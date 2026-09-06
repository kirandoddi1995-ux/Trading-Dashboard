import datetime as dt
import sqlite3

import pytest

from decision_evidence import (
    DecisionEvidenceSpine,
    EvidenceContractError,
    ExperimentTracker,
    FeatureDefinition,
    FeatureQualityMonitor,
    FeatureRegistry,
)
from evidence_ledger import ImmutableEvidenceLedger
from live_evidence import EvidenceTier, LiveEvidenceBundle, LiveEvidenceContext, feature_schema_digest
from observability import MetricsRegistry


UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 7, 10, 0, tzinfo=UTC)


def connect(path):
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def services(tmp_path):
    ledger = ImmutableEvidenceLedger(connect, str(tmp_path / "evidence.sqlite3"), signing_key="key")
    registry = FeatureRegistry(ledger.append, ledger)
    registry.register(FeatureDefinition(
        name="score", version="score-v1", dtype="float", source="provider",
        computation_logic="Frozen rule score v1", availability_rule="provider timestamp <= decision",
        maximum_age_seconds=120, minimum=0, maximum=100,
    ), registered_at=NOW - dt.timedelta(days=1))
    quality = FeatureQualityMonitor(registry, ledger.append, MetricsRegistry())
    spine = DecisionEvidenceSpine(ledger.append, ledger, feature_quality=quality)
    return ledger, registry, spine


def evidence():
    lineage = {
        "score": {
            "value": 72.0, "source": "provider",
            "effective_at": (NOW - dt.timedelta(seconds=2)).isoformat(),
            "available_at": (NOW - dt.timedelta(seconds=1)).isoformat(),
            "definition_version": "score-v1", "dtype": "float",
            "maximum_age_seconds": 120,
        }
    }
    return LiveEvidenceBundle(
        context=LiveEvidenceContext(
            strategy_id="rules-v1", asset_class="equity", target_version="barrier-v1",
            horizon_sessions=2, instrument="A", decision_at=NOW,
            feature_schema_hash=feature_schema_digest(lineage),
        ),
        tier=EvidenceTier.OBSERVATION,
        quote_observed_at=NOW - dt.timedelta(seconds=1), quote_received_at=NOW,
        quote_source="provider", feature_lineage=lineage,
        universe_observed_at=NOW - dt.timedelta(hours=1),
        universe_effective_at=NOW - dt.timedelta(hours=2),
    )


def capture_kwargs():
    return {
        "evidence": evidence(), "action": "No Trade", "direction": "long",
        "entry": 100, "stop": 95, "target": 110, "quantity": 0,
        "governance": {"status": "NO_TRADE", "blocking_reasons": ["uncalibrated"]},
        "quote": {"source": "provider", "bid": 99.9, "ask": 100.1, "last": 100},
        "universe": {
            "snapshot_id": "snapshot-1", "payload_hash": "u" * 64,
            "source": "provider universe", "member": True,
            "observed_at": (NOW - dt.timedelta(hours=1)).isoformat(),
            "effective_at": (NOW - dt.timedelta(hours=2)).isoformat(),
        },
        "costs": {
            "round_trip_bps": 20, "spread_bps": 20, "slippage_bps": 0,
            "impact_bps": 0, "statutory_bps": 0, "brokerage_bps": 0,
            "breakdown_complete": True, "assumptions": "fixture",
        },
        "code_version": "v1", "code_hash": "c" * 64,
        "config_hash": "g" * 64, "policy_hash": "p" * 64,
        "correlation_id": "correlation-1", "decision_id": "decision-1",
    }


def test_logged_decision_snapshot_is_immutable_after_caller_mutation(tmp_path):
    ledger, _, spine = services(tmp_path)
    kwargs = capture_kwargs()
    result = spine.capture(**kwargs)
    kwargs["governance"]["status"] = "PASS"
    kwargs["quote"]["bid"] = 1
    stored = ledger.events("decision:decision-1")[0]
    assert stored["payload"]["governance"]["status"] == "NO_TRADE"
    assert stored["payload"]["quote"]["bid"] == 99.9
    assert result["record"]["features"]["raw_values_used"] == {"score": 72.0}
    conn = connect(str(tmp_path / "evidence.sqlite3"))
    try:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE evidence_ledger_events SET payload_json='{}'")
    finally:
        conn.close()


