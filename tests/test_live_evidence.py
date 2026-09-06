import datetime as dt

from live_evidence import (
    EvidenceTier,
    LiveEvidenceBundle,
    LiveEvidenceContext,
    feature_schema_digest,
    provider_timestamp,
    quote_evidence_times,
    timestamped_feature_lineage,
    unavailable_bundle,
)
from live_governance import GovernanceServices, evaluate_live_governance
from resilience_control_plane import ResilienceControlPlane


UTC = dt.timezone.utc


def _lineage(now):
    return {
        "score": {
            "value": 71.0,
            "source": "scanner",
            "available_at": now - dt.timedelta(seconds=2),
            "effective_at": now - dt.timedelta(seconds=2),
            "definition_version": "score-v1",
            "dtype": "float",
        }
    }


def test_unavailable_bundle_never_manufactures_evidence():
    now = dt.datetime.now(UTC)
    bundle = unavailable_bundle(
        strategy_id="equity-scanner-v19.0", asset_class="equity",
        target_version="target-v1", horizon_sessions=5, instrument="NSE:ABC",
        decision_at=now,
    )
    assert bundle.tier is EvidenceTier.OBSERVATION
    assert bundle.quote_age_seconds is None
    failures = bundle.compatibility_failures()
    assert "Calibration evidence is unavailable" in failures
    assert "Portfolio return histories are unavailable" in failures


def test_context_rejects_naive_decision_timestamp():
    try:
        LiveEvidenceContext("s", "equity", "t", 5, "NSE:ABC", dt.datetime.now(), "hash")
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive timestamp was accepted")


def test_bundle_computes_quote_age_and_detects_context_mismatch():
    now = dt.datetime.now(UTC)
    lineage = _lineage(now)
    context = LiveEvidenceContext(
        "equity-scanner-v19.0", "equity", "target-v1", 5, "NSE:ABC", now,
        feature_schema_digest(lineage),
    )
    expected = context.compatibility_fields()
    package = {**expected}
    bundle = LiveEvidenceBundle(
        context=context, tier=EvidenceTier.VALIDATED,
        quote_observed_at=now - dt.timedelta(seconds=3), quote_received_at=now - dt.timedelta(seconds=2),
        quote_source="Upstox", feature_lineage=lineage,
        universe_observed_at=now - dt.timedelta(minutes=1),
        universe_effective_at=now - dt.timedelta(days=1),
        model_predictions=({"model_id": "m1"},), model_weights={"m1": 1.0},
        calibration_evidence=package,
        conformal_evidence=package,
        fill_evidence={**package, "asset_class": "options"},
        portfolio_returns=[[0.01]], portfolio_weights={"NSE:ABC": 0.1},
        stress_scenarios={"down": {"NSE:ABC": -0.1}},
    )
    assert bundle.quote_age_seconds == 3.0
    assert "Fill evidence context mismatch: asset_class" in bundle.compatibility_failures()


def test_developing_evidence_cannot_be_production_eligible():
    now = dt.datetime.now(UTC)
    lineage = _lineage(now)
    context = LiveEvidenceContext("s", "equity", "t", 5, "NSE:ABC", now, feature_schema_digest(lineage))
    bundle = LiveEvidenceBundle(context=context, tier=EvidenceTier.DEVELOPING, feature_lineage=lineage)
    assert any("not production eligible" in reason for reason in bundle.compatibility_failures())


class _Observability:
    def __init__(self):
        self.events = []

    def record(self, *args, **kwargs):
        self.events.append((args, kwargs))


class _Ledger:
    @staticmethod
    def outbox_stats():
        return {"pending": 0, "oldest_age_seconds": 0}


def test_ui_independent_governance_service_fails_closed_without_real_evidence():
    now = dt.datetime.now(UTC)
    bundle = unavailable_bundle(
        strategy_id="equity-scanner-v19.0", asset_class="equity",
        target_version="target-v1", horizon_sessions=5,
        instrument="NSE:ABC", decision_at=now,
    )
    observability = _Observability()
    result = evaluate_live_governance(
        instrument="NSE:ABC", entry=100, stop=95, target=112,
        spread_bps=10, order_value=1000, average_daily_value=1_000_000,
        evidence=bundle,
        services=GovernanceServices(
            control_plane=ResilienceControlPlane(), evidence_ledger=_Ledger(),
            observability=observability, app_build="test-build",
        ),
    )
    assert result["status"] == "NO_TRADE"
    assert result["allow_trade"] is False
    assert any("Calibration evidence is unavailable" in reason for reason in result["blocking_reasons"])
    assert observability.events


def test_quote_timestamps_are_measured_and_naive_text_is_rejected():
    observed = dt.datetime(2026, 9, 6, 4, 0, tzinfo=UTC)
    received = observed + dt.timedelta(seconds=1)
    parsed_observed, parsed_received = quote_evidence_times({
        "last_trade_time": int(observed.timestamp() * 1000),
        "_ts": received.timestamp(),
    })
    assert parsed_observed == observed
    assert parsed_received == received
    assert provider_timestamp("2026-09-06 09:30:00") is None


def test_timestamped_lineage_requires_real_time_and_preserves_definition():
    now = dt.datetime.now(UTC)
    lineage = timestamped_feature_lineage(
        {"score": 75.0}, source="Upstox + scanner", available_at=now,
        definition_version="scanner-v1", maximum_age_seconds=5,
    )
    assert lineage["score"]["available_at"] == now.isoformat()
    assert lineage["score"]["definition_version"] == "scanner-v1"
    try:
        timestamped_feature_lineage(
            {"score": 75.0}, source="provider", available_at=dt.datetime.now(),
            definition_version="v1", maximum_age_seconds=5,
        )
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive feature timestamp was accepted")
