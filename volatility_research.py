"""Offline European-option research. No authority, persistence, feeds or defaults for carry.

Units: IV decimal, spot delta, theta/charm per calendar day, vega/vanna per
one volatility percentage point, volga per percentage point squared. ACT/365F.
Research fits are bounded to observed strikes; diagnostics are not arbitrage proofs.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from datetime import date
from zoneinfo import ZoneInfo

import numpy as np
from scipy.optimize import brentq, least_squares, linprog
from scipy.stats import norm

from derivative_contracts import stamp
from iv_surface import black_scholes_price, black_scholes_greeks, implied_volatility

VERSION = "volatility-research-v1"
YEAR = 365 * 86400


class ResearchError(ValueError):
    """Non-sensitive input failure; never include an uploaded payload in the message."""


def finite(value, *, positive=False):
    if value is None or isinstance(value, bool):
        raise ResearchError("Missing/invalid number")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ResearchError("Missing/invalid number") from None
    if not math.isfinite(value) or (positive and value <= 0):
        raise ResearchError("Non-finite/non-positive number")
    return value


@dataclass(frozen=True)
class Valuation:
    spot: float
    strike: float
    years: float
    rate: float
    dividend_yield: float
    kind: str

    def __post_init__(self):
        for name in ("spot", "strike", "years"):
            object.__setattr__(self, name, finite(getattr(self, name), positive=True))
        for name in ("rate", "dividend_yield"):
            object.__setattr__(self, name, finite(getattr(self, name)))
        if self.kind not in {"CE", "PE"}:
            raise ResearchError("Only European CE/PE supported")
        if self.years > 10 or abs(self.rate) > 1 or abs(self.dividend_yield) > 1:
            raise ResearchError("Outside supported model domain")

    @property
    def forward(self):
        return self.spot * math.exp((self.rate - self.dividend_yield) * self.years)

    def price(self, iv):
        return float(black_scholes_price(
            self.spot, self.strike, self.years, finite(iv, positive=True),
            option_type=self.kind, risk_free_rate=self.rate, dividend_yield=self.dividend_yield))

    def solve(self, price):
        iv = implied_volatility(finite(price, positive=True), self.spot, self.strike,
                                self.years, option_type=self.kind,
                                risk_free_rate=self.rate, dividend_yield=self.dividend_yield)
        if iv is None or not 1e-4 < iv < 5:
            raise ResearchError("IV unidentifiable in supported solver range")
        return float(iv)

    def greeks(self, iv):
        iv = finite(iv, positive=True)
        g = {k: float(v) for k, v in black_scholes_greeks(
            self.spot, self.strike, self.years, iv, option_type=self.kind,
            risk_free_rate=self.rate, dividend_yield=self.dividend_yield).items()}
        t = self.years
        d1 = (math.log(self.spot / self.strike) +
              (self.rate - self.dividend_yield + iv * iv / 2) * t) / (iv * math.sqrt(t))
        d2 = d1 - iv * math.sqrt(t)
        g["vanna"] = float(-math.exp(-self.dividend_yield * t) * norm.pdf(d1) * d2 / iv / 100)
        g["volga"] = g["vega"] * d1 * d2 / iv / 100
        # Charm is d(delta)/d(calendar time), holding spot, IV and carry fixed.
        sign = 1 if self.kind == "CE" else -1
        d1_dt = ((self.rate - self.dividend_yield + iv * iv / 2) * t -
                 math.log(self.spot / self.strike)) / (2 * iv * t ** 1.5)
        g["charm"] = float(math.exp(-self.dividend_yield * t) *
                           (self.dividend_yield * sign * norm.cdf(sign * d1) -
                            norm.pdf(d1) * d1_dt) / 365)
        return g


def greek_consistency(v, bid, ask, provider, conventions, tolerances):
    """Shadow check, never an authorization token. Tolerances must be explicit.

    Provider data already normalized to the declared convention. No unit guessing.
    The diagnostic envelope samples interior IVs too, not only the endpoints.
    """
    required = {"model": "BSM_SPOT", "iv": "DECIMAL", "theta": "CALENDAR_DAY",
                "vega": "VOL_POINT", "quantity": "PER_UNIT", "day_count": "ACT365F"}
    result = {"status": "NOT_COMPARABLE", "approval_eligible": False}
    if conventions != required:
        return dict(result, reason="Unconfirmed provider conventions")
    if v.years*YEAR < 60:
        return dict(result, status="UNSTABLE", reason="Last-minute expiry outside comparison domain")
    try:
        bid, ask = finite(bid, positive=True), finite(ask, positive=True)
        if bid > ask:
            raise ResearchError("Crossed book")
        low, high = v.solve(bid), v.solve(ask)
        sigma = finite(provider.get("iv"), positive=True)
        actual = {k: finite(provider.get(k)) for k in ("delta", "gamma", "theta", "vega")}
        bounds = {k: (finite(tolerances[k][0]), finite(tolerances[k][1])) for k in actual}
        if any(min(pair) < 0 for pair in bounds.values()):
            raise ResearchError("Negative tolerance")
        local = v.greeks(sigma)
        envelope = [v.greeks(float(x)) for x in np.linspace(low, high, 33)]
        failures = [k for k, value in actual.items()
                    if abs(value - local[k]) > bounds[k][0] +
                    bounds[k][1] * max(abs(value), abs(local[k]))]
        if not low <= sigma <= high:
            failures.append("iv_outside_book_interval")
        return dict(result, status="MISMATCH" if failures else "CONSISTENT",
                    failures=failures, local=local, iv_bid=low, iv_ask=high,
                    envelope={k: [min(g[k] for g in envelope), max(g[k] for g in envelope)]
                              for k in local},
                    limitation="Conditional same-feed arithmetic check; sampled envelope, not a proof")
    except (ValueError, TypeError, KeyError, OverflowError):
        return dict(result, reason="Missing inputs or unstable IV calculation")


def svi(k, parameters):
    a, b, rho, m, s = parameters
    x = np.asarray(k) - m
    return a + b * (rho * x + np.sqrt(x * x + s * s))


def density_diagnostic(k, parameters):
    """Gatheral/Jacquier g(k); finite-grid diagnostic, NOT global certification."""
    a, b, rho, m, s = parameters
    x = np.asarray(k) - m
    root = np.sqrt(x*x + s*s)
    w = svi(k, parameters)
    wp = b * (rho + x / root)
    wpp = b * s*s / root**3
    return (1 - np.asarray(k)*wp/(2*w))**2 - wp**2/4*(1/w + .25) + wpp/2


def fit_smile(points):
    """Fit OTM observations in log-forward-moneyness; do not fabricate wings."""
    if len(points) < 7:
        return {"status": "INSUFFICIENT_STRIKES", "count": len(points)}
    k = np.array([p["k"] for p in points])
    w = np.array([p["iv_mid"]**2 * p["years"] for p in points])
    scale = np.array([max((p["iv_ask"]**2-p["iv_bid"]**2)*p["years"], 1e-8)
                      for p in points])
    if len(set(k)) != len(k) or min(k) >= 0 or max(k) <= 0:
        return {"status": "INSUFFICIENT_WING_COVERAGE"}
    candidates = []
    for rho in (-.6, 0, .6):
        fit = least_squares(lambda p: (svi(k, p)-w)/scale,
                            [max(float(np.median(w))/2, 1e-7), .02, rho, 0, .1],
                            bounds=([1e-10, 0, -.999, -2, .001], [10, 2, .999, 2, 2]),
                            max_nfev=600)
        if fit.success and np.all(np.isfinite(fit.x)):
            candidates.append(fit)
    if not candidates:
        return {"status": "FIT_FAILED"}
    fit = min(candidates, key=lambda f: float(np.sum(f.fun**2)))
    grid = np.linspace(min(k), max(k), 201)
    density_min = float(min(density_diagnostic(grid, fit.x)))
    residual = float(max(abs(fit.fun)))
    usable = density_min >= 0 and residual <= 1
    return dict(status="RESEARCH_FIT" if usable else "REJECTED_FIT",
                parameters=fit.x.tolist(), k_min=float(min(k)), k_max=float(max(k)),
                min_sampled_density=density_min, max_spread_scaled_residual=residual,
                count=len(points), extrapolation=False,
                grid=[dict(k=float(x), iv=float(math.sqrt(svi(x, fit.x)/points[0]["years"])))
                      for x in grid] if usable else [])


def strike_feasibility(rows, v):
    """Can SOME prices within observed books obey parity, slope and convexity?

    Convert puts to calls using reviewed carry; intersect call/put intervals.
    This checks observed strikes only, before trusting a smooth fit.
    """
    d = math.exp(-v.rate*v.years)
    books = {}
    for row in rows:
        k = row["strike"]
        shift = d*(v.forward-k) if row["kind"] == "PE" else 0
        lo, hi = row["bid"]+shift, row["ask"]+shift
        lo, hi = max(lo, d*max(v.forward-k, 0)), min(hi, d*v.forward)
        if k in books:
            lo, hi = max(lo, books[k][0]), min(hi, books[k][1])
        if lo > hi:
            return "INFEASIBLE_BOOKS"
        books[k] = (lo, hi)
    strikes = sorted(books)
    if len(strikes) < 3:
        return "INSUFFICIENT_STRIKES"
    n, matrix, rhs = len(strikes), [], []
    for i in range(n-1):
        row = np.zeros(n)
        row[i+1], row[i] = 1, -1
        matrix.extend([row, -row])
        rhs.extend([0, d*(strikes[i+1]-strikes[i])])
    for i in range(n-2):
        h1, h2 = strikes[i+1]-strikes[i], strikes[i+2]-strikes[i+1]
        row = np.zeros(n)
        row[i:i+3] = [-1/h1, 1/h1+1/h2, -1/h2]
        matrix.append(row)
        rhs.append(0)
    fit = linprog(np.zeros(n), A_ub=matrix, b_ub=rhs,
                  bounds=[books[k] for k in strikes], method="highs")
    return "FEASIBLE_OBSERVED_BOOKS" if fit.success else "INFEASIBLE_OR_SOLVER_FAILED"


def same_delta(smile, v, target):
    target = finite(target)
    if smile.get("status") != "RESEARCH_FIT":
        return {"status": "UNAVAILABLE"}
    def residual(k):
        iv = math.sqrt(float(svi(k, smile["parameters"]))/v.years)
        at = Valuation(v.spot, v.forward*math.exp(k), v.years, v.rate, v.dividend_yield, v.kind)
        return at.greeks(iv)["delta"]-target
    grid = np.linspace(smile["k_min"], smile["k_max"], 201)
    roots = []
    for left, right in zip(grid[:-1], grid[1:]):
        if residual(left) == 0:
            roots.append(float(left))
        elif residual(left)*residual(right) < 0:
            roots.append(float(brentq(residual, left, right)))
    if residual(grid[-1]) == 0:
        roots.append(float(grid[-1]))
    if len(roots) != 1:
        return {"status": "OUTSIDE_COVERAGE_OR_AMBIGUOUS"}
    k = roots[0]
    return dict(status="RESEARCH_ESTIMATE", delta=target, strike=v.forward*math.exp(k),
                iv=math.sqrt(float(svi(k, smile["parameters"]))/v.years))


def history_statistics(history, *, current_iv, series_key, as_of, lookback=252, sessions=None):
    """One past session per declared constant-tenor/delta/source/capture series.

    Never splice expiry-specific ATM observations into a constant-maturity index.
    Percentile uses strictly lower observations; flat-history rank is undefined.
    """
    current_iv = finite(current_iv, positive=True)
    as_of = stamp(as_of)
    if not isinstance(lookback, int) or isinstance(lookback, bool) or lookback < 2:
        raise ResearchError("History window must contain at least two sessions")
    if sessions is not None:
        if (len(sessions) != lookback or sessions != sorted(set(sessions)) or
                any(date.fromisoformat(s) >= as_of.astimezone(ZoneInfo('Asia/Kolkata')).date() for s in sessions)):
            raise ResearchError('Expected prior completed-session calendar')
    selected = {}
    for row in history:
        if row.get("series_key") != series_key:
            continue
        observed, available = stamp(row["observed_at"]), stamp(row["available_at"])
        if observed > available:
            raise ResearchError("History time ordering invalid")
        if available >= as_of:
            continue
        session = date.fromisoformat(row["session_date"]).isoformat()
        if session != observed.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat():
            raise ResearchError("Historical session/date mismatch")
        if session >= as_of.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat():
            continue
        if sessions is not None and session not in sessions:
            continue
        if session in selected:
            raise ResearchError("Duplicate historical session")
        selected[session] = finite(row["iv"], positive=True)
    values = [selected[k] for k in sorted(selected)[-lookback:]]
    if len(values) < lookback:
        return dict(status="INSUFFICIENT_HISTORY", count=len(values), required=lookback)
    low, high = min(values), max(values)
    return dict(status="RESEARCH_STATISTIC", count=len(values),
                calendar_coverage_confirmed=sessions is not None,
                iv_rank=None if high == low else 100*(current_iv-low)/(high-low),
                iv_percentile=100*sum(x < current_iv for x in values)/len(values),
                rank_clipped=False, percentile_definition="strictly lower prior observations")


def realized_volatility(rows, *, sessions, as_of, adjustment_version, annual_sessions=252):
    """Adjusted consecutive daily closes; missing sessions are never interpolated."""
    if len(sessions) < 3 or len(set(sessions)) != len(sessions) or sessions != sorted(sessions):
        raise ResearchError("Ordered unique completed-session calendar required")
    if not adjustment_version:
        raise ResearchError("Adjusted-price lineage required")
    today = stamp(as_of).astimezone(ZoneInfo('Asia/Kolkata')).date()
    if any(date.fromisoformat(s) >= today for s in sessions):
        raise ResearchError("Only prior completed sessions permitted")
    available = {}
    for row in rows:
        if row.get("session_date") not in sessions:
            continue
        if row["session_date"] in available:
            raise ResearchError("Duplicate underlying session")
        if (row.get("adjustment_version") != adjustment_version or stamp(row["available_at"]) > stamp(as_of)
                or stamp(row["available_at"]).astimezone(ZoneInfo('Asia/Kolkata')).date() < date.fromisoformat(row['session_date'])):
            raise ResearchError("Unavailable or inconsistent adjusted history")
        available[row["session_date"]] = finite(row["close"], positive=True)
    if len(available) != len(sessions):
        return dict(status="INSUFFICIENT_HISTORY", count=len(available))
    returns = np.diff(np.log([available[x] for x in sessions]))
    return dict(status="RESEARCH_STATISTIC", realized_iv=float(np.std(returns, ddof=1)*
                math.sqrt(finite(annual_sessions, positive=True))), returns=len(returns),
                first_session=sessions[0], last_session=sessions[-1],
                method="sample standard deviation of adjusted daily log returns")


def event_scenario(v, iv, *, spot_return, iv_change_points, elapsed_days, signed_units):
    """User-defined full repricing, NOT predicted IV crush or expected P&L."""
    iv = finite(iv, positive=True)
    shock, elapsed = finite(spot_return), finite(elapsed_days)
    units = finite(signed_units)
    new_iv = iv + finite(iv_change_points)/100
    if shock <= -1 or elapsed < 0 or elapsed/365 >= v.years or new_iv <= 0:
        raise ResearchError("Scenario outside pre-expiry model domain")
    after = Valuation(v.spot*(1+shock), v.strike, v.years-elapsed/365,
                      v.rate, v.dividend_yield, v.kind)
    return dict(status="HYPOTHETICAL", gross_pnl=(after.price(new_iv)-v.price(iv))*units,
                excludes="spreads, fees, fills, margin and physical settlement",
                assumption="sticky strike IV shock; carry unchanged")


def constant_tenor(slices, target_days):
    """Forward-ATM total-variance interpolation, never nearest-expiry substitution."""
    t = finite(target_days, positive=True)/365
    points = []
    for sl in slices:
        smile = sl['smile']
        if smile['status'] == 'RESEARCH_FIT' and smile['k_min'] <= 0 <= smile['k_max']:
            points.append((sl['years'], float(svi(0, smile['parameters']))))
    points.sort()
    for years, variance in points:
        if abs(years-t) < 1e-12:
            return dict(status='RESEARCH_ESTIMATE', iv=math.sqrt(variance/t), target_days=target_days)
    for (t1, w1), (t2, w2) in zip(points[:-1], points[1:]):
        if t1 < t < t2:
            if w2 < w1:
                return dict(status='NEGATIVE_FORWARD_VARIANCE')
            return dict(status='RESEARCH_ESTIMATE', iv=math.sqrt((w1+(w2-w1)*(t-t1)/(t2-t1))/t),
                        target_days=target_days)
    return dict(status='INSUFFICIENT_EXPIRY_COVERAGE')


def analyze_bundle(bundle):
    """Explicit, captured input bundle; never accept live-chain defaults as metadata."""
    if not isinstance(bundle, dict) or bundle.get("schema_version") != 1:
        raise ResearchError("Expected research bundle schema_version 1")
    for key in ("underlying", "source", "snapshot_id", "convention_version"):
        if not isinstance(bundle.get(key), str) or not bundle[key].strip():
            raise ResearchError("Research provenance required")
    as_of = stamp(bundle["as_of"])
    max_age = finite(bundle["max_age_seconds"], positive=True)
    max_skew = finite(bundle["max_skew_seconds"], positive=True)
    slices = bundle.get("slices")
    scenarios = bundle.get('scenarios', [])
    if not isinstance(scenarios, list) or len(scenarios) > 12:
        raise ResearchError('Maximum 12 scenarios')
    if not isinstance(slices, list) or not 1 <= len(slices) <= 12:
        raise ResearchError("Require 1-12 expiry slices")
    output, seen_expiries = [], set()
    all_times = []
    for sl in slices:
        expiry = stamp(sl["expiry_at"])
        if expiry in seen_expiries:
            raise ResearchError("Duplicate expiry slice")
        seen_expiries.add(expiry)
        t = (expiry-as_of).total_seconds()/YEAR
        if t <= 0:
            raise ResearchError("Expired slice")
        if sl.get("exercise") != "EUROPEAN" or not sl.get("carry_source") or not sl.get("adjustment_version"):
            raise ResearchError("Reviewed exercise/carry/adjustment metadata required")
        reference_time = stamp(sl["reference_at"])
        all_times.append(reference_time)
        v = Valuation(sl["spot"], sl["spot"], t, sl["rate"], sl["dividend_yield"], "CE")
        rows, selected, seen, diagnostics = [], {}, set(), []
        contracts = sl.get("contracts")
        if not isinstance(contracts, list) or not 1 <= len(contracts) <= 300:
            raise ResearchError("Require 1-300 contracts per expiry")
        for raw in contracts:
            if not raw.get("instrument_key") or not raw.get("contract_version"):
                raise ResearchError("Contract lineage required")
            strike, kind = finite(raw["strike"], positive=True), raw["kind"]
            if (strike, kind) in seen:
                raise ResearchError("Duplicate strike/side")
            seen.add((strike, kind))
            observed, available = stamp(raw["source_at"]), stamp(raw["available_at"])
            if not observed <= available <= as_of:
                raise ResearchError("Quote timestamps out of order")
            all_times.extend([observed, available])
            bid, ask = finite(raw["bid"], positive=True), finite(raw["ask"], positive=True)
            if bid > ask:
                raise ResearchError("Crossed book")
            finite(raw["bid_size"], positive=True)
            finite(raw["ask_size"], positive=True)
            at = Valuation(v.spot, strike, t, v.rate, v.dividend_yield, kind)
            try:
                low, mid, high = (at.solve(x) for x in (bid, (bid+ask)/2, ask))
            except ResearchError:
                diagnostics.append(dict(instrument_key=raw["instrument_key"], status="IV_UNAVAILABLE"))
                continue
            row = dict(instrument_key=raw["instrument_key"], strike=strike, kind=kind,
                       bid=bid, ask=ask, k=math.log(strike/v.forward), years=t,
                       iv_bid=low, iv_mid=mid, iv_ask=high, greeks=at.greeks(mid))
            row["consistency"] = greek_consistency(at, bid, ask, raw.get("provider", {}),
                    bundle.get("provider_conventions"), bundle.get("tolerances", {}))
            row["scenarios"] = [event_scenario(at, mid, **scenario)
                                for scenario in bundle.get("scenarios", [])]
            rows.append(row)
            if (strike < v.forward and kind == "PE") or (strike >= v.forward and kind == "CE"):
                selected[strike] = row
        feasibility = strike_feasibility(rows, v)
        smile = fit_smile(list(selected.values())) if feasibility == "FEASIBLE_OBSERVED_BOOKS" else {"status": "REJECTED_BOOKS"}
        deltas = {}
        for kind, target in (("CE", .25), ("PE", -.25), ("CE", .5)):
            at = Valuation(v.spot, v.strike, t, v.rate, v.dividend_yield, kind)
            deltas[kind+str(target)] = same_delta(smile, at, target)
        output.append(dict(expiry=expiry.isoformat(), years=t, forward=v.forward,
                           books=feasibility, smile=smile, same_delta=deltas,
                           contracts=rows, diagnostics=diagnostics))
    if any(not 0 <= (as_of-x).total_seconds() <= max_age for x in all_times):
        raise ResearchError("Stale/future input snapshot")
    if (max(all_times)-min(all_times)).total_seconds() > max_skew:
        raise ResearchError("Snapshot inputs not aligned")
    output.sort(key=lambda x: x["years"])
    calendars = []
    for near, far in zip(output[:-1], output[1:]):
        a, b = near["smile"], far["smile"]
        record = dict(near=near["expiry"], far=far["expiry"], status="UNAVAILABLE")
        if a["status"] == b["status"] == "RESEARCH_FIT":
            lo, hi = max(a["k_min"], b["k_min"]), min(a["k_max"], b["k_max"])
            if lo < hi:
                grid = np.linspace(lo, hi, 201)
                diff = svi(grid, b["parameters"])-svi(grid, a["parameters"])
                record.update(status="NEGATIVE_FORWARD_VARIANCE" if min(diff) < -1e-10 else "NO_SAMPLED_DECREASE",
                              min_total_variance_increment=float(min(diff)))
        calendars.append(record)
    historical = {'status': 'NOT_REQUESTED'}
    rv = {'status': 'NOT_REQUESTED'}
    constant = {'status': 'NOT_REQUESTED'}
    history = bundle.get('history')
    if history is not None:
        if not isinstance(history, dict) or len(history.get('rows', [])) > 5000:
            raise ResearchError('Invalid/oversized history')
        if not history.get('capture_context'):
            raise ResearchError('Consistent historical capture context required')
        constant = constant_tenor(output, history['target_days'])
        series_key = '|'.join([VERSION, bundle['underlying'], bundle['source'],
                               bundle['convention_version'], history['capture_context'],
                               str(finite(history['target_days'], positive=True)), 'FORWARD_ATM'])
        historical = {'status': 'CURRENT_CONSTANT_TENOR_UNAVAILABLE', 'series_key': series_key}
        if 'iv' in constant:
            historical = dict(history_statistics(history.get('rows', []), current_iv=constant['iv'],
                              series_key=series_key, as_of=as_of, lookback=252,
                              sessions=history['sessions']), series_key=series_key)
    if bundle.get('realized') is not None:
        spec = bundle['realized']
        if len(spec.get('rows', [])) > 5000 or len(spec.get('sessions', [])) > 1000:
            raise ResearchError('Oversized realized history')
        rv = realized_volatility(spec['rows'], sessions=spec['sessions'], as_of=as_of,
                                 adjustment_version=spec['adjustment_version'],
                                 annual_sessions=spec['annual_sessions'])
        if 'iv' in constant and 'realized_iv' in rv:
            rv['iv_minus_trailing_rv'] = constant['iv']-rv['realized_iv']
            rv['comparison'] = 'Forward implied vs trailing realized; NOT a forecast or expected premium'
            rv['implied_horizon_calendar_days'] = constant['target_days']
            rv['realized_horizon_calendar_days'] = (date.fromisoformat(rv['last_session'])-
                                                    date.fromisoformat(rv['first_session'])).days
    canonical = json.dumps(bundle, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return dict(engine_version=VERSION, mode="RESEARCH_ONLY", approval_eligible=False,
                input_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
                as_of=as_of.isoformat(), slices=output, calendar_diagnostics=calendars,
                constant_tenor=constant, iv_history=historical, realized=rv,
                limitations=["Same-feed model calculations are not independent prices",
                             "Finite-grid fitted diagnostics are not global arbitrage certification",
                             "No regulatory deltas, fill evidence or promotion authority"])
