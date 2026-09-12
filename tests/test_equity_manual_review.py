import datetime as dt
from pathlib import Path

import pytest

from equity_manual_review import (
    ManualReviewError, build_manual_review, decision_digest, review_status,
)


UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 13, 4, 0, tzinfo=UTC)


def signal(*, allowed=True, action="Buy", decision_id="decision-1", entry=100.0):
    return {
        "Ticker": "ABC", "Action": action, "_system_action": action,
        "_price_val": entry, "_sl": 95.0, "_tgt": 108.0,
        "_scan_run_id": "scan-1", "_quote_observed_at": NOW.isoformat(),
        "_decision_id": decision_id,
        "_governance": {
            "allow_trade": allowed, "decision_at": NOW.isoformat(),
            "decision_evidence": {"decision_id": decision_id},
        },
    }


def confirmed_review(candidate=None, **overrides):
    candidate = candidate or signal()
    values = dict(
        secondary_platform="Other broker", secondary_price=100.10,
        reviewer="single-user", attested_at=NOW,
        source_quote_observed_at=None, confirmed=True,
    )
    values.update(overrides)
    return build_manual_review(candidate, **values)


def test_manual_review_cannot_override_governance_or_non_buy():
    for candidate in (signal(allowed=False), signal(action="Watch")):
        with pytest.raises(ManualReviewError):
            confirmed_review(candidate)
        assert not review_status(candidate, None, now=NOW)["actionable"]


def test_confirmed_review_is_bound_to_exact_decision_and_details():
    candidate = signal()
    review = confirmed_review(candidate)
    assert review_status(candidate, review, now=NOW)["actionable"]
    superseded = signal(decision_id="decision-2")
    assert review_status(superseded, review, now=NOW)["status"] == "SUPERSEDED"
    changed_price = signal(entry=101.0)
    assert changed_price["_decision_id"] == candidate["_decision_id"]
    assert decision_digest(changed_price) != review["decision_digest"]
    assert review_status(changed_price, review, now=NOW)["status"] == "SUPERSEDED"


def test_review_requires_explicit_confirmation_and_real_values():
    with pytest.raises(ManualReviewError, match="explicitly confirmed"):
        confirmed_review(confirmed=False)
    with pytest.raises(ManualReviewError, match="platform"):
        confirmed_review(secondary_platform="")
    with pytest.raises(ManualReviewError, match="numeric"):
        confirmed_review(secondary_price="")


def test_price_mismatch_and_stale_review_never_become_actionable():
    candidate = signal()
    mismatch = confirmed_review(candidate, secondary_price=101.0)
    assert mismatch["status"] == "MISMATCH"
    assert not review_status(candidate, mismatch, now=NOW)["actionable"]
    matching = confirmed_review(candidate)
    stale_now = NOW + dt.timedelta(seconds=61)
    assert review_status(candidate, matching, now=stale_now)["status"] == "STALE"


def test_dashboard_actionability_is_structurally_additive():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert '_signal["Action"] = "Buy" if _manual_state["actionable"] else "Manual review required"' in source
    assert 'if _review_signal.get("_system_action") == "Buy"' not in source
    assert 'is_actionable = sig.get("Action") == "Buy"' in source
    assert 'event_type="SIGNAL_CREATED" if sig.get("Action") == "Buy" else "SIGNAL_AMENDED"' in source
