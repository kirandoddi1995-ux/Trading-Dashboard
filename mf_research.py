"""Mutual-fund disclosures and chronological forecast evaluation.

No trading, credentials, learned parameters, or Streamlit session state live here.
Official data is matched by scheme, never inferred from a fund's volatility.
"""

import concurrent.futures
import datetime as dt
import io
import json
import re
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

import numpy as np
import pandas as pd
import requests
import observability


AMFI = "https://www.amfiindia.com"
PERFORMANCE_SOURCE = AMFI + "/otherdata/fund-performance"
RISK_SOURCE = AMFI + "/online-center/risk-o-meter"
GATEWAY = AMFI + "/gateway/pollingsebi/api/amfi/"
RISK_LEVELS = ("Low", "Low to Moderate", "Moderate", "Moderately High", "High", "Very High")
MODEL_VERSION = "MF-block-bootstrap-v2"

# IDs are resolved from AMFI's category list, not guessed from scheme names.
CATEGORY_GROUPS = {
    "Large Cap": (1, "Large Cap"), "Large & Mid Cap": (1, "Large & Mid Cap"),
    "Flexi Cap": (1, "Flexi Cap"), "Multi Cap": (1, "Multi Cap"),
    "Mid Cap": (1, "Mid Cap"), "Small Cap": (1, "Small Cap"), "ELSS (Tax Saver)": (1, "ELSS"),
    "Liquid": (2, "Liquid"), "Overnight": (2, "Overnight"), "Money Market": (2, "Money Market"),
    "Short Duration Debt": (2, "Short Duration"), "Low Duration Debt": (2, "Low Duration"),
    "Ultra Short Duration Debt": (2, "Ultra Short Duration"), "Corporate Bond": (2, "Corporate Bond"),
    "Banking & PSU Debt": (2, "Banking and PSU"), "Gilt": (2, "Gilt"),
    "Balanced Advantage": (3, "Dynamic Asset Allocation or Balanced Advantage"),
    "Aggressive Hybrid": (3, "Aggressive Hybrid"),
}


def canonical_name(value):
    value = str(value or "").lower()
    value = re.sub(r"\([^)]*(?:erstwhile|formerly)[^)]*\)", " ", value)
    value = re.sub(r"\b(?:direct|regular)\s*(?:plan)?\b", " ", value)
    value = re.sub(r"\b(?:growth|idcw|dividend|reinvestment|payout)\s*(?:option)?\b", " ", value)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def finite_number(value):
    try:
        result = float(str(value).replace(",", "").replace("%", "").strip())
        return result if np.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def normalize_risk(value):
    text = " ".join(str(value or "").lower().replace("-", " ").split())
    text = re.sub(r"\s+risk$", "", text).strip()
    return next((label for label in RISK_LEVELS if label.lower() == text), None)


def _get(url, *, session=None, params=None, max_bytes=12_000_000):
    """Only fixed official URLs are passed by this module; never user-supplied URLs."""
    client = session or requests
    response = observability.observed_request(
        client, "GET", url, params=params, timeout=(4, 12), stream=True,
    )
    try:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("Official response exceeded size limit")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        response.close()


class _ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts, self.inside = [], False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.scripts.append(data)


def parse_amfi_directory(html):
    parser = _ScriptParser()
    parser.feed(html)
    chunks = []
    for script in parser.scripts:
        marker = "self.__next_f.push("
        if marker not in script:
            continue
        try:
            value = json.loads(script.split(marker, 1)[1].rsplit(")", 1)[0])
            if len(value) > 1 and isinstance(value[1], str):
                chunks.append(value[1])
        except (ValueError, IndexError):
            continue
    found = {}

    def visit(value):
        if isinstance(value, dict):
            if value.get("mf_id") and value.get("mf_name"):
                found[canonical_name(value["mf_name"])] = {
                    "id": str(value["mf_id"]), "name": value["mf_name"],
                    "risk_url": value.get("amc_riskometer_monthly") or RISK_SOURCE,
                }
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for line in "".join(chunks).splitlines():
        if '"mf_id"' in line:
            try:
                visit(json.loads(line.split(":", 1)[1]))
            except ValueError:
                continue
    if not found:
        raise ValueError("AMFI disclosure directory format changed")
    return found


