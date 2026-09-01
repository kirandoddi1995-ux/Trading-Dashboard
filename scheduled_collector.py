"""Headless scheduled evidence collector for GitHub Actions.

It deliberately collects read-only market and mutual-fund evidence.  It never
places orders and never prints credentials.  Every run is recorded in the
durable repository, including partial coverage and failures.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import mf_research as mfr
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


IST = ZoneInfo("Asia/Kolkata")
UPSTOX_API = "https://api.upstox.com"
NSE_INSTRUMENTS = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
NIFTY_KEY = "NSE_INDEX|Nifty 50"
MINIMUM_UNIVERSE = 1000
QUOTE_BATCH_SIZE = 200


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
        return {"pending": 0, "stored": 0, "failed": 0}
    earliest = min(pd.Timestamp(row["as_of_date"]).date() for row in pending) - dt.timedelta(days=5)
    benchmark = fetch_daily_history(client, token, NIFTY_KEY, earliest)
    stored, failed = 0, 0
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
                target = compute_forward_target(
                    history, observation["as_of_date"],
                    TargetDefinition(int(horizon), round_trip_cost_bps=cost_bps, entry_rule="exact_intraday"),
                    stop=float(observation["stop"]), target=float(observation["target"]), benchmark=benchmark,
                    intraday=intraday, signal_timestamp=signal_timestamp,
                )
                if target is not None:
                    repo.save_prediction_target(observation["observation_id"], target)
                    stored += 1
        except Exception:
            failed += 1
    return {"pending": len(pending), "stored": stored, "failed": failed}


def update_corporate_actions(repo: ProductionRepository, client: requests.Session, token: str,
                             *, limit=100) -> dict:
    candidates = repo.corporate_action_candidates(limit=limit, refresh_days=30)
    archived, failed = 0, 0
    for isin in candidates:
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
            repo.mark_enrichment_checked(isin, "corporate_actions", "ok")
        except PermissionError:
            raise
        except Exception as exc:
            failed += 1
            repo.mark_enrichment_checked(isin, "corporate_actions", type(exc).__name__)
        time.sleep(0.15)
    return {"checked": len(candidates), "archived": archived, "failed": failed}


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
    repo = ProductionRepository(os.environ.get("DATABASE_URL"))
    client = session()
    run_id = repo.start_run(mode, scheduled_for=dt.datetime.now(IST), metadata={"headless": True})
    result = {"mode": mode}
    record_count = 0
    try:
        if mode in {"open", "close", "all"}:
            universe = fetch_nse_universe(client)
            universe_result = repo.archive_universe(universe, dt.datetime.now(IST).date())
            quotes = fetch_quotes(client, token, [row["instrument_key"] for row in universe])
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
            target_result = update_matured_targets(repo, client, token)
            result["targets"] = target_result
            record_count += target_result["stored"]
            mf_result = archive_mutual_funds(repo, client, nav_file=nav_file)
            result["mutual_funds"] = mf_result
            record_count += mf_result["nav_archived"]
        if mode in {"weekly", "all"}:
            if mode == "weekly":
                universe = fetch_nse_universe(client)
                universe_result = repo.archive_universe(universe, dt.datetime.now(IST).date())
                result["universe"] = universe_result
                record_count += universe_result["count"]
            corporate_actions = update_corporate_actions(repo, client, token)
            result["corporate_actions"] = corporate_actions
            record_count += corporate_actions["archived"]
            mf_result = archive_mutual_funds(repo, client, nav_file=nav_file, include_disclosures=True)
            result["mutual_funds"] = mf_result
            record_count += mf_result["nav_archived"] + mf_result["disclosures_archived"]
        repo.finish_run(run_id, status="SUCCESS", record_count=record_count, metadata=result)
        return result
    except Exception as exc:
        repo.finish_run(
            run_id, status="FAILED", record_count=record_count,
            error_kind=type(exc).__name__, error_message=str(exc), metadata=result,
        )
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect durable market research evidence")
    parser.add_argument("--mode", choices=("auto", "open", "close", "weekly", "all"), default="auto")
    parser.add_argument("--nav-file", help="Optional local AMFI NAV file for a controlled import")
    parser.add_argument("--check", action="store_true", help="Validate configuration and schema only")
    args = parser.parse_args(argv)
    if args.check:
        health = ProductionRepository(os.environ.get("DATABASE_URL")).health()
        print(json.dumps(health, default=str))
        return 0 if health.get("connected") else 1
    result = run(args.mode, nav_file=args.nav_file)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
