"""Prospective-only shadow feature collection.

Nothing in this module is imported by live scoring or governance.  It records
new observations only after their real receipt time, preserves provider event
times separately, and refuses collection until the operator confirms that the
configured data plan and terms permit durable research storage.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import re
import time
import urllib.parse
from collections.abc import Iterable, Mapping

from decision_evidence import FeatureDefinition, FeatureQualityMonitor, FeatureRegistry
from observability import get_registry
from research_features import order_book_features, publish_research_features


UTC = dt.timezone.utc
UPSTOX_API = "https://api.upstox.com"
GLOBAL_INSTRUMENTS = (
    "https://assets.upstox.com/market-quote/instruments/exchange/global.json.gz"
)
FULL_QUOTE_BATCH_SIZE = 400  # Official endpoint maximum is 500.
GLOBAL_NAMES = {
    "GIFT NIFTY", "DOW JONES", "S&P", "S&P 500", "US 30",
    "OIL (BRENT)", "USD INR", "USDINR",
}


class LicenseAcknowledgementRequired(RuntimeError):
    """Raised before any provider request when archival rights are unconfirmed."""


def licence_acknowledged(env: Mapping[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    return str(values.get("PROSPECTIVE_DATA_LICENSE_ACK") or "").strip().casefold() in {
        "1", "true", "yes",
    }


def require_licence_acknowledgement(env: Mapping[str, str] | None = None) -> None:
    if not licence_acknowledged(env):
        raise LicenseAcknowledgementRequired(
            "Prospective provider archival is disabled until "
            "PROSPECTIVE_DATA_LICENSE_ACK=true is set after reviewing provider terms"
        )


def _aware(value, *, milliseconds=False) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        number = float(value)
        if milliseconds or number > 10_000_000_000:
            number /= 1000.0
        parsed = dt.datetime.fromtimestamp(number, UTC)
    else:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("provider timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def _latency_seconds(text) -> int:
    match = re.search(r"(\d+)", str(text or ""))
    return int(match.group(1)) if match else 900


def _request_json(client, url, *, token=None, params=None, timeout=(5, 25)):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.get(url, params=params, headers=headers, timeout=timeout)
    if response.status_code in {401, 403}:
        raise PermissionError("Upstox rejected the Analytics Token")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping) or payload.get("status") not in {None, "success"}:
        raise ValueError("Provider returned an unsuccessful or changed JSON schema")
    return payload


def fetch_full_quotes(client, token: str, instrument_keys: Iterable[str]) -> dict[str, dict]:
    """Fetch D5/full quote snapshots without interpreting them as model inputs."""
    keys = list(dict.fromkeys(str(key) for key in instrument_keys if key))
    result: dict[str, dict] = {}
    for start in range(0, len(keys), FULL_QUOTE_BATCH_SIZE):
        chunk = keys[start:start + FULL_QUOTE_BATCH_SIZE]
        payload = _request_json(
            client,
            f"{UPSTOX_API}/v3/market-quote/quotes",
            token=token,
            params={"instrument_key": ",".join(chunk)},
        )
        requested = set(chunk)
        for response_key, raw in (payload.get("data") or {}).items():
            if not isinstance(raw, Mapping):
                continue
            item = dict(raw)
            key = str(item.get("instrument_token") or item.get("instrument_key") or response_key)
            if key not in requested:
                continue
            item["instrument_key"] = key
            if item.get("prev_close_price") is not None and not item.get("prev_ohlc"):
                item["prev_ohlc"] = {"close": item.get("prev_close_price")}
            item["_received_at"] = dt.datetime.now(UTC).isoformat()
            result[key] = item
        if start + FULL_QUOTE_BATCH_SIZE < len(keys):
            time.sleep(0.20)
    return result


def fetch_global_instruments(client) -> list[dict]:
    response = client.get(GLOBAL_INSTRUMENTS, timeout=(5, 30))
    response.raise_for_status()
    raw = response.content
    if len(raw) > 20_000_000:
        raise ValueError("Global instrument payload exceeded the safety limit")
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    rows = json.loads(raw.decode("utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Global instrument schema changed")
    wanted = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or "").strip().upper()
        if name in GLOBAL_NAMES and row.get("instrument_key"):
            wanted.append(dict(row))
    return wanted


def fetch_institutional_flows(client, token: str) -> list[dict]:
    received_at = dt.datetime.now(UTC)
    current_date = received_at.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).date()
    rows: list[dict] = []
    for participant, path in (("FII", "fii"), ("DII", "dii")):
        payload = _request_json(
            client,
            f"{UPSTOX_API}/v2/market/{path}",
            token=token,
            params={
                "data_type": "NSE_EQ|CASH", "interval": "1D",
                "from": current_date.isoformat(),
            },
        )
        series = (payload.get("data") or {}).get("NSE_EQ|CASH") or []
        if not isinstance(series, list):
            raise ValueError(f"{participant} activity schema changed")
        for item in series:
            if not isinstance(item, Mapping) or item.get("time_stamp") is None:
                continue
            rows.append({
                "participant": participant,
                "segment": "NSE_EQ|CASH",
                "provider_effective_at": _aware(item["time_stamp"], milliseconds=True),
                # The API does not publish a separate release timestamp.  In a
                # prospective collector, receipt is the only defensible first-known time.
                "available_at": received_at,
                "value": dict(item),
            })
    return rows


class ProspectiveFeatureWriter:
    """Register, quality-check, then append one shadow feature observation."""

    def __init__(self, repository):
        self.repository = repository
        self.registry = FeatureRegistry(repository.append_evidence_event, repository)
        self.quality = FeatureQualityMonitor(
            self.registry, repository.append_evidence_event, metrics=get_registry(),
        )

    def record(self, *, instrument_key: str, definition: FeatureDefinition, value,
               effective_at, available_at, observed_at=None) -> dict:
        observed = _aware(observed_at or available_at)
        effective = _aware(effective_at)
        available = _aware(available_at)
        self.registry.register(definition, registered_at=observed)
        lineage = {
            definition.name: {
                "value": value,
                "effective_at": effective.isoformat(),
                "available_at": available.isoformat(),
                "definition_version": definition.version,
                "maximum_age_seconds": definition.maximum_age_seconds,
                "source": definition.source,
            }
        }
        quality = self.quality.observe(
            source_id=f"prospective:{definition.name}:{instrument_key}",
            feature_lineage=lineage,
            decision_at=observed,
            required_features=(definition.name,),
        )
        if quality["status"] != "PASS":
            self.repository.record_quality_event(
                "prospective_features", "ERROR", "FEATURE_QUALITY_FAILED",
                f"Rejected {definition.name} observation before persistence",
                {"instrument_key": instrument_key, "failures": quality["failures"]},
            )
            return {"stored": False, "quality": quality}
        feature_id = self.repository.record_feature_observation(
            instrument_key=instrument_key,
            feature_name=f"{definition.name}@{definition.version}",
            value=value,
            effective_at=effective,
            available_at=available,
            source=definition.source,
        )
        return {"stored": True, "feature_id": feature_id, "quality": quality}


ORDER_BOOK_D5 = FeatureDefinition(
    name="order_book_depth_d5",
    version="upstox-full-quote-v3-d5-v1",
    dtype="object",
    source="Upstox Full Market Quote V3",
    computation_logic="Unmodified five-level bid/ask depth and quote metadata at REST receipt",
    availability_rule="effective_at and available_at equal collector receipt time; provider last-trade time is retained inside value",
    maximum_age_seconds=30,
)
INSTITUTIONAL_FLOW = FeatureDefinition(
    name="institutional_cash_flow",
    version="upstox-market-information-v1",
    dtype="object",
    source="Upstox FII/DII Activity API",
    computation_logic="Unmodified NSE_EQ|CASH daily participant record",
    availability_rule="effective_at is provider time_stamp; available_at is first successful prospective API receipt",
    maximum_age_seconds=40 * 24 * 3600,
)
GLOBAL_CUE = FeatureDefinition(
    name="global_market_cue",
    version="upstox-global-instruments-v1",
    dtype="object",
    source="Upstox Global Instruments + Full Market Quote V3",
    computation_logic="Unmodified quote plus declared provider latency and instrument metadata",
    availability_rule="effective_at and available_at equal collector receipt time; declared latency is retained and never hidden",
    maximum_age_seconds=1200,
)
COMPANY_PROFILE = FeatureDefinition(
    name="company_profile",
    version="upstox-fundamentals-profile-v1",
    dtype="object",
    source="Upstox Company Profile API",
    computation_logic="Unmodified company profile payload keyed by PIT-universe ISIN",
    availability_rule="effective_at and available_at equal first successful prospective API receipt",
    maximum_age_seconds=45 * 24 * 3600,
)
CORPORATE_ACTIONS = FeatureDefinition(
    name="corporate_actions",
    version="upstox-fundamentals-actions-v1",
    dtype="object",
    source="Upstox Corporate Actions API",
    computation_logic="Unmodified action list keyed by PIT-universe ISIN",
    availability_rule="event dates remain payload facts; feature availability is first successful prospective API receipt",
    maximum_age_seconds=45 * 24 * 3600,
)


def store_order_books(writer: ProspectiveFeatureWriter, quotes: Mapping[str, Mapping],
                      keys: Iterable[str]) -> dict:
    stored = rejected = missing = derived_stored = derived_rejected = 0
    for key in keys:
        quote = dict(quotes.get(key) or {})
        depth = quote.get("market_depth") or quote.get("depth")
        if not isinstance(depth, Mapping):
            missing += 1
            continue
        buys = depth.get("buy") or depth.get("bids")
        sells = depth.get("sell") or depth.get("asks")
        try:
            bid = float((buys or [])[0]["price"])
            ask = float((sells or [])[0]["price"])
            quantities = [float(level.get("quantity", 0)) for level in list(buys) + list(sells)]
            valid_book = bid > 0 and ask > 0 and bid <= ask and all(qty >= 0 for qty in quantities)
        except (TypeError, ValueError, IndexError, KeyError):
            valid_book = False
        if not valid_book:
            rejected += 1
            writer.repository.record_quality_event(
                "prospective_order_book", "ERROR", "DEPTH_SCHEMA_OR_RANGE_INVALID",
                "Rejected a malformed, crossed, or negative-quantity D5 snapshot",
                {"instrument_key": key},
            )
            continue
        received = _aware(quote.get("_received_at") or dt.datetime.now(UTC))
        try:
            effective = _aware(quote["timestamp"])
        except (KeyError, TypeError, ValueError):
            rejected += 1
            writer.repository.record_quality_event(
                "prospective_order_book", "ERROR", "SNAPSHOT_TIMESTAMP_INVALID",
                "Rejected D5 snapshot without a timezone-aware provider generation time",
                {"instrument_key": key},
            )
            continue
        value = {
            "depth": dict(depth),
            "last_price": quote.get("last_price"),
            "last_trade_time": quote.get("last_trade_time"),
            "snapshot_semantics": "collector_receipt_time",
        }
        result = writer.record(
            instrument_key=key, definition=ORDER_BOOK_D5, value=value,
            effective_at=effective, available_at=received, observed_at=received,
        )
        stored += int(result["stored"])
        rejected += int(not result["stored"])
        if result["stored"]:
            try:
                derived = order_book_features(list(buys), list(sells))
                published = publish_research_features(
                    writer, instrument_key=key,
                    values={name: derived[name] for name in (
                        "order_book_imbalance_d5", "microprice_d5",
                    )},
                    effective_at=effective, available_at=received,
                )
                derived_stored += int(published["stored"])
                derived_rejected += int(published["rejected"])
            except Exception as exc:
                derived_rejected += 2
                writer.repository.record_quality_event(
                    "prospective_order_book", "ERROR", "DEPTH_DERIVATION_FAILED",
                    "Raw D5 snapshot stored but research-only derivation failed",
                    {"instrument_key": key, "error_kind": type(exc).__name__},
                )
    if missing:
        writer.repository.record_quality_event(
            "prospective_order_book", "WARNING", "DEPTH_MISSING",
            f"{missing} shortlisted quote snapshots had no D5 depth",
            {"missing": missing},
        )
    return {
        "stored": stored, "rejected": rejected, "missing_depth": missing,
        "derived_stored": derived_stored, "derived_rejected": derived_rejected,
        "consumed_by_scoring": False,
    }


def store_institutional_flows(writer: ProspectiveFeatureWriter, rows: Iterable[Mapping]) -> dict:
    stored = rejected = 0
    for row in rows:
        result = writer.record(
            instrument_key=f"NSE_EQ|CASH:{row['participant']}",
            definition=INSTITUTIONAL_FLOW,
            value={
                "participant": row["participant"],
                "segment": row["segment"],
                "record": dict(row["value"]),
                "publication_time_semantics": "first_observed_by_collector",
            },
            effective_at=row["provider_effective_at"],
            available_at=row["available_at"],
            observed_at=row["available_at"],
        )
        stored += int(result["stored"])
        rejected += int(not result["stored"])
    return {"stored": stored, "rejected": rejected}


def store_global_cues(writer: ProspectiveFeatureWriter, instruments: Iterable[Mapping],
                      quotes: Mapping[str, Mapping], *, capture_context="INDIA_CLOSE") -> dict:
    stored = rejected = missing = 0
    for instrument in instruments:
        key = str(instrument.get("instrument_key") or "")
        quote = dict(quotes.get(key) or {})
        if not quote:
            missing += 1
            continue
        received = _aware(quote.get("_received_at") or dt.datetime.now(UTC))
        try:
            effective = _aware(quote["timestamp"])
        except (KeyError, TypeError, ValueError):
            rejected += 1
            writer.repository.record_quality_event(
                "prospective_global_cues", "ERROR", "SNAPSHOT_TIMESTAMP_INVALID",
                "Rejected global cue without a timezone-aware provider generation time",
                {"instrument_key": key},
            )
            continue
        result = writer.record(
            instrument_key=key,
            definition=GLOBAL_CUE,
            value={
                "instrument": dict(instrument),
                "quote": {k: v for k, v in quote.items() if k != "_received_at"},
                "declared_latency_seconds": _latency_seconds(instrument.get("latency")),
                "snapshot_semantics": "collector_receipt_time",
                "capture_context": str(capture_context),
            },
            effective_at=effective,
            available_at=received,
            observed_at=received,
        )
        stored += int(result["stored"])
        rejected += int(not result["stored"])
    if missing:
        writer.repository.record_quality_event(
            "prospective_global_cues", "WARNING", "GLOBAL_QUOTE_MISSING",
            f"{missing} configured global cues had no quote snapshot",
            {"missing": missing},
        )
    return {"stored": stored, "rejected": rejected, "missing_quotes": missing}


def collect_company_profiles(repository, client, token: str, *, limit=25) -> dict:
    writer = ProspectiveFeatureWriter(repository)
    candidates = repository.enrichment_candidates(
        "company_profile", limit=limit, refresh_days=30,
    )
    stored = failed = 0
    for candidate in candidates:
        isin = candidate["isin"]
        try:
            payload = _request_json(
                client,
                f"{UPSTOX_API}/v2/fundamentals/{urllib.parse.quote(isin, safe='')}/profile",
                token=token,
            )
            received = dt.datetime.now(UTC)
            result = writer.record(
                instrument_key=candidate["instrument_key"],
                definition=COMPANY_PROFILE,
                value={"isin": isin, "profile": dict(payload.get("data") or {})},
                effective_at=received, available_at=received, observed_at=received,
            )
            if not result["stored"]:
                raise ValueError("company profile failed feature quality")
            repository.mark_enrichment_checked(isin, "company_profile", "ok")
            stored += 1
        except PermissionError:
            raise
        except Exception as exc:
            repository.mark_enrichment_checked(isin, "company_profile", type(exc).__name__)
            failed += 1
        time.sleep(0.15)
    if failed:
        repository.record_quality_event(
            "prospective_company_profile", "WARNING", "PROFILE_COLLECTION_PARTIAL",
            f"{failed} company profile observations failed",
            {"checked": len(candidates), "stored": stored, "failed": failed},
        )
    return {"checked": len(candidates), "stored": stored, "failed": failed}