def parse_scheme_summary(xml_bytes, expected_name):
    """Read labelled cells only; ignore launch risk and never treat save-date as risk-date."""
    if len(xml_bytes) > 3_000_000 or re.search(br"<!\s*(DOCTYPE|ENTITY)", xml_bytes, re.I):
        raise ValueError("Unsupported XML document")
    root = ET.fromstring(xml_bytes)
    fields = {}
    for row in root.findall(".//{*}Row"):
        cells = [" ".join(cell.itertext()).strip() for cell in row.findall("{*}Cell/{*}Data")]
        cells = [cell for cell in cells if cell]
        if cells and re.fullmatch(r"\d+(?:\.0)?", cells[0]):
            cells = cells[1:]
        if len(cells) >= 2:
            fields[canonical_name(cells[0])] = " ".join(cells[1:])
    # AMFI publishes both Excel SpreadsheetML and a field-named XML schema.
    # HDFC/Nippon and other AMCs use the latter, without Row/Cell/Data nodes.
    if root.tag.split("}")[-1] == "SchemeSummaryDocument":
        for node in root.iter():
            if len(node) == 0 and node.text and node.text.strip():
                fields[canonical_name(node.tag.split("}")[-1])] = node.text.strip()
    name = fields.get("fund name") or fields.get("scheme name")
    if not name or canonical_name(name) != canonical_name(expected_name):
        raise ValueError("Scheme summary did not match the requested fund")
    risk = next((normalize_risk(value) for key, value in fields.items()
                 if "riskometer" in key and "as on" in key and "benchmark" not in key), None)
    benchmark = next((value for key, value in fields.items() if "benchmark" in key and "tier 1" in key), None)
    saved = root.find(".//{*}LastSaved")
    document_date = pd.to_datetime(saved.text, errors="coerce", utc=True) if saved is not None else pd.NaT
    return {
        "scheme_name": name, "riskometer": risk, "benchmark_name": benchmark,
        "document_date": document_date.date().isoformat() if pd.notna(document_date) else None,
        "risk_as_of": None, "performance_as_of": None,
        "risk_source_type": "AMFI scheme summary (not a verified current monthly reading)",
        "risk_verified_current": False,
    }


def _summary_for_scheme(scheme, listings, directory):
    house = canonical_name(scheme.get("fundHouse"))
    name = canonical_name(scheme.get("schemeName"))
    matches = [item for item in listings.get(house, []) if canonical_name(item.get("scheme_name")) == name]
    if len(matches) != 1:
        return {"status": "No unambiguous official scheme match"}
    scheme_id = str(matches[0].get("scheme_id", ""))
    if not scheme_id.isascii() or not scheme_id.isdigit():
        return {"status": "Invalid official scheme identifier"}
    source = f"https://portal.amfiindia.com/spages/SSD_{scheme_id}.xml"
    result = parse_scheme_summary(_get(source, max_bytes=3_000_000), scheme["schemeName"])
    result.update(source_url=source, risk_monthly_url=directory[house]["risk_url"], status="Summary available")
    return result


def _post_report(session, route, payload):
    response = observability.observed_request(
        session, "POST", GATEWAY + route, json=payload, timeout=(4, 12),
    )
    response.raise_for_status()
    if len(response.content) > 12_000_000:
        raise ValueError("Performance report too large")
    data = response.json()
    if data.get("validationMsg") != "SUCCESS":
        raise ValueError("Official performance service rejected request")
    return data.get("data")


def parse_performance_rows(rows, as_of, source_url=PERFORMANCE_SOURCE):
    """Direct-plan and benchmark returns must come from the SAME dated report."""
    parsed = []
    for row in rows or []:
        name = row.get("schemeName") or row.get("scheme") or row.get("fundName")
        if not name:
            continue
        record = {
            "scheme_name": name, "benchmark_name": row.get("benchmark"),
            "riskometer": normalize_risk(row.get("riskometerScheme")),
            "benchmark_riskometer": normalize_risk(row.get("riskometerBenchmark")),
            "performance_as_of": as_of, "risk_as_of": None,
            "risk_source_type": "AMFI performance report; monthly risk date not supplied",
            "risk_verified_current": False, "source_url": source_url,
            "official_ir_3y": finite_number(row.get("ir3YrDirect")),
        }
        for years in (1, 3, 5):
            record[f"official_fund_{years}y"] = finite_number(row.get(f"return{years}YearDirect"))
            record[f"official_benchmark_{years}y"] = finite_number(row.get(f"return{years}YearBenchmark"))
        parsed.append(record)
    return parsed