def test_outcome_waits_for_real_session_horizon_and_is_write_once(tmp_path):
    ledger, _, spine = services(tmp_path)
    spine.capture(**capture_kwargs())
    closes = [NOW + dt.timedelta(hours=6), NOW + dt.timedelta(days=1, hours=6)]
    with pytest.raises(EvidenceContractError, match="horizon has not passed"):
        spine.outcome(
            decision_id="decision-1", outcome="TIMEOUT", outcome_at=closes[0],
            actual_forward_return=.01, completed_session_closes=closes,
            source_observation_ids=["bar-1", "bar-2"], actual_costs={"bps": 20},
            now=closes[0],
        )
    first = spine.outcome(
        decision_id="decision-1", outcome="TIMEOUT", outcome_at=closes[-1],
        actual_forward_return=.01, completed_session_closes=closes,
        source_observation_ids=["bar-1", "bar-2"], actual_costs={"bps": 20},
        now=closes[-1],
    )
    second = spine.outcome(
        decision_id="decision-1", outcome="TIMEOUT", outcome_at=closes[-1],
        actual_forward_return=.01, completed_session_closes=closes,
        source_observation_ids=["bar-1", "bar-2"], actual_costs={"bps": 20},
        now=closes[-1],
    )
    assert first["event"]["duplicate"] is False
    assert second["event"]["duplicate"] is True
    with pytest.raises(ValueError, match="different evidence"):
        spine.outcome(
            decision_id="decision-1", outcome="STOP", outcome_at=closes[-1],
            actual_forward_return=-.05, completed_session_closes=closes,
            source_observation_ids=["bar-1", "bar-2"], actual_costs={"bps": 20},
            now=closes[-1],
        )
    assert [event["event_type"] for event in ledger.events("decision:decision-1")].count("OUTCOME_MATURED") == 1


def test_incomplete_decision_context_fails_without_partial_event(tmp_path):
    ledger, _, spine = services(tmp_path)
    kwargs = capture_kwargs()
    kwargs["costs"].pop("assumptions")
    with pytest.raises(EvidenceContractError, match="cost context is missing"):
        spine.capture(**kwargs)
    assert ledger.events("decision:decision-1") == []


def test_buy_requires_executable_quote_verified_universe_and_complete_costs(tmp_path):
    ledger, _, spine = services(tmp_path)
    kwargs = capture_kwargs()
    kwargs["action"] = "Buy"
    kwargs["quote"]["ask"] = None
    with pytest.raises(EvidenceContractError, match="Buy decision lacks executable quote"):
        spine.capture(**kwargs)
    assert ledger.events("decision:decision-1") == []


def test_feature_quality_records_stale_range_and_schema_failures(tmp_path):
    ledger, registry, _ = services(tmp_path)
    monitor = FeatureQualityMonitor(registry, ledger.append, MetricsRegistry())
    result = monitor.observe(
        source_id="equity:rules-v1", decision_at=NOW,
        required_features=["score", "missing"],
        feature_lineage={
            "score": {
                "value": 101, "source": "provider", "definition_version": "score-v1",
                "effective_at": (NOW - dt.timedelta(minutes=5)).isoformat(),
                "available_at": (NOW - dt.timedelta(minutes=5)).isoformat(),
                "maximum_age_seconds": 120,
            }
        },
    )
    codes = {failure["code"] for failure in result["failures"]}
    assert result["status"] == "FAIL"
    assert {"MISSING", "STALE", "RANGE_HIGH"}.issubset(codes)
    assert ledger.events("feature-quality:equity:rules-v1")[-1]["payload"]["status"] == "FAIL"


def test_experiment_tracker_retains_negative_results_and_retries(tmp_path):
    ledger, _, _ = services(tmp_path)
    tracker = ExperimentTracker(ledger.append, ledger)
    request = {
        "hypothesis": "feature x adds signal",
        "data_window": {"start": "2026-01-01", "end": "2026-06-30"},
        "config_hash": "g" * 64, "feature_versions": {"score": "score-v1"},
        "code_hash": "c" * 64,
    }
    first = tracker.start(**request, trial_id="trial-1", started_at=NOW)
    tracker.finish(
        first, status="NEGATIVE", metrics={"brier_skill": -0.01},
        result_summary="No validated improvement", finished_at=NOW + dt.timedelta(minutes=1),
    )
    second = tracker.start(
        **request, trial_id="trial-2", started_at=NOW + dt.timedelta(days=1),
    )
    events = ledger.events(f"experiment:{first['fingerprint']}")
    assert second["attempt"] == 2
    assert [event["event_type"] for event in events] == [
        "EXPERIMENT_REGISTERED", "EXPERIMENT_RESULT_RECORDED", "EXPERIMENT_RETRIED",
    ]
