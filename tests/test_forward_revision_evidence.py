"""Deterministic as-of and local custody checks using synthetic source versions."""
from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

import pytest

import forward_revision_evidence as evidence
import forward_revision_quarantine as quarantine
from research_integrity import IntegrityError, canonical
from test_forward_revision_quarantine import config as _fixture, candles as _candles, baseline, received, prepared, MemoryDrive

config = _fixture
candles = _candles


def records(config: dict[str, Any]) -> list[dict[str, Any]]:
    first = candles(config, 2)
    first[0][4] += 1
    second = candles(config, 3)
    second[0][4] += 2
    return [quarantine.snapshot(config, first, received(config, 10), baseline(config), 'a' * 64),
            quarantine.snapshot(config, second, received(config, 15), baseline(config), 'a' * 64)]


@pytest.mark.parametrize('timestamp,count,revision', [
    ('2022-01-03T09:20:29+05:30', 0, None),
    ('2022-01-03T09:20:30+05:30', 1, 0),
    ('2022-01-03T09:25:29+05:30', 1, 0),
    ('2022-01-03T09:25:30+05:30', 2, 1),
    ('2022-01-03T09:30:29+05:30', 2, 1),
    ('2022-01-03T09:30:30+05:30', 3, 2)])
def test_no_lookahead_and_exact_receipt_cutoff(config: dict[str, Any], timestamp: str,
        count: int, revision: int | None) -> None:
    result = evidence.versions_as_of(records(config), timestamp)
    assert len(result['bars']) == count
    if count:
        assert result['bars'][0]['values'][3] == baseline(config)[0]['values'][3] + revision
    assert result['training_eligible'] is False and result['decision_eligible'] is False


def test_timezone_equivalence_and_input_unchanged(config: dict[str, Any]) -> None:
    source = records(config)
    before = deepcopy(source)
    a = evidence.versions_as_of(source, '2022-01-03T09:25:30+05:30')
    b = evidence.versions_as_of(source, '2022-01-03T03:55:30+00:00')
    assert a == b and source == before


def test_empty_and_missing_stay_empty() -> None:
    assert evidence.versions_as_of([], '2022-01-03T03:55:30+00:00')['bars'] == []
    with pytest.raises(IntegrityError, match='AWARE_TIMESTAMP_REQUIRED'):
        evidence.versions_as_of([], '2022-01-03T09:25:30')


def test_identity_and_duplicate_slots_fail_closed(config: dict[str, Any]) -> None:
    source = records(config)
    with pytest.raises(IntegrityError, match='DUPLICATE_SLOT'):
        evidence.versions_as_of([source[0], source[0]], received(config, 15))
    source[1] = quarantine.snapshot(config, candles(config, 3), received(config, 15), baseline(config), 'b' * 64)
    with pytest.raises(IntegrityError, match='IDENTITY_CONFLICT'):
        evidence.versions_as_of(source, received(config, 15))


def test_same_receipt_conflicting_source_versions_fail(config: dict[str, Any]) -> None:
    old = baseline(config)
    old[0]['available_at'] = received(config, 10)
    bars = candles(config, 2)
    bars[0][4] += 1
    record = quarantine.snapshot(config, bars, received(config, 10), old, 'a' * 64)
    with pytest.raises(IntegrityError, match='SAME_RECEIPT_CONFLICT'):
        evidence.versions_as_of([record], received(config, 10))


def test_audit_binds_journal_snapshot_and_ack_without_writes(tmp_path: Path,
        config: dict[str, Any]) -> None:
    root, journal = prepared(tmp_path, config)
    recorder = quarantine.QuarantineProducer(config, journal, None)
    result = recorder.record_poll(candles(config, 2), received_at=received(config), computed_clock=datetime.now)
    manifest = quarantine.publish(MemoryDrive(), result)
    receipts = recorder.directory / 'receipts'
    receipts.mkdir()
    (receipts / 'receipt-synthetic.json').write_bytes(canonical(manifest))
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    report = evidence.audit(root, date(2022, 1, 3))
    assert report['accepted_observations'] == 1 and report['missing_accepted_decisions'] == 74
    assert report['raw_snapshots'] == report['locally_recorded_remote_verifications'] == 1
    assert report['raw_snapshots_without_verified_receipt'] == 0
    assert all(p.read_bytes() == data for p, data in before.items())
    assert {p for p in root.rglob('*') if p.is_file()} == set(before)