def fetch_performance_report(category_name):
    if category_name not in CATEGORY_GROUPS:
        raise ValueError("Category not supported by the official performance adapter")
    group_id, expected = CATEGORY_GROUPS[category_name]
    with requests.Session() as session:
        subcategories = _post_report(session, "getsubcategory", {"category": group_id})
        matches = [r for r in subcategories or [] if canonical_name(r.get("name")) == canonical_name(expected)]
        if len(matches) != 1:
            raise ValueError("Official performance category could not be matched")
        # Request only completed weekdays. A weekend/holiday empty report gets one earlier retry.
        day = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).date() - dt.timedelta(days=1)
        for attempt in range(2):
            while day.weekday() >= 5:
                day -= dt.timedelta(days=1)
            rows = _post_report(session, "fundperformance", {
                "maturityType": 1, "category": group_id, "subCategory": matches[0]["id"],
                "mfid": 0, "reportDate": day.strftime("%d-%b-%Y"),
            })
            if rows:
                result = parse_performance_rows(rows, day.isoformat())
                if result:
                    return result
            day -= dt.timedelta(days=1)
    raise ValueError("Official performance report is empty")


def fetch_official_disclosures(schemes, category_name, budget_seconds=40):
    """Bounded read-only retrieval. Failures are visible and not turned into zero metrics."""
    started = time.monotonic()
    records, errors = {}, []
    try:
        performance = fetch_performance_report(category_name)
    except Exception as exc:
        performance = []
        response = getattr(exc, "response", None)
        detail = f"HTTP {response.status_code}" if response is not None else type(exc).__name__
        errors.append(f"AMFI's dated benchmark-return report could not be retrieved ({detail}).")
    for scheme in schemes:
        matches = [r for r in performance if canonical_name(r["scheme_name"]) == canonical_name(scheme["schemeName"])]
        if len(matches) == 1:
            records[str(scheme["schemeCode"])] = dict(matches[0])
    missing = [s for s in schemes if str(s["schemeCode"]) not in records]
    if not missing:
        return {"records": records, "errors": errors}
    try:
        directory = parse_amfi_directory(_get(RISK_SOURCE).decode("utf-8"))
    except Exception as exc:
        errors.append("AMFI disclosure directory unavailable: " + type(exc).__name__)
        return {"records": records, "errors": errors}
    houses = {canonical_name(s.get("fundHouse")) for s in missing}
    listings = {}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    try:
        jobs = {executor.submit(_get, AMFI + "/api/populate-scheme", params={"MF_ID": directory[h]["id"]}): h
                for h in houses if h in directory and directory[h]["id"].isdigit()}
        done, pending = concurrent.futures.wait(jobs, timeout=max(0, budget_seconds - (time.monotonic() - started)))
        for future in done:
            try:
                listings[jobs[future]] = json.loads(future.result())
            except Exception:
                pass
        for future in pending:
            future.cancel()
        jobs = {executor.submit(_summary_for_scheme, s, listings, directory): str(s["schemeCode"])
                for s in missing if canonical_name(s.get("fundHouse")) in listings}
        done, pending = concurrent.futures.wait(jobs, timeout=max(0, budget_seconds - (time.monotonic() - started)))
        for future in done:
            try:
                records[jobs[future]] = future.result()
            except Exception as exc:
                records[jobs[future]] = {"status": "Summary unavailable: " + type(exc).__name__}
        for future in pending:
            future.cancel()
        if pending:
            errors.append("Official disclosure lookup reached its time budget; retry uses the cached completed scan")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return {"records": records, "errors": errors}


def benchmark_comparison(record, as_of=None):
    """Do not compare an older benchmark return with today's fund CAGR."""
    today = pd.Timestamp(as_of or dt.date.today()).normalize()
    date = pd.to_datetime(record.get("performance_as_of"), errors="coerce")
    valid_date = pd.notna(date) and 0 <= (today - date).days <= 45
    result = {"comparison_status": "Available" if valid_date else "Unavailable or dated report older than 45 days"}
    for years in (1, 3, 5):
        fund = finite_number(record.get(f"official_fund_{years}y"))
        benchmark = finite_number(record.get(f"official_benchmark_{years}y"))
        result[f"excess_{years}y_pp"] = fund - benchmark if valid_date and fund is not None and benchmark is not None else None
    return result


def risk_disclosure_status(record, as_of=None):
    if not record.get("riskometer"):
        return "Risk label unavailable"
    today = pd.Timestamp(as_of or dt.date.today()).normalize()
    effective = pd.to_datetime(record.get("risk_as_of"), errors="coerce")
    if pd.notna(effective):
        age = (today - effective).days
        prefix = "User supplied; " if record.get("imported") else ""
        return prefix + (f"Stale: effective {age} days ago" if age > 60 else f"Effective {effective.date().isoformat()}; verify latest monthly disclosure")
    saved = pd.to_datetime(record.get("document_date"), errors="coerce")
    if pd.notna(saved) and (today - saved).days > 60:
        return "Old summary; current monthly risk not verified"
    return "Risk effective date unknown; current monthly risk not verified"


