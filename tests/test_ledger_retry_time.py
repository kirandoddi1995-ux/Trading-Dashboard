"""Offline regressions for immutable effective-time retry identity."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
import sqlite3
from typing import Any

import pytest

import evidence_ledger
from evidence_ledger import ImmutableEvidenceLedger


def connect(path: str) -> sqlite3.Connection:
    """Open only a disposable test ledger."""
    return sqlite3.connect(path, timeout=10)


def request() -> dict[str, Any]:
    """An original request with no market data or real signing material."""
    return {
        "aggregate_id": "equity:synthetic", "event_type": "DECISION_EVALUATED",
        "payload": {"identifiers": {"asset_class": "equity"}},
        "effective_at": "2026-09-12T04:00:00+00:00",
        "idempotency_key": "synthetic-time-identity",
    }


@pytest.mark.parametrize("queued", [False, True])
def test_explicit_changed_time_cannot_retry_or_create_intent(
    tmp_path: Path, queued: bool,
) -> None:
    """A conflicting retry cannot change an original or add a delivery row."""
    store = ImmutableEvidenceLedger(connect, str(tmp_path / "ledger.sqlite"),
                                    signing_key="synthetic-test-key")
    first = store.append(**request(), queue_remote_delivery=queued)
    before = store.pending_deliveries()
    changed = request()
    changed["effective_at"] = "2026-09-12T04:00:01+00:00"
    with pytest.raises(ValueError, match="different evidence"):
        store.append(**changed, queue_remote_delivery=True)
    assert store.pending_deliveries() == before
    assert store.events("equity:synthetic")[0]["event_hash"] == first["event_hash"]
    assert len(store.events("equity:synthetic")) == 1
    assert store.verify()["valid"]


@pytest.mark.parametrize("same_time", [
    "2026-09-12T09:30:00+05:30", "2026-09-12T04:00:00Z",
    dt.datetime(2026, 9, 12, 4, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 9, 12, 4),
])
def test_equivalent_instants_reuse_exact_original(
    tmp_path: Path, same_time: str | dt.datetime,
) -> None:
    """Timezone normalization retains the existing UTC/naive-time contract."""
    store = ImmutableEvidenceLedger(connect, str(tmp_path / "ledger.sqlite"))
    first = store.append(**request(), queue_remote_delivery=True)
    args = request()
    args["effective_at"] = same_time
    retry = store.append(**args, queue_remote_delivery=True)
    assert retry["duplicate"]
    assert retry["event_id"] == first["event_id"]
    assert retry["event_hash"] == first["event_hash"]
    assert store.pending_deliveries()[0]["effective_at"] == first["effective_at"]


@pytest.mark.parametrize("explicit_none", [False, True])
def test_omitted_time_retry_after_restart_retains_first_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, explicit_none: bool,
) -> None:
    """Later clocks and restart never replace the original default timestamp."""
    path = str(tmp_path / "ledger.sqlite")
    monkeypatch.setattr(evidence_ledger, "_utcnow",
                        lambda: dt.datetime(2026, 9, 12, 4, tzinfo=dt.timezone.utc))
    args = request()
    args.pop("effective_at")
    first = ImmutableEvidenceLedger(connect, path).append(**args)
    monkeypatch.setattr(evidence_ledger, "_utcnow",
                        lambda: dt.datetime(2026, 9, 13, 4, tzinfo=dt.timezone.utc))
    if explicit_none:
        args["effective_at"] = None
    reopened = ImmutableEvidenceLedger(connect, path)
    retry = reopened.append(**args, queue_remote_delivery=True)
    assert retry["event_id"] == first["event_id"]
    assert retry["effective_at"] == first["effective_at"]
    assert reopened.pending_deliveries()[0]["effective_at"] == first["effective_at"]
    assert reopened.verify()["valid"]


@pytest.mark.parametrize("invalid", ["", False, 0])
def test_explicit_invalid_time_is_not_treated_as_omission(
    tmp_path: Path, invalid: str | bool | int,
) -> None:
    """False-like malformed input cannot silently acquire the current time."""
    store = ImmutableEvidenceLedger(connect, str(tmp_path / "ledger.sqlite"))
    args = request()
    args["effective_at"] = invalid
    with pytest.raises(ValueError):
        store.append(**args, queue_remote_delivery=True)
    assert store.events("equity:synthetic") == []
    assert store.pending_deliveries() == []


def test_changed_time_after_ack_does_not_reset_acknowledgement(tmp_path: Path) -> None:
    """A refused request never reopens an already delivered original."""
    store = ImmutableEvidenceLedger(connect, str(tmp_path / "ledger.sqlite"))
    first = store.append(**request(), queue_remote_delivery=True)
    store.mark_delivered(first["idempotency_key"])
    args = request()
    args["effective_at"] = "2026-09-12T04:01:00+00:00"
    with pytest.raises(ValueError, match="different evidence"):
        store.append(**args, queue_remote_delivery=True)
    assert store.pending_deliveries() == []
    assert store.append(**request(), queue_remote_delivery=True)["duplicate"]
    assert store.pending_deliveries() == []
