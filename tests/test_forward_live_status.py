"""Synthetic metadata fixtures only; no installed capture or real session reads."""
from datetime import date, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

import forward_live_status as status

DAY = date(2026, 10, 19)
NOW = datetime.fromisoformat('2026-10-19T12:00:30+05:30')


def roots(tmp_path: Path) -> tuple[Path, Path]:
    left, right = tmp_path / 'capture', tmp_path / 'ops'
    left.mkdir()
    right.mkdir()
    return left, right


def receipt(root: Path, n: Any = 2) -> Path:
    directory = root / str(DAY) / 'state/versioned-v1/receipts'
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / ('receipt-'+'a'*32+'.json')
    file.write_text(json.dumps(dict(format='forward-versioned-manifest-v1', status='REMOTE_VERIFIED',
        recorded_decisions=n, sha256='a'*64, spec_hash='b'*64,
        training_eligible=False, approval_authority=False)), encoding='utf-8')
    return file


def test_counts_not_slot_proof_no_journal_or_inputs(tmp_path: Path) -> None:
    root, ops = roots(tmp_path)
    receipt(root)
    poison = root / str(DAY) / 'state/versioned-v1/journal.sqlite'
    poison.write_bytes(b'NOT_SQLITE_PRIVATE_MUST_NOT_OPEN')
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    value = status.observe(root, ops, DAY, NOW)
    assert value['scheduled_slots_elapsed'] == 33
    assert value['slots_due_after_90s_reporting_grace'] == 32
    assert value['future_slots'] == 42
    assert value['highest_unbound_receipt_decision_count'] == 2
    assert value['elapsed_missing_count'] == 'NOT_ESTABLISHED'
    assert value['missing_slots'].startswith('NOT_ESTABLISHED')
    assert value['remote_custody_verified'] is False
    assert before == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert b'NOT_SQLITE' not in json.dumps(value).encode()


@pytest.mark.parametrize('at,elapsed,due', [
    ('09:19:59', 0, 0), ('09:20:30', 1, 0), ('09:21:59', 1, 0),
    ('09:22:00', 1, 1), ('12:00:00', 32, 32), ('15:30:30', 75, 74), ('16:00:00', 75, 75)])
def test_elapsed_vs_grace_never_changes_capture_window(tmp_path: Path, at: str, elapsed: int, due: int) -> None:
    root, ops = roots(tmp_path)
    value = status.observe(root, ops, DAY, datetime.fromisoformat('2026-10-19T'+at+'+05:30'))
    assert value['scheduled_slots_elapsed'] == elapsed
    assert value['slots_due_after_90s_reporting_grace'] == due
    assert value['retry_allowed'] is False


@pytest.mark.parametrize('n', [True, -1, 76, '2', 1.0, None])
def test_bad_count_not_promoted(tmp_path: Path, n: Any) -> None:
    root, ops = roots(tmp_path)
    receipt(root, n)
    result = status.observe(root, ops, DAY, NOW)
    assert result['invalid_metadata'] == 1
    assert result['highest_unbound_receipt_decision_count'] is None


def test_reports_redacted_inflight_duplicate_and_foreign_ignored(tmp_path: Path) -> None:
    root, ops = roots(tmp_path)
    (ops / (str(DAY)+'-'+'a'*32+'.json')).write_text('{', encoding='utf8')
    (ops / (str(DAY)+'-'+'b'*32+'.json')).write_text('{"x":1,"x":2}', encoding='utf8')
    (ops / (str(DAY)+'-'+'c'*32+'.json')).write_text(json.dumps(dict(
        session_date=str(DAY), observed_at=NOW.isoformat(), status='BLOCKED',
        code='PRIVATE_TOKEN_SECRET /private/path', raw_error='PRIVATE')), encoding='utf8')
    (ops / 'config.json').write_text('SECRET_DO_NOT_READ', encoding='utf8')
    result = status.observe(root, ops, DAY, NOW)
    assert result['incomplete_metadata'] == 2
    assert result['blocked_codes'] == {'OTHER_REDACTED': 1}
    assert 'PRIVATE' not in json.dumps(result) and 'SECRET' not in json.dumps(result)


@pytest.mark.parametrize('change', [{'exit_code': True}, {'retries': True}, {'clock_problem': 'FAIL'},
    {'receipt_written': False}, {'missing_decisions': True}, {'approval_authority': True},
    {'training_eligible': True}, {'code':'AUTH_REQUIRED'}, {'capture_status':'FAKE'},
    {'decision_recorded_this_poll':False}])