def test_unacknowledged_snapshot_not_claimed_as_remote(tmp_path: Path, config: dict[str, Any]) -> None:
    root, journal = prepared(tmp_path, config)
    recorder = quarantine.QuarantineProducer(config, journal, None)
    recorder.record_poll(candles(config, 2), received_at=received(config), computed_clock=datetime.now)
    report = evidence.audit(root, date(2022, 1, 3))
    assert report['locally_recorded_remote_verifications'] == 0
    assert report['raw_snapshots_without_verified_receipt'] == 1


@pytest.mark.parametrize('field,value', [('slot', '2022-01-03T04:00:00+00:00'),
                                       ('sha256', 'f' * 64), ('training_eligible', True)])
def test_forged_or_orphan_receipt_blocks(tmp_path: Path, config: dict[str, Any],
        field: str, value: Any) -> None:
    root, journal = prepared(tmp_path, config)
    recorder = quarantine.QuarantineProducer(config, journal, None)
    result = recorder.record_poll(candles(config, 2), received_at=received(config), computed_clock=datetime.now)
    manifest = quarantine.publish(MemoryDrive(), result)
    manifest[field] = value
    receipts = recorder.directory / 'receipts'
    receipts.mkdir()
    (receipts / 'receipt-synthetic.json').write_bytes(canonical(manifest))
    with pytest.raises(IntegrityError, match='RECEIPT_INVALID'):
        evidence.audit(root, date(2022, 1, 3))


def test_private_reads_are_bounded(tmp_path: Path) -> None:
    path = tmp_path / 'large.json'
    path.write_bytes(b'x' * 11)
    with pytest.raises(IntegrityError, match='SIZE_BOUND'):
        evidence.private_read(path, 10)


@pytest.mark.parametrize('maximum', [0, -1, quarantine.MAX_BYTES + 1])
def test_invalid_read_bounds_fail_before_open(tmp_path: Path, maximum: int) -> None:
    with pytest.raises(IntegrityError, match='SIZE_BOUND'):
        evidence.private_read(tmp_path / 'does-not-exist', maximum)


def test_policy_must_match_the_original_journal(tmp_path: Path, config: dict[str, Any]) -> None:
    root, journal = prepared(tmp_path, config)
    recorder = quarantine.QuarantineProducer(config, journal, None)
    recorder.record_poll(candles(config, 2), received_at=received(config), computed_clock=datetime.now)
    path = recorder.directory / 'policy.json'
    policy = json.loads(path.read_bytes())
    policy['baseline_sha256'] = 'f' * 64
    path.write_bytes(canonical(policy))
    with pytest.raises(IntegrityError, match='IDENTITY_CONFLICT'):
        evidence.audit(root, date(2022, 1, 3))


def test_snapshot_damage_blocks_instead_of_counting_success(tmp_path: Path, config: dict[str, Any]) -> None:
    root, journal = prepared(tmp_path, config)
    recorder = quarantine.QuarantineProducer(config, journal, None)
    recorder.record_poll(candles(config, 2), received_at=received(config), computed_clock=datetime.now)
    path = next((recorder.directory / 'snapshots').glob('*.json'))
    record = json.loads(path.read_bytes())
    record['closed_bars'][0]['values'][3] += 1
    path.write_bytes(canonical(record))
    with pytest.raises(IntegrityError, match='ARCHIVE_CONTENT_INVALID'):
        evidence.audit(root, date(2022, 1, 3))


def test_preview_and_errors_redacted(monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    def fail(*args: Any) -> dict[str, Any]:
        raise RuntimeError('PRIVATE_PRICES_AND_TOKEN')
    monkeypatch.setattr(evidence, 'audit', fail)
    assert evidence.main(['--root', 'unused']) == 0
    assert json.loads(capsys.readouterr().out)['writes'] == 0
    assert evidence.main(['--root', 'unused', '--session-date', '2022-01-03', '--confirm-read']) == 2
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output and json.loads(output)['status'] == 'BLOCKED'
