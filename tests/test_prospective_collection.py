import ast
import datetime as dt
import gzip
import json
from pathlib import Path

import pytest
import pandas as pd
import requests

import scheduled_collector as collector
from prospective_collection import (
    COMPANY_PROFILE,
    CueInstrumentSelection,
    LicenseAcknowledgementRequired,
    ProspectiveFeatureWriter,
    fetch_global_instruments,
    fetch_global_quotes,
    fetch_institutional_flows,
    require_licence_acknowledgement,
    store_global_cues,
    store_order_books,
)
from scanner_funnel import stage1_prefilter


UTC = dt.timezone.utc
ROOT = Path(__file__).resolve().parents[1]


class MemoryRepository:
    def __init__(self):
        self.ledger = []
        self.features = []
        self.quality_events = []
        self.scanner = []

    def append_evidence_event(self, **event):
        prior = next((row for row in self.ledger
                      if row["idempotency_key"] == event["idempotency_key"]), None)
        if prior:
            return {"duplicate": True, "event_id": prior["event_id"]}
        stored = {**event, "event_id": str(len(self.ledger) + 1), "duplicate": False}
        self.ledger.append(stored)
        return stored

    def events(self, aggregate_id):
        return [row for row in self.ledger if row["aggregate_id"] == aggregate_id]

    def record_feature_observation(self, **row):
        self.features.append(row)
        return f"feature-{len(self.features)}"

    def record_quality_event(self, *args, **kwargs):
        self.quality_events.append((args, kwargs))

    def archive_universe(self, rows, snapshot_date):
        self.universe = list(rows)
        return {
            "date": str(snapshot_date), "count": len(self.universe), "complete": True,
            "payload_hash": "u" * 64, "snapshot_id": "s" * 64,
            "observed_at": dt.datetime.now(UTC).isoformat(), "source": "test-universe",
        }

    def archive_quotes(self, rows, **kwargs):
        self.quotes = list(rows)
        return len(self.quotes)

    def prior_average_volumes(self, keys, **kwargs):
        return {key: 1000.0 for key in keys}

    def upsert_scanner_observations(self, rows):
        self.scanner = list(rows)
        return len(self.scanner)


class Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FlowClient:
    def get(self, url, **kwargs):
        participant = "FII" if url.endswith("/fii") else "DII"
        return Response({
            "status": "success",
            "data": {"NSE_EQ|CASH": [{
                "time_stamp": 1_788_566_400_000,
                "buy_amount": 100 if participant == "FII" else 80,
                "sell_amount": 90,
            }]},
        })


class BadGlobalQuoteResponse:
    status_code = 400

    def raise_for_status(self):
        raise requests.HTTPError("400 Bad Request", response=self)

    def json(self):
        return {
            "status": "error",
            "errors": [{"errorCode": "UDAPI100095", "message": "Invalid Instrument key"}],
        }


class BadGlobalQuoteClient:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return BadGlobalQuoteResponse()


class InstrumentMasterResponse:
    status_code = 200

    def __init__(self, rows):
        self.content = gzip.compress(json.dumps(rows).encode("utf-8"))

    def raise_for_status(self):
        return None


class InstrumentMasterClient:
    def __init__(self, global_rows, nse_rows, mcx_rows):
        self.rows = {
            "global.json.gz": global_rows,
            "NSE.json.gz": nse_rows,
            "MCX.json.gz": mcx_rows,
        }

    def get(self, url, **kwargs):
        name = url.rsplit("/", 1)[-1]
        return InstrumentMasterResponse(self.rows[name])


def quote(price, close, volume, received):
    return {
        "last_price": price,
        "ohlc": {"high": price + 2, "low": price - 2, "close": close},
        "volume": volume,
        "market_depth": {
            "buy": [{"price": price - 0.1, "quantity": 100}],
            "sell": [{"price": price + 0.1, "quantity": 120}],
        },
        "_received_at": received.isoformat(),
        "timestamp": received.isoformat(),
    }