def test_success_needs_terminal_contract(tmp_path: Path, change: dict[str, Any]) -> None:
    root, ops = roots(tmp_path)
    report = dict(session_date=str(DAY), observed_at=NOW.isoformat(), status='POLL_REMOTE_VERIFIED',
        code='REMOTE_VERIFICATION_COMPLETE',stage='LOCAL_RECEIPT_CONFIRMED',category='NONE',
        capture_status='VERSIONED_OBSERVATION_RECORDED',decision_recorded_this_poll=True,
        approval_authority=False,training_eligible=False,
        recorded_decisions=2, missing_decisions=73, exit_code=0, retries=0, clock_problem='PASS',
        local_poll_committed=True, receipt_written=True, remote_verified=True)
    report.update(change)
    (ops / (str(DAY)+'-'+'a'*32+'.json')).write_text(json.dumps(report), encoding='utf8')
    result = status.observe(root, ops, DAY, NOW)
    assert result['successful_process_reports'] == 0 and result['invalid_metadata'] == 1


def test_unbound_75_claim_cannot_zero_missing_or_prove_any_slot(tmp_path: Path) -> None:
    root, ops = roots(tmp_path)
    receipt(root, 75)
    result = status.observe(root, ops, DAY, NOW)
    assert result['receipt_session_binding_verified'] is False
    assert result['elapsed_missing_count'] == 'NOT_ESTABLISHED'
    assert result['successful_process_reports'] == 0


def test_replaced_file_detected_before_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, ops = roots(tmp_path)
    path = receipt(root)
    replacement = path.with_name('replacement')
    replacement.write_text('PRIVATE_MUST_NOT_READ',encoding='utf8')
    original = os.open
    def swapped(file: Any, flags: int) -> int:
        os.replace(replacement, path)
        return original(file, flags)
    monkeypatch.setattr(os, 'open', swapped)
    with pytest.raises(status.StatusError, match='FILE_IDENTITY_CHANGED'):
        status.observe(root, ops, DAY, NOW)


def test_file_truncated_after_open_is_incomplete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, ops = roots(tmp_path)
    file = receipt(root)
    original = os.read
    def changed(descriptor: int, size: int) -> bytes:
        file.write_text('{}',encoding='utf8')
        return original(descriptor, size)
    monkeypatch.setattr(os,'read',changed)
    assert status.observe(root, ops, DAY, NOW)['incomplete_metadata'] == 1


def test_short_valid_json_prefix_is_not_complete_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, ops = roots(tmp_path)
    receipt(root)
    fragments = iter([b'{}',b''])
    monkeypatch.setattr(os,'read',lambda descriptor,size:next(fragments))
    result = status.observe(root,ops,DAY,NOW)
    assert result['incomplete_metadata'] == 1 and result['unbound_distinct_manifest_claims'] == 0


def test_bounds_overlap_dates_and_redacted_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    root, ops = roots(tmp_path)
    with pytest.raises(status.StatusError, match='SEPARATE_PRIVATE_ROOTS'):
        status.observe(root, root / 'ops', DAY, NOW)
    with pytest.raises(status.StatusError, match='SAME_DAY'):
        status.observe(root, ops, date(2026, 10, 20), NOW)
    monkeypatch.setattr(status, 'MAX_ENTRIES', 1)
    (ops / 'one').touch()
    (ops / 'two').touch()
    with pytest.raises(status.StatusError, match='ENTRY_BOUND'):
        status.observe(root, ops, DAY, NOW)
    assert status.main(['--root', 'relative', '--ops-root', 'relative2', '--session-date', str(date.today()),
                        '--inspect-read-only']) == 2
    assert 'relative' not in capsys.readouterr().out


def test_preview_has_no_roots_or_host_access() -> None:
    result = subprocess.run([sys.executable, '-B', 'forward_live_status.py', '--root', 'NEVER_READ',
        '--ops-root', 'NEVER_READ', '--session-date', str(DAY)], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['filesystem_reads'] == 0


def test_link_rejected(tmp_path: Path) -> None:
    root, ops = roots(tmp_path)
    link = tmp_path / 'linked'
    try:
        link.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip('Host does not permit synthetic symlink creation')
    with pytest.raises(status.StatusError, match='LINK_PATH'):
        status.observe(link, ops, DAY, NOW)
