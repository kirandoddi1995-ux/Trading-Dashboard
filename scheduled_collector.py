"""Headless scheduled evidence collector for GitHub Actions.

It deliberately collects read-only market and mutual-fund evidence.  It never
places orders and never prints credentials.  Every run is recorded in the
durable repository, including partial coverage and failures.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import socket
import threading
import time
import urllib.parse
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import mf_research as mfr
from observability import configure_runtime_observability, get_registry
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from amfi_ingestion import (
    canonical_scheme_name,
    current_ranking_records,
    download_amfi_open_nav,
    download_amfi_ter,
    load_amfi_open_nav,
)
from prediction_validation import TARGET_VERSION, TargetDefinition, compute_forward_target
from production_repository import ProductionRepository
from decision_evidence import DecisionEvidenceSpine
from scanner_funnel import stage1_prefilter
from prospective_collection import (
    CORPORATE_ACTIONS,
    LicenseAcknowledgementRequired,
    ProspectiveFeatureWriter,
    collect_company_profiles,
    fetch_full_quotes,
    fetch_global_instruments,
    fetch_institutional_flows,
    require_licence_acknowledgement,
    store_global_cues,
    store_institutional_flows,
    store_order_books,
)


IST = ZoneInfo("Asia/Kolkata")
UPSTOX_API = "https://api.upstox.com"
NSE_INSTRUMENTS = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
NIFTY_KEY = "NSE_INDEX|Nifty 50"
MINIMUM_UNIVERSE = 1000
QUOTE_BATCH_SIZE = 200
SCHEDULED_STAGE1_VERSION = "equity-stage1-scheduled-v1"


def is_nse_scan_window(now=None) -> bool:
    """Conservative normal-session window; holiday closure is caught by quote health."""
    current = now or dt.datetime.now(IST)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("scan clock must be timezone-aware")
    current = current.astimezone(IST)
    return current.weekday() < 5 and dt.time(9, 30) <= current.time() <= dt.time(15, 15)


def session_elapsed_fraction(now=None) -> float | None:
    current = (now or dt.datetime.now(IST)).astimezone(IST)
    market_open = current.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = current.replace(hour=15, minute=30, second=0, microsecond=0)
    if not market_open <= current <= market_close:
        return None
    return max(0.01, min(1.0, (current - market_open).total_seconds() /
                              (market_close - market_open).total_seconds()))


def is_us_close_capture_window(now=None) -> bool:
    """Window after both daylight and standard-time US cash closes, in IST."""
    current = now or dt.datetime.now(IST)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("global-cue clock must be timezone-aware")
    current = current.astimezone(IST)
    return current.weekday() in {1, 2, 3, 4, 5} and dt.time(3, 0) <= current.time() <= dt.time(5, 0)


def _runtime_hashes() -> tuple[str, str, str]:
    root = Path(__file__).resolve().parent
    code = hashlib.sha256()
    for name in ("scheduled_collector.py", "scanner_funnel.py", "decision_evidence.py"):
        code.update(name.encode())
        code.update((root / name).read_bytes())
    config = hashlib.sha256(json.dumps({
        "stage1_top_n": int(os.environ.get("SCHEDULED_STAGE1_TOP_N", "150")),
        "quote_coverage_minimum": 0.90,
        "scan_window_ist": "09:30-15:15",
        "shadow_only": True,
    }, sort_keys=True).encode()).hexdigest()
    policy_path = root / "resilience_policy.json"
    policy = hashlib.sha256(policy_path.read_bytes()).hexdigest() if policy_path.exists() else "unavailable"
    return code.hexdigest(), config, policy


def _best_bid_ask(quote: dict) -> tuple[float | None, float | None]:
    depth = quote.get("market_depth") or quote.get("depth") or {}
    buys = depth.get("buy") or depth.get("bids") or []
    sells = depth.get("sell") or depth.get("asks") or []
    def price(rows):
        if not rows:
            return None
        row = rows[0]
        value = row.get("price") if isinstance(row, dict) else None
        try:
            parsed = float(value)
            return parsed if parsed > 0 else None
        except (TypeError, ValueError):
            return None
    return price(buys), price(sells)


def _quote_snapshot_age(quote: dict, received_at: dt.datetime) -> float | None:
    value = quote.get("timestamp")
    try:
        if isinstance(value, (int, float)) or str(value).strip().isdigit():
            number = float(value)
            if number > 10_000_000_000:
                number /= 1000.0
            generated = dt.datetime.fromtimestamp(number, dt.timezone.utc)
        else:
            generated = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if generated.tzinfo is None or generated.utcoffset() is None:
                return None
            generated = generated.astimezone(dt.timezone.utc)
        return (received_at.astimezone(dt.timezone.utc) - generated).total_seconds()
    except (TypeError, ValueError, OSError):
        return None


def fetch_nse_exchange_status(client, token: str, *, now=None) -> dict:
    response = client.get(
        f"{UPSTOX_API}/v2/market/status/NSE",
        headers=auth_headers(token), timeout=(5, 15),
    )
    if response.status_code in {401, 403}:
        raise PermissionError("Upstox rejected the Analytics Token")
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("status") or data.get("last_updated") is None:
        raise ValueError("Upstox exchange-status schema changed")
    updated = dt.datetime.fromtimestamp(float(data["last_updated"]) / 1000.0, dt.timezone.utc)
    received = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    age = (received - updated).total_seconds()
    if age < -30 or age > 300:
        raise RuntimeError(f"NSE exchange status is stale or future-dated ({age:.0f}s)")
    if str(data["status"]).upper() != "NORMAL_OPEN":
        raise RuntimeError(f"NSE is not in NORMAL_OPEN state ({data['status']})")
    return {
        "exchange": "NSE", "status": "NORMAL_OPEN",
        "last_updated": updated.isoformat(), "age_seconds": age,
    }


def _scheduled_stage1(repo, client, token: str, run_id: str, *, now=None) -> dict:
    current = now or dt.datetime.now(IST)
    if not is_nse_scan_window(current):
        return {"status": "SKIPPED", "reason": "Outside conservative NSE scan window"}
    market_status = fetch_nse_exchange_status(client, token)
    universe = fetch_nse_universe(client)
    universe_result = repo.archive_universe(universe, current.date())
    if not universe_result["complete"]:
        raise RuntimeError("PIT universe snapshot is incomplete")
    keys = [row["instrument_key"] for row in universe]
    quote_map = fetch_full_quotes(client, token, keys)
    received_times = []
    for quote in quote_map.values():
        try:
            received = dt.datetime.fromisoformat(str(quote.get("_received_at")).replace("Z", "+00:00"))
            if received.tzinfo is not None and received.utcoffset() is not None:
                received_times.append(received.astimezone(dt.timezone.utc))
        except (TypeError, ValueError):
            continue
    observed_at = max(received_times or [dt.datetime.now(dt.timezone.utc)])
    quote_count = repo.archive_quotes(
        quote_map.values(), observed_at=observed_at, source="Upstox Full Market Quote V3",
    )
    quote_ages = {key: _quote_snapshot_age(quote, observed_at)
                  for key, quote in quote_map.items()}
    fresh_quotes = {
        key: quote for key, quote in quote_map.items()
        if quote_ages.get(key) is not None and -30 <= quote_ages[key] <= 120
    }
    coverage = len(fresh_quotes) / len(universe) if universe else 0.0
    if len(fresh_quotes) != len(quote_map):
        repo.record_quality_event(
            "scheduled_stage1", "WARNING", "QUOTE_SNAPSHOT_STALE_OR_UNTIMED",
            f"Rejected {len(quote_map) - len(fresh_quotes)} quote snapshots with invalid age",
            {"received": len(quote_map), "fresh": len(fresh_quotes), "maximum_age_seconds": 120},
        )
    if coverage < 0.90:
        repo.record_quality_event(
            "scheduled_stage1", "ERROR", "QUOTE_COVERAGE_LOW",
            f"Scheduled Stage-1 quote coverage was {coverage:.1%}; minimum is 90%",
            {"universe": len(universe), "quotes": len(quote_map)},
        )
        raise RuntimeError(f"Quote coverage {coverage:.1%} is below 90%")

    instrument_dict = {row["trading_symbol"]: row["instrument_key"] for row in universe}
    tickers = list(instrument_dict)
    average_volumes = repo.prior_average_volumes(keys, as_of_date=current.date(), lookback=20)
    top_n = max(1, int(os.environ.get("SCHEDULED_STAGE1_TOP_N", "150")))
    selected, stats = stage1_prefilter(
        tickers, instrument_dict, fresh_quotes, top_n,
        average_volumes=average_volumes,
        elapsed_fraction=session_elapsed_fraction(current),
    )
    evidence = list(stats.pop("_evidence", []))
    records = []
    batch = []
    for item in evidence:
        key = item.get("instrument_key")
        if not key:
            continue
        decision_id = hashlib.sha256(
            f"{run_id}|{key}|{SCHEDULED_STAGE1_VERSION}".encode()
        ).hexdigest()
        quote = dict(fresh_quotes.get(key) or {})
        bid, ask = _best_bid_ask(quote)
        action = "Watch" if item.get("stage1_pass") else "No Trade"
        records.append({
            "observation_id": decision_id,
            "as_of_date": current.date(),
            "observed_at": observed_at,
            "instrument_key": key,
            "trading_symbol": item["trading_symbol"],
            "strategy_version": SCHEDULED_STAGE1_VERSION,
            "universe_snapshot_date": current.date(),
            "stage1_pass": bool(item.get("stage1_pass")),
            "stage2_pass": False,
            "rejection_reason": item.get("rejection_reason") or "Stage-2 was not run by scheduled scanner",
            "score": item.get("score"),
            "features": {**dict(item.get("features") or {}), "scan_run_id": run_id,
                         "shadow_action": action},
        })
        batch.append({
            "decision_id": decision_id,
            "instrument_key": key,
            "instrument": item["trading_symbol"],
            "action": action,
            "stage1_pass": bool(item.get("stage1_pass")),
            "rejection_reason": item.get("rejection_reason"),
            "inputs_used": dict(item.get("features") or {}),
            "quote": {
                "status": "AVAILABLE" if quote else "UNAVAILABLE",
                "source": "Upstox Full Market Quote V3",
                "bid": bid, "ask": ask, "last": quote.get("last_price"),
                "provider_last_trade_time": quote.get("last_trade_time"),
                "provider_snapshot_time": quote.get("timestamp"),
                "quote_age_seconds": quote_ages.get(key),
                "received_at": quote.get("_received_at"),
            },
            "costs": {"status": "NOT_EVALUATED", "reason": "Stage-1 shadow observation only"},
        })
    if len(records) != len(universe):
        raise RuntimeError("Stage-1 evidence did not cover the complete PIT universe")
    stored = repo.upsert_scanner_observations(records)
    code_hash, config_hash, policy_hash = _runtime_hashes()
    DecisionEvidenceSpine(repo.append_evidence_event, repo).capture_candidate_batch(
        scan_run_id=run_id,
        observed_at=observed_at,
        strategy_id=SCHEDULED_STAGE1_VERSION,
        target_version=TARGET_VERSION,
        horizon_sessions=15,
        candidates=batch,
        universe={
            "status": "VERIFIED",
            "snapshot_id": universe_result["snapshot_id"],
            "payload_hash": universe_result["payload_hash"],
            "source": universe_result["source"],
            "observed_at": universe_result["observed_at"],
            "effective_at": dt.datetime.combine(
                current.date(), dt.time.min, tzinfo=IST,
            ).astimezone(dt.timezone.utc).isoformat(),
        },
        code_version="v22.1-PROSPECTIVE-COLLECTION",
        code_hash=code_hash,
        config_hash=config_hash,
        policy_hash=policy_hash,
    )
    shadow = {"status": "DISABLED", "reason": "Licence acknowledgement not configured"}
    try:
        require_licence_acknowledgement()
        shadow = store_order_books(ProspectiveFeatureWriter(repo), fresh_quotes, selected)
        shadow["status"] = "SUCCESS"
    except LicenseAcknowledgementRequired as exc:
        repo.record_quality_event(
            "prospective_features", "WARNING", "LICENSE_ACK_REQUIRED", str(exc),
        )
    return {
        "status": "SUCCESS", "universe": universe_result, "quotes": quote_count,
        "quote_coverage": coverage, "scanner_observations": stored,
        "shortlisted": len(selected), "funnel": stats, "market_status": market_status,
        "order_book_shadow": shadow,
    }


def _post_close_shadow(repo, client, token: str) -> dict:
    try:
        require_licence_acknowledgement()
    except LicenseAcknowledgementRequired as exc:
        repo.record_quality_event(
            "prospective_features", "WARNING", "LICENSE_ACK_REQUIRED", str(exc),
        )
        return {"status": "DISABLED", "reason": str(exc)}
    writer = ProspectiveFeatureWriter(repo)
    flow_rows = fetch_institutional_flows(client, token)
    flows = store_institutional_flows(writer, flow_rows)
    repo.record_quality_event(
        "prospective_institutional_flows", "WARNING",
        "PROVIDER_PUBLICATION_TIME_UNAVAILABLE",
        "Upstox exposes record time but not a separate official release time; first collector receipt is preserved as availability",
        {"records": len(flow_rows), "availability_semantics": "first_observed_by_collector"},
    )
    if not flow_rows:
        repo.record_quality_event(
            "prospective_institutional_flows", "ERROR", "FLOW_DATA_MISSING",
            "No current-date FII/DII records were available after close",
        )
        flows["missing"] = 2
    global_cues = _global_cue_shadow(
        repo, client, token, writer=writer, capture_context="INDIA_CLOSE",
    )
    profiles = collect_company_profiles(
        repo, client, token, limit=max(1, int(os.environ.get("PROFILE_COLLECTION_LIMIT", "25"))),
    )
    failures = (
        flows.get("rejected", 0) + flows.get("missing", 0)
        + global_cues.get("rejected", 0) + global_cues.get("missing_quotes", 0)
        + profiles.get("failed", 0)
    )
    return {
        "status": "PARTIAL" if failures else "SUCCESS",
        "institutional_flows": flows, "global_cues": global_cues,
        "company_profiles": profiles, "failures": failures,
    }


def _global_cue_shadow(repo, client, token: str, *, writer=None,
                       capture_context="US_CLOSE_WINDOW", now=None) -> dict:
    if capture_context == "US_CLOSE_WINDOW" and not is_us_close_capture_window(now):
        return {"status": "SKIPPED", "reason": "Outside the after-US-close capture window"}
    try:
        require_licence_acknowledgement()
    except LicenseAcknowledgementRequired as exc:
        repo.record_quality_event(
            "prospective_features", "WARNING", "LICENSE_ACK_REQUIRED", str(exc),
        )
        return {"status": "DISABLED", "reason": str(exc)}
    writer = writer or ProspectiveFeatureWriter(repo)
    instruments = fetch_global_instruments(client)
    global_quotes = fetch_full_quotes(
        client, token, [row["instrument_key"] for row in instruments],
    )
    result = store_global_cues(
        writer, instruments, global_quotes, capture_context=capture_context,
    )
    result["status"] = "PARTIAL" if (
        result.get("rejected", 0) or result.get("missing_quotes", 0)
    ) else "SUCCESS"
    result["capture_context"] = capture_context
    return result


class CollectorLease:
    """Distributed collector lease with fencing and background renewal."""

    def __init__(self, repo, *, ttl_seconds=180):
        self.repo = repo
        self.ttl_seconds = max(int(ttl_seconds), 30)
        self.owner_id = f"{socket.gethostname()}:{os.getpid()}:{os.urandom(6).hex()}"
        self.lease_name = "scheduled-evidence-collector"
        self.token = None
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = None

    def __enter__(self):
        lease = self.repo.acquire_collector_lease(
            self.lease_name, self.owner_id, ttl_seconds=self.ttl_seconds,
        )
        if not lease:
            raise RuntimeError("Another scheduled evidence collector owns the active lease")
        self.token = int(lease["fencing_token"])
        self._thread = threading.Thread(target=self._renew_loop, daemon=True)
        self._thread.start()
        return self

    def _renew_loop(self):
        while not self._stop.wait(max(self.ttl_seconds / 3, 10)):
            try:
                renewed = self.repo.renew_collector_lease(
                    self.lease_name, self.owner_id, self.token,
                    ttl_seconds=self.ttl_seconds,
                )
            except Exception:
                renewed = False
            if not renewed:
                self._lost.set()
                return

    def assert_valid(self):
        if self._lost.is_set():
            raise RuntimeError("Collector lease was lost; fenced worker stopped")

    def __exit__(self, *_):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self.token is not None:
            try:
                self.repo.release_collector_lease(self.lease_name, self.owner_id, self.token)
            except Exception:
                pass


def session() -> requests.Session:
    retry = Retry(
        total=4, connect=3, read=3, status=4, backoff_factor=0.8,
        status_forcelist=(408, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}), respect_retry_after_header=True,
    )
    client = requests.Session()
    client.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10))
    client.headers.update({"Accept": "application/json", "User-Agent": "QuantTerminalCollector/19.0"})
    return client


def analytics_token() -> str:
    token = str(os.environ.get("UPSTOX_ANALYTICS_TOKEN") or os.environ.get("UPSTOX_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("UPSTOX_ANALYTICS_TOKEN is not configured")
    return token


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def fetch_nse_universe(client: requests.Session) -> list[dict]:
    response = client.get(NSE_INSTRUMENTS, timeout=(5, 30))
    response.raise_for_status()
    payload = response.content
    if len(payload) > 80_000_000:
        raise ValueError("NSE instrument payload exceeded the safety limit")
    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    records = json.loads(payload.decode("utf-8"))
    eligible = []
    for item in records:
        segment = str(item.get("segment") or item.get("exchange") or "").strip().upper()
        instrument_type = str(item.get("instrument_type") or "").strip().upper()
        series = str(item.get("series") or "EQ").strip().upper()
        symbol = str(item.get("trading_symbol") or item.get("tradingsymbol") or "").strip().upper()
        if segment != "NSE_EQ" or instrument_type not in {"EQ", "EQUITY"} or series != "EQ":
            continue
        if not symbol or symbol[0].isdigit() or not item.get("instrument_key"):
            continue
        normalized = dict(item)
        normalized.update(trading_symbol=symbol, exchange="NSE", segment="NSE_EQ")
        eligible.append(normalized)
    if len(eligible) < MINIMUM_UNIVERSE:
        raise ValueError(f"Only {len(eligible)} eligible NSE equities were loaded")
    return eligible


def fetch_quotes(client: requests.Session, token: str, keys: list[str]) -> list[dict]:
    requested = set(keys)
    by_key = {}
    for start in range(0, len(keys), QUOTE_BATCH_SIZE):
        chunk = keys[start:start + QUOTE_BATCH_SIZE]
        response = client.get(
            f"{UPSTOX_API}/v3/market-quote/ohlc",
            params={"instrument_key": ",".join(chunk), "interval": "1d"},
            headers=auth_headers(token), timeout=(5, 20),
        )
        if response.status_code in {401, 403}:
            raise PermissionError("Upstox rejected the Analytics Token")
        response.raise_for_status()
        data = response.json().get("data") or {}
        for response_key, item in data.items():
            if not isinstance(item, dict):
                continue
            record = dict(item)
            instrument_key = str(item.get("instrument_token") or response_key)
            if instrument_key not in requested:
                continue
            record["instrument_key"] = instrument_key
            by_key[instrument_key] = record
        # Deliberately stay below burst limits even if provider limits change.
        if start + QUOTE_BATCH_SIZE < len(keys):
            time.sleep(0.20)
    return [by_key[key] for key in keys if key in by_key]


def fetch_daily_history(client: requests.Session, token: str, instrument_key: str,
                        from_date, to_date=None) -> pd.DataFrame:
    to_date = to_date or dt.datetime.now(IST).date()
    encoded = urllib.parse.quote(str(instrument_key), safe="")
    url = f"{UPSTOX_API}/v3/historical-candle/{encoded}/days/1/{to_date}/{from_date}"
    response = client.get(url, headers=auth_headers(token), timeout=(5, 25))
    if response.status_code in {401, 403}:
        raise PermissionError("Upstox rejected the Analytics Token")
    response.raise_for_status()
    candles = (response.json().get("data") or {}).get("candles") or []
    rows = []
    for candle in candles:
        if len(candle) < 6:
            continue
        rows.append({
            "Date": pd.to_datetime(candle[0], errors="coerce"), "Open": candle[1], "High": candle[2],
            "Low": candle[3], "Close": candle[4], "Volume": candle[5],
            "OI": candle[6] if len(candle) > 6 else 0,
        })
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows).dropna(subset=["Date"]).set_index("Date").sort_index()
    frame.index = frame.index.tz_localize(None) if frame.index.tz is None else frame.index.tz_convert(IST).tz_localize(None)
    return frame[~frame.index.duplicated(keep="last")]


def fetch_historical_minutes(client: requests.Session, token: str, instrument_key: str,
                             from_date, to_date=None) -> pd.DataFrame:
    """Fetch exact one-minute evidence (Upstox V3, available from Jan-2022)."""
    from_date = pd.Timestamp(from_date).date()
    to_date = pd.Timestamp(to_date or dt.datetime.now(IST).date()).date()
    encoded = urllib.parse.quote(str(instrument_key), safe="")
    rows = []
    chunk_start = from_date
    while chunk_start <= to_date:
        chunk_end = min(chunk_start + dt.timedelta(days=29), to_date)
        url = f"{UPSTOX_API}/v3/historical-candle/{encoded}/minutes/1/{chunk_end}/{chunk_start}"
        response = client.get(url, headers=auth_headers(token), timeout=(5, 40))
        if response.status_code in {401, 403}:
            raise PermissionError("Upstox rejected the Analytics Token")
        response.raise_for_status()
        candles = (response.json().get("data") or {}).get("candles") or []
        for candle in candles:
            if len(candle) < 6:
                continue
            rows.append({
                "Date": pd.to_datetime(candle[0], errors="coerce"), "Open": candle[1], "High": candle[2],
                "Low": candle[3], "Close": candle[4], "Volume": candle[5],
            })
        chunk_start = chunk_end + dt.timedelta(days=1)
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows).dropna(subset=["Date"]).set_index("Date").sort_index()
    frame.index = frame.index.tz_localize(IST).tz_localize(None) if frame.index.tz is None else frame.index.tz_convert(IST).tz_localize(None)
    return frame[~frame.index.duplicated(keep="last")]


def update_matured_targets(repo: ProductionRepository, client: requests.Session, token: str,
                           *, limit=40) -> dict:
    pending = repo.pending_observations(target_version=TARGET_VERSION, limit=limit)
    if not pending:
        return {"pending": 0, "stored": 0, "failed": 0, "failures": []}
    earliest = min(pd.Timestamp(row["as_of_date"]).date() for row in pending) - dt.timedelta(days=5)
    benchmark = fetch_daily_history(client, token, NIFTY_KEY, earliest)
    outcome_spine = DecisionEvidenceSpine(repo.append_evidence_event, repo)
    stored, failed, deferred, failures = 0, 0, 0, []
    for observation in pending:
        try:
            start = pd.Timestamp(observation["as_of_date"]).date() - dt.timedelta(days=5)
            history = fetch_daily_history(client, token, observation["instrument_key"], start)
            evidence_end = min(dt.datetime.now(IST).date(), start + dt.timedelta(days=50))
            intraday = fetch_historical_minutes(
                client, token, observation["instrument_key"], start, evidence_end,
            )
            features = observation.get("features") or {}
            cost_bps = float(features.get("execution_cost_bps") or features.get("_execution_cost_bps") or 30.0)
            observed_at = pd.Timestamp(observation["observed_at"])
            if observed_at.tzinfo is not None:
                observed_at = observed_at.tz_convert(IST).tz_localize(None)
            market_open = observed_at.replace(hour=9, minute=15, second=0, microsecond=0)
            market_close = observed_at.replace(hour=15, minute=30, second=0, microsecond=0)
            signal_timestamp = observed_at if market_open <= observed_at <= market_close else None
            for horizon in observation["missing_horizons"]:
                try:
                    completed_sessions = history.loc[
                        history.index.normalize() > pd.Timestamp(observation["as_of_date"]).normalize()
                    ]
                    if len(completed_sessions) < int(horizon):
                        deferred += 1
                        continue
                    target = compute_forward_target(
                        history, observation["as_of_date"],
                        TargetDefinition(int(horizon), round_trip_cost_bps=cost_bps, entry_rule="exact_intraday"),
                        stop=float(observation["stop"]), target=float(observation["target"]), benchmark=benchmark,
                        intraday=intraday, signal_timestamp=signal_timestamp,
                    )
                    if target is None:
                        raise ValueError("Exact target evidence is incomplete or ambiguous")
                    eligible_sessions = completed_sessions.iloc[:int(horizon)]
                    session_closes = []
                    source_ids = []
                    for session_at, session_row in eligible_sessions.iterrows():
                        session_date = pd.Timestamp(session_at).date()
                        session_close = dt.datetime.combine(
                            session_date, dt.time(15, 30), tzinfo=IST,
                        ).astimezone(dt.timezone.utc)
                        session_closes.append(session_close)
                        source_ids.append(hashlib.sha256(json.dumps({
                            "instrument_key": observation["instrument_key"],
                            "session_date": session_date.isoformat(),
                            "ohlcv": {
                                name: (None if pd.isna(session_row.get(name)) else float(session_row.get(name)))
                                for name in ("Open", "High", "Low", "Close", "Volume")
                            },
                        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
                    outcome_date = pd.Timestamp(target["outcome_date"]).date()
                    outcome_at = dt.datetime.combine(
                        outcome_date, dt.time(15, 30), tzinfo=IST,
                    ).astimezone(dt.timezone.utc)
                    outcome_spine.outcome(
                        decision_id=observation["observation_id"],
                        outcome=str(target["outcome"]).upper(),
                        outcome_at=outcome_at,
                        actual_forward_return=target["net_return"],
                        completed_session_closes=session_closes,
                        source_observation_ids=source_ids,
                        actual_costs={
                            "round_trip_bps": target["cost_bps"],
                            "entry_quality": target.get("entry_quality"),
                            "gross_return": target["gross_return"],
                            "net_return": target["net_return"],
                        },
                    )
                    repo.save_prediction_target(observation["observation_id"], target)
                    stored += 1
                except Exception as exc:
                    failed += 1
                    detail = {
                        "observation_id": observation["observation_id"], "horizon": int(horizon),
                        "error_kind": type(exc).__name__, "message": str(exc)[:300],
                    }
                    failures.append(detail)
                    repo.record_quality_event(
                        "prediction_targets", "ERROR", "TARGET_GENERATION_FAILED",
                        f"Target generation failed for observation {observation['observation_id']}", detail,
                    )
        except Exception as exc:
            missing_count = max(len(observation.get("missing_horizons") or []), 1)
            failed += missing_count
            detail = {
                "observation_id": observation.get("observation_id"),
                "error_kind": type(exc).__name__, "message": str(exc)[:300],
            }
            failures.append(detail)
            repo.record_quality_event(
                "prediction_targets", "ERROR", "TARGET_INPUT_FETCH_FAILED",
                f"Target inputs failed for observation {observation.get('observation_id')}", detail,
            )
    return {"pending": len(pending), "stored": stored, "failed": failed, "deferred": deferred,
            "failures": failures[:50]}


def update_corporate_actions(repo: ProductionRepository, client: requests.Session, token: str,
                             *, limit=100, shadow_writer=None) -> dict:
    candidates = repo.enrichment_candidates(
        "corporate_actions", limit=limit, refresh_days=30,
    )
    archived, shadow_stored, failed = 0, 0, 0
    for candidate in candidates:
        isin = candidate["isin"]
        try:
            response = client.get(
                f"{UPSTOX_API}/v2/fundamentals/{urllib.parse.quote(isin, safe='')}/corporate-actions",
                headers=auth_headers(token), timeout=(5, 20),
            )
            if response.status_code in {401, 403}:
                raise PermissionError("Upstox rejected the Analytics Token")
            response.raise_for_status()
            actions = response.json().get("data") or []
            if not isinstance(actions, list):
                raise ValueError("Upstox corporate-actions schema changed")
            archived += repo.archive_corporate_actions(isin, actions)
            if shadow_writer is not None:
                received = dt.datetime.now(dt.timezone.utc)
                shadow = shadow_writer.record(
                    instrument_key=candidate["instrument_key"],
                    definition=CORPORATE_ACTIONS,
                    value={"isin": isin, "actions": actions},
                    effective_at=received, available_at=received, observed_at=received,
                )
                if not shadow["stored"]:
                    raise ValueError("corporate action payload failed feature quality")
                shadow_stored += 1
            repo.mark_enrichment_checked(isin, "corporate_actions", "ok")
        except PermissionError:
            raise
        except Exception as exc:
            failed += 1
            repo.mark_enrichment_checked(isin, "corporate_actions", type(exc).__name__)
        time.sleep(0.15)
    return {"checked": len(candidates), "archived": archived,
            "shadow_stored": shadow_stored, "failed": failed}


def archive_mutual_funds(repo: ProductionRepository, client: requests.Session,
                         *, nav_file: str | None = None, include_disclosures=False) -> dict:
    result = load_amfi_open_nav(nav_file) if nav_file else download_amfi_open_nav(session=client)
    nav_count = repo.archive_mf_nav(result.records, source="AMFI NAVOpen.txt", source_hash=result.source_hash)
    summary = {**result.summary(), "nav_archived": nav_count, "disclosures_archived": 0}
    if not include_disclosures:
        return summary

    current = current_ranking_records(result)
    codes_by_name = {}
    for record in current:
        codes_by_name.setdefault(canonical_scheme_name(record["scheme_name"]), []).append(record)
    disclosures = []
    try:
        for ter in download_amfi_ter(session=client):
            matches = codes_by_name.get(ter["canonical_name"], [])
            if len(matches) != 1:
                continue
            disclosures.append({
                "scheme_code": matches[0]["scheme_code"], "scheme_name": matches[0]["scheme_name"],
                "category": matches[0]["category"], "effective_date": ter["effective_date"],
                "ter": ter["ter"], "regular_ter": ter["regular_ter"], "status": "active",
            })
    except Exception as exc:
        repo.record_quality_event(
            "mutual_funds", "WARNING", "TER_UNAVAILABLE",
            f"Official AMFI TER retrieval failed: {type(exc).__name__}",
        )
    if disclosures:
        summary["disclosures_archived"] += repo.archive_mf_disclosures(
            disclosures, source="AMFI official TER workbook",
        )
    category_aliases = {
        "Large Cap": ("large cap",), "Large & Mid Cap": ("large mid cap",),
        "Flexi Cap": ("flexi cap",), "Multi Cap": ("multi cap",),
        "Mid Cap": ("mid cap",), "Small Cap": ("small cap",), "ELSS (Tax Saver)": ("elss",),
        "Liquid": ("liquid",), "Overnight": ("overnight",), "Money Market": ("money market",),
        "Short Duration Debt": ("short duration",), "Low Duration Debt": ("low duration",),
        "Ultra Short Duration Debt": ("ultra short duration",), "Corporate Bond": ("corporate bond",),
        "Banking & PSU Debt": ("banking psu",), "Gilt": ("gilt",),
        "Balanced Advantage": ("balanced advantage", "dynamic asset allocation"),
        "Aggressive Hybrid": ("aggressive hybrid",),
    }
    for category_name, aliases in category_aliases.items():
        candidates = []
        for record in current:
            normalized_category = canonical_scheme_name(record.get("category"))
            if category_name == "Mid Cap" and "large mid cap" in normalized_category:
                continue
            if category_name == "Short Duration Debt" and (
                "ultra short duration" in normalized_category or "low duration" in normalized_category
            ):
                continue
            if not any(alias in normalized_category for alias in aliases):
                continue
            candidates.append({
                "schemeCode": record["scheme_code"], "schemeName": record["scheme_name"],
                "fundHouse": record.get("amc"),
            })
        if not candidates:
            continue
        try:
            official = mfr.fetch_official_disclosures(candidates, category_name, budget_seconds=15)
            rows = []
            for scheme_code, disclosure in (official.get("records") or {}).items():
                effective = (
                    disclosure.get("performance_as_of") or disclosure.get("risk_as_of")
                    or disclosure.get("document_date")
                )
                if not effective:
                    continue
                rows.append({
                    **disclosure, "scheme_code": scheme_code, "category": category_name,
                    "effective_date": effective,
                })
            if rows:
                summary["disclosures_archived"] += repo.archive_mf_disclosures(
                    rows, source="AMFI official performance and scheme summaries",
                )
            for message in official.get("errors") or []:
                repo.record_quality_event(
                    "mutual_funds", "WARNING", "AMFI_DISCLOSURE_PARTIAL", str(message),
                    {"category": category_name},
                )
        except Exception as exc:
            repo.record_quality_event(
                "mutual_funds", "WARNING", "AMFI_DISCLOSURE_UNAVAILABLE",
                f"Official disclosure retrieval failed: {type(exc).__name__}",
                {"category": category_name},
            )
    return summary


def resolve_mode(requested: str, now=None) -> str:
    if requested != "auto":
        return requested
    now = now or dt.datetime.now(IST)
    if now.weekday() == 5:
        return "weekly"
    return "open" if now.hour < 12 else "close"


def run(mode: str, *, nav_file=None) -> dict:
    mode = resolve_mode(mode)
    token = analytics_token()
    repo = ProductionRepository(
        os.environ.get("DATABASE_URL"), schema_mode="validate", enforce_restricted_role=True,
    )
    client = session()
    lease_ttl = int(os.environ.get("COLLECTOR_LEASE_TTL_SECONDS", "180"))
    with CollectorLease(repo, ttl_seconds=lease_ttl) as lease:
        run_id = repo.start_run(
            mode, scheduled_for=dt.datetime.now(IST),
            metadata={"headless": True, "fencing_token": lease.token},
        )
        result = {"mode": mode, "fencing_token": lease.token}
        record_count = 0
        try:
            if mode == "scan":
                lease.assert_valid()
                scan_result = _scheduled_stage1(repo, client, token, run_id)
                result["scheduled_stage1"] = scan_result
                record_count += int(scan_result.get("scanner_observations", 0))
            if mode == "global":
                lease.assert_valid()
                global_result = _global_cue_shadow(
                    repo, client, token, capture_context="US_CLOSE_WINDOW",
                )
                result["global_cue_shadow"] = global_result
                record_count += int(global_result.get("stored", 0))
            if mode in {"open", "close", "all"}:
                lease.assert_valid()
                universe = fetch_nse_universe(client)
                universe_result = repo.archive_universe(universe, dt.datetime.now(IST).date())
                quotes = fetch_quotes(client, token, [row["instrument_key"] for row in universe])
                lease.assert_valid()
                quote_count = repo.archive_quotes(quotes, observed_at=dt.datetime.now(dt.timezone.utc))
                coverage = quote_count / len(universe) if universe else 0.0
                result.update(universe=universe_result, quotes=quote_count, quote_coverage=coverage)
                record_count += universe_result["count"] + quote_count
                if coverage < 0.90:
                    repo.record_quality_event(
                        "market_quotes", "ERROR", "QUOTE_COVERAGE_LOW",
                        f"Scheduled quote coverage was {coverage:.1%}; minimum is 90%",
                        {"universe": len(universe), "quotes": quote_count},
                    )
                    raise RuntimeError(f"Quote coverage {coverage:.1%} is below 90%")
            if mode in {"close", "all"}:
                lease.assert_valid()
                target_result = update_matured_targets(repo, client, token)
                result["targets"] = target_result
                record_count += target_result["stored"]
                mf_result = archive_mutual_funds(repo, client, nav_file=nav_file)
                result["mutual_funds"] = mf_result
                record_count += mf_result["nav_archived"]
                shadow_result = _post_close_shadow(repo, client, token)
                result["prospective_shadow"] = shadow_result
                record_count += (
                    int(shadow_result.get("institutional_flows", {}).get("stored", 0))
                    + int(shadow_result.get("global_cues", {}).get("stored", 0))
                    + int(shadow_result.get("company_profiles", {}).get("stored", 0))
                )
            if mode in {"weekly", "all"}:
                lease.assert_valid()
                if mode == "weekly":
                    universe = fetch_nse_universe(client)
                    universe_result = repo.archive_universe(universe, dt.datetime.now(IST).date())
                    result["universe"] = universe_result
                    record_count += universe_result["count"]
                shadow_writer = None
                try:
                    require_licence_acknowledgement()
                    shadow_writer = ProspectiveFeatureWriter(repo)
                except LicenseAcknowledgementRequired as exc:
                    repo.record_quality_event(
                        "prospective_features", "WARNING", "LICENSE_ACK_REQUIRED", str(exc),
                    )
                corporate_actions = update_corporate_actions(
                    repo, client, token, shadow_writer=shadow_writer,
                )
                result["corporate_actions"] = corporate_actions
                record_count += corporate_actions["archived"]
                mf_result = archive_mutual_funds(repo, client, nav_file=nav_file, include_disclosures=True)
                result["mutual_funds"] = mf_result
                record_count += mf_result["nav_archived"] + mf_result["disclosures_archived"]
            lease.assert_valid()
            run_status = "PARTIAL" if (
                result.get("targets", {}).get("failed", 0)
                or result.get("prospective_shadow", {}).get("status") == "PARTIAL"
                or result.get("global_cue_shadow", {}).get("status") == "PARTIAL"
                or result.get("corporate_actions", {}).get("failed", 0)
            ) else "SUCCESS"
            result["status"] = run_status
            repo.finish_run(run_id, status=run_status, record_count=record_count, metadata=result)
            get_registry().record(
                "collector", mode, 0.0, ok=run_status == "SUCCESS",
                status=run_status, count=max(record_count, 1),
            )
            return result
        except Exception as exc:
            get_registry().record(
                "collector", mode, 0.0, ok=False, status=type(exc).__name__,
            )
            repo.finish_run(
                run_id, status="FAILED", record_count=record_count,
                error_kind=type(exc).__name__, error_message=str(exc), metadata=result,
            )
            raise


def main(argv=None) -> int:
    configure_runtime_observability()
    parser = argparse.ArgumentParser(description="Collect durable market research evidence")
    parser.add_argument(
        "--mode", choices=("auto", "scan", "global", "open", "close", "weekly", "all"),
        default="auto",
    )
    parser.add_argument("--nav-file", help="Optional local AMFI NAV file for a controlled import")
    parser.add_argument("--check", action="store_true", help="Validate configuration and schema only")
    parser.add_argument("--migrate", action="store_true", help="Apply schema migrations with the owner-only URL")
    args = parser.parse_args(argv)
    if args.migrate:
        migration_url = str(os.environ.get("DATABASE_MIGRATION_URL") or "").strip()
        if not migration_url:
            print(json.dumps({"configured": False, "status": "DATABASE_MIGRATION_URL is not configured"}))
            return 1
        health = ProductionRepository(migration_url, schema_mode="migrate").health()
        print(json.dumps(health, default=str))
        return 0 if health.get("connected") else 1
    if args.check:
        health = ProductionRepository(
            os.environ.get("DATABASE_URL"), schema_mode="validate", enforce_restricted_role=True,
        ).health()
        print(json.dumps(health, default=str))
        return 0 if health.get("connected") else 1
    result = run(args.mode, nav_file=args.nav_file)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "SUCCESS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