def test_manual_and_scheduled_stage1_share_one_deterministic_algorithm():
    now = dt.datetime(2026, 9, 7, 10, 0, tzinfo=collector.IST)
    tickers = ["AAA", "BBB", "CCC"]
    instruments = {ticker: f"NSE_EQ|{ticker}" for ticker in tickers}
    quotes = {
        instruments["AAA"]: quote(105, 100, 1800, now.astimezone(UTC)),
        instruments["BBB"]: quote(98, 100, 1200, now.astimezone(UTC)),
        instruments["CCC"]: quote(101, 100, 800, now.astimezone(UTC)),
    }
    averages = {key: 1000.0 for key in instruments.values()}
    one = stage1_prefilter(
        tickers, instruments, quotes, 2, average_volumes=averages, elapsed_fraction=0.25,
    )
    two = stage1_prefilter(
        tickers, instruments, quotes, 2, average_volumes=averages, elapsed_fraction=0.25,
    )
    assert one == two

    source = (ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    wrapper = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef)
                   and node.name == "stage1_multi_bucket_prefilter")
    calls = [node.func.id for node in ast.walk(wrapper)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    assert "stage1_prefilter" in calls


def test_stage1_represents_non_finite_average_volume_as_unavailable():
    now = dt.datetime(2026, 9, 7, 10, 0, tzinfo=collector.IST)
    keys = {"AAA": "NSE_EQ|AAA", "BBB": "NSE_EQ|BBB"}

    _, stats = stage1_prefilter(
        list(keys), keys,
        {
            keys["AAA"]: quote(105, 100, 1800, now.astimezone(UTC)),
            keys["BBB"]: quote(102, 100, 1200, now.astimezone(UTC)),
        },
        2,
        average_volumes={keys["AAA"]: float("nan"), keys["BBB"]: 1000.0},
        elapsed_fraction=0.25,
    )

    evidence = {row["trading_symbol"]: row for row in stats["_evidence"]}
    features = evidence["AAA"]["features"]
    assert features["average_volume_20d"] is None
    assert features["raw_volume_ratio"] is None
    assert features["volume_pace_ratio"] is None
    assert evidence["BBB"]["features"]["average_volume_20d"] == 1000.0


def test_scheduled_scan_records_complete_shadow_funnel_and_never_buy(monkeypatch):
    now = dt.datetime(2026, 9, 7, 10, 0, tzinfo=collector.IST)
    universe = [
        {"instrument_key": "NSE_EQ|AAA", "trading_symbol": "AAA"},
        {"instrument_key": "NSE_EQ|BBB", "trading_symbol": "BBB"},
    ]
    quotes = {
        "NSE_EQ|AAA": quote(105, 100, 1800, now.astimezone(UTC)),
        "NSE_EQ|BBB": quote(98, 100, 1200, now.astimezone(UTC)),
    }
    repo = MemoryRepository()
    monkeypatch.delenv("PROSPECTIVE_DATA_LICENSE_ACK", raising=False)
    monkeypatch.setenv("SCHEDULED_STAGE1_TOP_N", "1")
    monkeypatch.setattr(collector, "fetch_nse_universe", lambda client: universe)
    monkeypatch.setattr(collector, "fetch_full_quotes", lambda client, token, keys: quotes)
    monkeypatch.setattr(
        collector, "fetch_nse_exchange_status",
        lambda client, token: {"exchange": "NSE", "status": "NORMAL_OPEN"},
    )

    result = collector._scheduled_stage1(repo, object(), "token", "run-1", now=now)
    assert result["status"] == "SUCCESS"
    assert len(repo.scanner) == len(universe)
    assert all(not row["stage2_pass"] for row in repo.scanner)
    batch = next(row for row in repo.ledger if row["event_type"] == "DECISION_BATCH_EVALUATED")
    assert {row["action"] for row in batch["payload"]["candidates"]} <= {"Watch", "No Trade"}
    assert result["order_book_shadow"]["status"] == "DISABLED"


def test_scan_clock_is_timezone_aware_and_bounded():
    assert collector.is_nse_scan_window(
        dt.datetime(2026, 9, 7, 9, 30, tzinfo=collector.IST)
    )
    assert not collector.is_nse_scan_window(
        dt.datetime(2026, 9, 7, 15, 16, tzinfo=collector.IST)
    )
    assert not collector.is_nse_scan_window(
        dt.datetime(2026, 9, 6, 10, 0, tzinfo=collector.IST)
    )
    with pytest.raises(ValueError):
        collector.is_nse_scan_window(dt.datetime(2026, 9, 7, 10, 0))
    assert collector.is_us_close_capture_window(
        dt.datetime(2026, 9, 8, 3, 15, tzinfo=collector.IST)
    )
    assert not collector.is_us_close_capture_window(
        dt.datetime(2026, 9, 8, 12, 0, tzinfo=collector.IST)
    )


def test_exchange_status_accepts_same_session_transition_and_fails_closed():
    now = dt.datetime(2026, 9, 7, 5, 11, tzinfo=UTC)  # 10:41 IST

    class Client:
        def __init__(self, status, updated):
            self.status = status
            self.updated = updated

        def get(self, *args, **kwargs):
            return Response({
                "status": "success",
                "data": {"exchange": "NSE", "status": self.status,
                         "last_updated": int(self.updated.timestamp() * 1000)},
            })

    assert collector.fetch_nse_exchange_status(
        Client("NORMAL_OPEN", now - dt.timedelta(seconds=10)), "token", now=now,
    )["status"] == "NORMAL_OPEN"
    # last_updated identifies the status transition (normally the 09:15 open),
    # not a continuously refreshed provider heartbeat.
    same_session = collector.fetch_nse_exchange_status(
        Client("NORMAL_OPEN", now - dt.timedelta(minutes=85)), "token", now=now,
    )
    assert same_session["age_seconds"] == pytest.approx(85 * 60)
    with pytest.raises(RuntimeError, match="not in NORMAL_OPEN"):
        collector.fetch_nse_exchange_status(Client("CLOSED", now), "token", now=now)
    with pytest.raises(RuntimeError, match="current IST trading date"):
        collector.fetch_nse_exchange_status(
            Client("NORMAL_OPEN", now - dt.timedelta(days=1)), "token", now=now,
        )
    with pytest.raises(RuntimeError, match="future-dated"):
        collector.fetch_nse_exchange_status(
            Client("NORMAL_OPEN", now + dt.timedelta(minutes=1)), "token", now=now,
        )


def test_prospective_writer_preserves_first_known_time_and_rejects_reversed_time():
    repo = MemoryRepository()
    writer = ProspectiveFeatureWriter(repo)
    available = dt.datetime(2026, 9, 7, 16, 0, tzinfo=UTC)
    effective = available - dt.timedelta(hours=1)
    result = writer.record(
        instrument_key="NSE_EQ|AAA", definition=COMPANY_PROFILE,
        value={"sector": "Banks"}, effective_at=effective,
        available_at=available, observed_at=available,
    )
    assert result["stored"] is True
    assert repo.features[0]["effective_at"] == effective
    assert repo.features[0]["available_at"] == available

    rejected = writer.record(
        instrument_key="NSE_EQ|BBB", definition=COMPANY_PROFILE,
        value={"sector": "IT"}, effective_at=available + dt.timedelta(seconds=1),
        available_at=available, observed_at=available,
    )
    assert rejected["stored"] is False
    assert len(repo.features) == 1


def test_provider_archival_requires_explicit_operator_acknowledgement(monkeypatch):
    monkeypatch.delenv("PROSPECTIVE_DATA_LICENSE_ACK", raising=False)
    with pytest.raises(LicenseAcknowledgementRequired):
        require_licence_acknowledgement()
    monkeypatch.setenv("PROSPECTIVE_DATA_LICENSE_ACK", "true")
    require_licence_acknowledgement()


def test_order_book_quality_rejects_crossed_depth_before_storage():
    now = dt.datetime(2026, 9, 7, 5, 0, tzinfo=UTC)
    repo = MemoryRepository()
    writer = ProspectiveFeatureWriter(repo)
    valid = quote(100, 99, 1000, now)
    crossed = quote(100, 99, 1000, now)
    crossed["market_depth"]["buy"][0]["price"] = 101
    crossed["market_depth"]["sell"][0]["price"] = 100
    result = store_order_books(
        writer, {"NSE_EQ|AAA": valid, "NSE_EQ|BBB": crossed},
        ["NSE_EQ|AAA", "NSE_EQ|BBB"],
    )
    assert result == {
        "stored": 1, "rejected": 1, "missing_depth": 0,
        "derived_stored": 2, "derived_rejected": 0,
        "consumed_by_scoring": False,
    }
    assert len(repo.features) == 3
    assert any(args[2] == "DEPTH_SCHEMA_OR_RANGE_INVALID" for args, _ in repo.quality_events)


def test_flow_collection_uses_provider_effective_and_actual_receipt_timestamps():
    before = dt.datetime.now(UTC)
    rows = fetch_institutional_flows(FlowClient(), "token")
    after = dt.datetime.now(UTC)
    assert {row["participant"] for row in rows} == {"FII", "DII"}
    assert all(before <= row["available_at"] <= after for row in rows)
    assert all(row["provider_effective_at"] < row["available_at"] for row in rows)


def test_global_quote_400_is_per_key_explicit_and_not_retried():
    client = BadGlobalQuoteClient()

    result = fetch_global_quotes(client, "token", ["GLOBAL_INDEX|^DJI"])

    assert result == {
        "quotes": {},
        "failures": [{
            "instrument_key": "GLOBAL_INDEX|^DJI",
            "error_kind": "HTTPError",
            "http_status": 400,
            "provider_code": "UDAPI100095",
        }],
        "requested": 1,
    }
    assert len(client.calls) == 1
    assert client.calls[0][0].endswith("/v2/market-quote/quotes")
    assert client.calls[0][1]["params"] == {"instrument_key": "GLOBAL_INDEX|^DJI"}


def test_domestic_proxy_cues_select_nearest_futures_and_store_clear_labels():
    as_of = dt.date(2026, 9, 7)
    client = InstrumentMasterClient(
        global_rows=[
            {"segment": "GLOBAL_INDEX", "name": "DOW JONES",
             "instrument_key": "GLOBAL_INDEX|^DJI", "latency": "20 Seconds"},
            {"segment": "GLOBAL_INDICATOR", "name": "USD INR",
             "instrument_key": "GLOBAL_INDICATOR|USDINR", "latency": "20 Seconds"},
            {"segment": "GLOBAL_INDICATOR", "name": "OIL (BRENT)",
             "instrument_key": "GLOBAL_INDICATOR|BZUSD", "latency": "20 Seconds"},
        ],
        nse_rows=[
            {"segment": "NCD_FO", "instrument_type": "FUT",
             "underlying_symbol": "USDINR", "expiry": 1788652800000,
             "trading_symbol": "USDINR FUT 06 SEP 26", "instrument_key": "NCD_FO|old"},
            {"segment": "NCD_FO", "instrument_type": "FUT",
             "underlying_symbol": "USDINR", "expiry": 1789084800000,
             "trading_symbol": "USDINR FUT 11 SEP 26", "instrument_key": "NCD_FO|11993"},
            {"segment": "NCD_FO", "instrument_type": "FUT",
             "underlying_symbol": "USDINR", "expiry": 1789689600000,
             "trading_symbol": "USDINR FUT 18 SEP 26", "instrument_key": "NCD_FO|1883"},
        ],
        mcx_rows=[
            {"segment": "MCX_FO", "instrument_type": "FUT",
             "underlying_symbol": "CRUDEOIL", "expiry": 1789948800000,
             "trading_symbol": "CRUDEOIL FUT 21 SEP 26",
             "instrument_key": "MCX_FO|565899"},
            {"segment": "MCX_FO", "instrument_type": "FUT",
             "underlying_symbol": "CRUDEOIL", "expiry": 1792368000000,
             "trading_symbol": "CRUDEOIL FUT 19 OCT 26",
             "instrument_key": "MCX_FO|569900"},
        ],
    )

    instruments = fetch_global_instruments(client, as_of=as_of)
    by_key = {row["instrument_key"]: row for row in instruments}

    assert set(by_key) == {
        "GLOBAL_INDEX|^DJI", "NCD_FO|11993", "MCX_FO|565899",
    }
    assert "GLOBAL_INDICATOR|USDINR" not in by_key
    assert "GLOBAL_INDICATOR|BZUSD" not in by_key
    assert by_key["NCD_FO|11993"]["cue_label"] == (
        "NSE USDINR futures (INR spot proxy)"
    )
    assert by_key["MCX_FO|565899"]["cue_label"] == (
        "MCX CRUDEOIL (WTI-linked, domestic crude proxy)"
    )

    now = dt.datetime(2026, 9, 7, 10, 30, tzinfo=UTC)
    quotes = {
        key: {**quote(100, 99, 1000, now), "instrument_key": key}
        for key in by_key
    }
    repo = MemoryRepository()
    result = store_global_cues(
        ProspectiveFeatureWriter(repo), instruments, quotes,
    )

    assert result == {"stored": 3, "rejected": 0, "missing_quotes": 0}
    stored = {row["instrument_key"]: row["value"] for row in repo.features}
    assert stored["NCD_FO|11993"]["proxy_for"] == "USD/INR spot"
    assert "not the RBI" in stored["NCD_FO|11993"]["proxy_disclosure"]
    assert stored["NCD_FO|11993"]["declared_latency_seconds"] is None
    assert stored["MCX_FO|565899"]["proxy_for"] == "global crude oil"
    assert "not ICE Brent" in stored["MCX_FO|565899"]["proxy_disclosure"]


def test_known_missing_proxy_is_excluded_without_failing_global_cues(monkeypatch):
    now = dt.datetime(2026, 9, 7, 10, 30, tzinfo=UTC)
    instrument = {
        "segment": "GLOBAL_INDEX", "name": "DOW JONES",
        "instrument_key": "GLOBAL_INDEX|^DJI", "latency": "20 Seconds",
    }
    selection = CueInstrumentSelection(
        [instrument],
        known_excluded_gaps=[{
            "cue_label": "NSE USDINR futures (INR spot proxy)",
            "underlying_symbol": "USDINR", "segment": "NCD_FO",
            "reason": "no_non_expired_future_in_current_master",
            "as_of": "2026-09-07",
        }],
    )
    repo = MemoryRepository()
    monkeypatch.setenv("PROSPECTIVE_DATA_LICENSE_ACK", "true")
    monkeypatch.setattr(collector, "fetch_global_instruments", lambda unused: selection)
    monkeypatch.setattr(
        collector, "fetch_global_quotes",
        lambda *args: {
            "quotes": {"GLOBAL_INDEX|^DJI": quote(100, 99, 1000, now)},
            "failures": [], "requested": 1,
        },
    )

    result = collector._global_cue_shadow(
        repo, object(), "token", capture_context="INDIA_CLOSE",
    )

    assert result["status"] == "SUCCESS"
    assert result["stored"] == 1
    assert result["known_excluded_gaps"][0]["underlying_symbol"] == "USDINR"
    assert any(
        args[2] == "GLOBAL_CUE_PROXY_EXCLUDED" for args, _ in repo.quality_events
    )


def test_target_maturation_uses_each_decisions_immutable_fifteen_session_horizon(monkeypatch):
    observed_at = dt.datetime(2026, 1, 2, 10, 0, tzinfo=collector.IST)
    decision_at = observed_at.astimezone(UTC)
    dates = pd.bdate_range("2026-01-05", periods=20)
    history = pd.DataFrame({
        "Open": 100.0, "High": 103.0, "Low": 98.0, "Close": 101.0, "Volume": 1000.0,
    }, index=dates)

    class MaturityRepository(MemoryRepository):
        def __init__(self):
            super().__init__()
            self.pending_kwargs = None
            self.saved_targets = []
            self.ledger.append({
                "aggregate_id": "decision:decision-15",
                "event_type": "DECISION_EVALUATED",
                "idempotency_key": "decision-15-evaluated",
                "payload": {
                    "decision_at": decision_at.isoformat(),
                    "identifiers": {
                        "target_version": collector.TARGET_VERSION,
                        "horizon_sessions": 15,
                    },
                },
            })

        def pending_observations(self, **kwargs):
            self.pending_kwargs = kwargs
            return [{
                "observation_id": "decision-15",
                "as_of_date": "2026-01-02",
                "observed_at": observed_at,
                "instrument_key": "NSE_EQ|TEST",
                "trading_symbol": "TEST",
                "entry": 100.0,
                "stop": 95.0,
                "target": 110.0,
                "features": {"execution_cost_bps": 30.0},
                "horizon_sessions": 15,
            }]

        def save_prediction_target(self, observation_id, target):
            self.saved_targets.append((observation_id, target))

    repo = MaturityRepository()
    evaluated_horizons = []
    history_state = {"value": history.iloc[:14]}

    monkeypatch.setattr(
        collector, "fetch_daily_history", lambda *args, **kwargs: history_state["value"],
    )
    monkeypatch.setattr(collector, "fetch_historical_minutes", lambda *args, **kwargs: pd.DataFrame())

    def compute_target(prices, as_of_date, definition, **kwargs):
        evaluated_horizons.append(definition.horizon_sessions)
        outcome_date = prices.index[definition.horizon_sessions - 1]
        return {
            "horizon_sessions": definition.horizon_sessions,
            "target_version": collector.TARGET_VERSION,
            "entry_date": str(prices.index[0].date()),
            "label_end_date": str(outcome_date.date()),
            "outcome_date": outcome_date,
            "outcome": "horizon",
            "target_before_stop": False,
            "gross_return": 0.04,
            "net_return": 0.037,
            "benchmark_return": 0.01,
            "excess_return": 0.027,
            "positive_excess": True,
            "cost_bps": 30.0,
            "entry_quality": "first_minute_after_signal",
        }

    monkeypatch.setattr(collector, "compute_forward_target", compute_target)

    deferred = collector.update_matured_targets(repo, object(), "token")

    assert deferred == {"pending": 1, "stored": 0, "failed": 0, "deferred": 1, "failures": []}
    assert evaluated_horizons == []
    assert not [row for row in repo.ledger if row["event_type"] == "OUTCOME_MATURED"]

    history_state["value"] = history
    result = collector.update_matured_targets(repo, object(), "token")

    assert result == {"pending": 1, "stored": 1, "failed": 0, "deferred": 0, "failures": []}
    assert repo.pending_kwargs == {"target_version": collector.TARGET_VERSION, "limit": 40}
    assert evaluated_horizons == [15]
    assert repo.saved_targets[0][0] == "decision-15"
    assert repo.saved_targets[0][1]["horizon_sessions"] == 15
    matured = [row for row in repo.ledger if row["event_type"] == "OUTCOME_MATURED"]
    assert len(matured) == 1
    assert matured[0]["payload"]["horizon_sessions"] == 15
    assert len(matured[0]["payload"]["completed_session_closes"]) == 15


def test_close_run_keeps_committed_stages_when_one_global_quote_returns_400(monkeypatch):
    class RunRepository(MemoryRepository):
        def __init__(self):
            super().__init__()
            self.commits = []
            self.finished = []

        def acquire_collector_lease(self, *args, **kwargs):
            return {"fencing_token": 41}

        def renew_collector_lease(self, *args, **kwargs):
            return True

        def release_collector_lease(self, *args, **kwargs):
            return True

        def start_run(self, *args, **kwargs):
            return "close-run"

        def finish_run(self, run_id, **kwargs):
            self.finished.append((run_id, kwargs))

        def archive_universe(self, rows, snapshot_date):
            self.commits.append("nse_universe")
            return super().archive_universe(rows, snapshot_date)

        def archive_quotes(self, rows, **kwargs):
            self.commits.append("nse_quotes")
            return super().archive_quotes(rows, **kwargs)

    repo = RunRepository()
    client = BadGlobalQuoteClient()
    universe = [{"instrument_key": "NSE_EQ|AAA", "trading_symbol": "AAA"}]

    monkeypatch.setenv("UPSTOX_ANALYTICS_TOKEN", "token")
    monkeypatch.setenv("PROSPECTIVE_DATA_LICENSE_ACK", "true")
    monkeypatch.setattr(collector, "ProductionRepository", lambda *args, **kwargs: repo)
    monkeypatch.setattr(collector, "session", lambda: client)
    monkeypatch.setattr(collector, "fetch_nse_universe", lambda unused: universe)
    monkeypatch.setattr(
        collector, "fetch_quotes",
        lambda unused_client, unused_token, unused_keys: [{"instrument_key": "NSE_EQ|AAA"}],
    )

    def mature(*args, **kwargs):
        repo.commits.append("target_maturation")
        return {"stored": 2, "failed": 0}

    def mutual_funds(*args, **kwargs):
        repo.commits.append("mutual_funds")
        return {"nav_archived": 3, "disclosures_archived": 0}

    def store_flows(writer, rows):
        writer.repository.commits.append("institutional_flows")
        return {"stored": 4, "rejected": 0}

    def profiles(repository, *args, **kwargs):
        repository.commits.append("company_profiles")
        return {"checked": 5, "stored": 5, "failed": 0}

    monkeypatch.setattr(collector, "update_matured_targets", mature)
    monkeypatch.setattr(collector, "archive_mutual_funds", mutual_funds)
    monkeypatch.setattr(collector, "fetch_institutional_flows", lambda *args: [{}])
    monkeypatch.setattr(collector, "store_institutional_flows", store_flows)
    monkeypatch.setattr(
        collector, "fetch_global_instruments",
        lambda unused: [{
            "name": "DOW JONES", "instrument_key": "GLOBAL_INDEX|^DJI",
            "latency": "20 Seconds",
        }],
    )
    monkeypatch.setattr(collector, "collect_company_profiles", profiles)

    result = collector.run("close")

    assert result["status"] == "PARTIAL"
    assert result["prospective_shadow"]["global_cues"]["status"] == "FAILED"
    assert result["prospective_shadow"]["company_profiles"]["status"] == "SUCCESS"
    assert repo.commits == [
        "nse_universe", "nse_quotes", "target_maturation", "mutual_funds",
        "institutional_flows", "company_profiles",
    ]
    assert repo.finished[-1][1]["status"] == "PARTIAL"
    assert repo.finished[-1][1]["record_count"] == 16
    assert "error_kind" not in repo.finished[-1][1]
    assert repo.finished[-1][1]["metadata"]["targets"] == {"stored": 2, "failed": 0}
    assert any(
        args[0] == "prospective_global_cues" and args[2] == "GLOBAL_QUOTE_FETCH_FAILED"
        for args, _ in repo.quality_events
    )
    assert len(client.calls) == 1