def parse_disclosure_csv(payload, as_of=None):
    """Session-local fallback; imported values are labelled user supplied, not API verified."""
    if len(payload) > 2_000_000:
        raise ValueError("Disclosure CSV must be smaller than 2 MB")
    frame = pd.read_csv(io.BytesIO(payload), dtype=str).fillna("")
    required = {"scheme_code", "scheme_name", "benchmark_name", "performance_as_of", "source_url"}
    if not required.issubset(frame.columns):
        raise ValueError("CSV requires: " + ", ".join(sorted(required)))
    today = pd.Timestamp(as_of or dt.date.today()).normalize()
    output = {}
    for row in frame.to_dict("records"):
        code = row["scheme_code"].strip()
        if not re.fullmatch(r"[0-9]{4,7}", code) or code in output:
            raise ValueError("Each row needs a unique numeric AMFI scheme code")
        if not re.fullmatch(r"https://[^\s<>\"']+", row["source_url"]):
            raise ValueError("Each record needs an HTTPS disclosure source URL")
        for field in ("performance_as_of", "risk_as_of"):
            if row.get(field):
                date = pd.to_datetime(row[field], format="%Y-%m-%d", errors="coerce")
                if pd.isna(date) or date > today:
                    raise ValueError("Disclosure dates must be valid ISO dates, not future dates")
                row[field] = date.date().isoformat()
        for field in ("riskometer", "benchmark_riskometer"):
            raw = row.get(field)
            row[field] = normalize_risk(raw)
            if raw and row[field] is None:
                raise ValueError("Unknown Riskometer label")
        for years in (1, 3, 5):
            for kind in ("fund", "benchmark"):
                key = f"official_{kind}_{years}y"
                raw = row.get(key)
                row[key] = finite_number(raw)
                if raw and row[key] is None:
                    raise ValueError("Return values must be numeric percentages or blank")
        row["official_ir_3y"] = finite_number(row.get("official_ir_3y"))
        row.update(risk_source_type="User-imported disclosure (not independently verified)",
                   risk_verified_current=False, imported=True)
        output[code] = row
    return output


def complete_monthly_nav(nav_df, as_of):
    """Preserve missing months and exclude incomplete calendar months; never forward-fill."""
    frame = nav_df.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["nav"] = pd.to_numeric(frame["nav"], errors="coerce")
    frame = frame.dropna().query("nav > 0").sort_values("date").drop_duplicates("date", keep="last")
    frame = frame[frame["date"] <= pd.Timestamp(as_of)]
    if frame.empty:
        return pd.Series(dtype=float)
    grouped = frame.set_index("date")
    nav = grouped["nav"].resample("ME").last()
    dates = pd.Series(grouped.index, index=grouped.index).resample("ME").last()
    # A quote from the beginning of a month is not a valid month-end observation.
    age = (pd.Series(nav.index, index=nav.index) - dates).dt.days
    return nav.where(age <= 7).loc[nav.index <= pd.Timestamp(as_of)]


def summarize_validation(folds):
    if not folds:
        return {"folds": 0, "status": "Insufficient history", "production_validated": False}
    frame = pd.DataFrame(folds)
    actual, forecast, baseline = frame["actual_net_pct"], frame["median_net_pct"], frame["baseline_net_pct"]
    outcome = (actual > 0).astype(float)
    brier = float(((frame["positive_probability"] - outcome) ** 2).mean())
    baseline_brier = float(((frame["baseline_probability"] - outcome) ** 2).mean())
    mae = float((forecast - actual).abs().mean())
    baseline_mae = float((baseline - actual).abs().mean())
    coverage = float(((actual >= frame["lower_net_pct"]) & (actual <= frame["upper_net_pct"])).mean() * 100)
    count = len(frame)
    status = "Limited sample" if count < 10 else "Historical improvement" if mae < baseline_mae and brier < baseline_brier else "Baseline not beaten"
    return {
        "folds": count, "status": status, "mae_pp": mae, "baseline_mae_pp": baseline_mae,
        "brier": brier, "baseline_brier": baseline_brier, "coverage_80_pct": coverage,
        "mean_interval_width_pp": float((frame["upper_net_pct"] - frame["lower_net_pct"]).mean()),
        "beats_baseline": mae < baseline_mae and brier < baseline_brier,
        "production_validated": False,
    }


def walk_forward_validate(histories, compute_fn, rank_fn, category_name, cost_pct=0.5, as_of=None):
    """Annual, non-overlapping 12-month holdouts for the deployed scenario model.

    All peers are selected using TRAINING data only; future availability cannot
    change the forecast. Current TER/AUM/Riskometer values never enter old folds.
    This evaluates scenarios, not the full current fund-ranking strategy. Current
    category membership still creates survivorship/reclassification limitations.
    """
    if not np.isfinite(cost_pct) or not 0 <= cost_pct <= 10:
        raise ValueError("Cost must be between 0 and 10 percent")
    as_of = pd.Timestamp(as_of or dt.date.today()).normalize()
    frames, monthly, metadata = {}, {}, {}
    for code, payload in histories.items():
        if not payload or not payload.get("data"):
            continue
        frame = pd.DataFrame(payload["data"])
        frame["date"] = pd.to_datetime(frame["date"], format="%d-%m-%Y", errors="coerce")
        frame["nav"] = pd.to_numeric(frame["nav"], errors="coerce")
        frame = frame.dropna().query("nav > 0").sort_values("date").drop_duplicates("date", keep="last")
        frame = frame[frame["date"] <= as_of]
        if frame.empty:
            continue
        frames[str(code)] = frame
        monthly[str(code)] = complete_monthly_nav(frame, as_of)
        metadata[str(code)] = payload.get("meta", {})
    if not frames:
        return {"model_version": MODEL_VERSION, "by_scheme": {}, "fold_rows": [], "cost_pct": cost_pct}
    first_year = min(frame["date"].min().year for frame in frames.values()) + 3
    origins = pd.date_range(f"{first_year}-12-31", as_of, freq="YE")
    outcomes = {code: [] for code in frames}
    for origin in origins:
        test_end = origin + pd.DateOffset(years=1)
        if test_end > as_of:
            continue
        training_stats = []
        for code, frame in frames.items():
            train = frame[frame["date"] <= origin]
            if train.empty or (origin - train["date"].max()).days > 7:
                continue
            payload = {"meta": metadata[code], "data": [
                {"date": row.date.strftime("%d-%m-%Y"), "nav": row.nav}
                for row in train.itertuples(index=False)
            ]}
            stats = compute_fn(payload, as_of_date=origin)
            if stats and stats.get("history_years", 0) >= 3 and stats.get("forecast_samples") is not None:
                stats.update(scheme_code=code, aum_crore=None)
                training_stats.append(stats)
        if not training_stats:
            continue
        predictions = rank_fn(training_stats, ter_map={}, category_name=category_name)
        for prediction in predictions:
            code = prediction["scheme_code"]
            prices = monthly[code]
            start, end = prices.get(origin), prices.get(test_end)
            if pd.isna(start) or pd.isna(end) or start is None or end is None or start <= 0:
                continue
            train_months = prices.loc[prices.index <= origin]
            train_annual = (train_months / train_months.shift(12) - 1).dropna().tail(60)
            if train_annual.empty:
                continue
            samples = np.asarray(prediction["forecast_samples"], dtype=float)
            cost_factor = 1.0 - cost_pct / 100.0
            net_samples = ((1.0 + samples / 100.0) * cost_factor - 1.0) * 100
            actual = (float(end) / float(start) * cost_factor - 1) * 100
            base_samples = ((1 + train_annual) * cost_factor - 1) * 100
            lower, median, upper = np.quantile(net_samples, [0.1, 0.5, 0.9])
            fold = {
                "scheme_code": code, "scheme_name": prediction["scheme_name"],
                "training_end": origin.date().isoformat(), "test_end": test_end.date().isoformat(),
                "training_last_nav": frames[code].loc[frames[code]["date"] <= origin, "date"].max().date().isoformat(),
                "actual_net_pct": float(actual), "median_net_pct": float(median),
                "lower_net_pct": float(lower), "upper_net_pct": float(upper),
                "positive_probability": float((net_samples > 0).mean()),
                "baseline_net_pct": float(base_samples.median()),
                "baseline_probability": float(((base_samples > 0).sum() + 1) / (len(base_samples) + 2)),
            }
            outcomes[code].append(fold)
    return {
        "model_version": MODEL_VERSION, "cost_pct": cost_pct,
        "by_scheme": {code: summarize_validation(folds) for code, folds in outcomes.items()},
        "fold_rows": [fold for folds in outcomes.values() for fold in folds],
        "limitations": "Current surviving category sample; no point-in-time category/universe archive. "
                       "Correlated funds are not independent trials. Validates historical scenarios, not ranking or suitability. "
                       "Illustrative transaction/exit cost; personal taxes and actual scheme exit loads not modelled. "
                       "NAV already includes ongoing expenses. No prospective performance claim.",
    }
