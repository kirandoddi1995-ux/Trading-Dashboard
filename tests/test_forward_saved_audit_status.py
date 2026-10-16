from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
from typing import Any

import pytest

import forward_saved_audit_status as reader

DAY = date(2026, 10, 16)


def report(n: int = 75) -> dict[str, Any]:
    start = datetime.combine(DAY, time(9, 20), reader.IST)
    return dict(status='VERSIONED_COVERAGE_COMPLETE' if n == 75 else 'VERSIONED_COVERAGE_INCOMPLETE',
                session_date=DAY.isoformat(), observed_at='2026-10-16T10:10:01+00:00',
                raw_polls=n, recorded_decisions=n, missing_decisions=75-n, expected_decisions=75,
                slots=[dict(slot=(start+timedelta(minutes=5*i)).isoformat(),
                            status='OBSERVED_DECISION' if i < n else 'MISSING_NOT_OBSERVED')
                       for i in range(75)], generation_sha256='a'*64, capture_writes=0,
                full_session_cohort_eligible=False, training_eligible=False, approval_authority=False,
                remote_custody_verified=False, backfill_allowed=False,
                coverage_requirement_met=n == 75, operational_cause_per_slot='NOT_ESTABLISHED')


def save(root: Path, item: dict[str, Any], number: int = 0) -> None:
    (root / f'{DAY}-{number:032x}.json').write_text(json.dumps(item), encoding='utf8')


def test_preview_never_inspects(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def fail(*args: object) -> None:
        raise AssertionError('IO attempted')
    monkeypatch.setattr(reader, 'inspect', fail)
    assert reader.main(['--ops-root', 'not-an-absolute-path', '--session-date', str(DAY)]) == 0
    assert json.loads(capsys.readouterr().out)['reads'] == 0


@pytest.mark.parametrize('n', [0, 2, 75])
def test_bounded_projection_does_not_claim_schedule_or_custody(tmp_path: Path, n: int) -> None:
    item = report(n)
    item['private_extra'] = 'NEVER_PRINT_ME'
    save(tmp_path, item)
    result = reader.inspect(tmp_path, DAY)
    assert result['status'] == 'SAVED_AUDIT_REPORT_CLAIMS_VALIDATED'
    assert result['candidates'][0]['recorded_decisions'] == n
    assert result['scheduled_task_origin_verified'] is result['training_eligible'] is False
    assert result['capture_reads'] == result['writes'] == 0
    assert 'NEVER_PRINT_ME' not in json.dumps(result)


@pytest.mark.parametrize('field,value', [
    ('recorded_decisions', True), ('raw_polls', 76), ('expected_decisions', 74),
    ('missing_decisions', 1), ('generation_sha256', 'secret'), ('capture_writes', False),
    ('training_eligible', True), ('approval_authority', True), ('remote_custody_verified', True),
    ('full_session_cohort_eligible', True), ('backfill_allowed', True),
    ('session_date', '2026-10-15'), ('observed_at', '2026-10-16T10:10:00'),
    ('observed_at', '2026-10-16T10:09:59Z'),
    ('status', 'VERSIONED_COVERAGE_INCOMPLETE'), ('coverage_requirement_met', 1),
    ('operational_cause_per_slot', 'INVENTED'), ('slots', []),
])
def test_bad_claims_are_redacted(tmp_path: Path, field: str, value: Any) -> None:
    item = report(); item[field] = value
    save(tmp_path, item)
    # Unrecognised statuses are non-audit reports, not audit candidates.
    result = reader.inspect(tmp_path, DAY)
    assert result['status'] == 'SAVED_AUDIT_REPORT_REVIEW_REQUIRED'
    assert result['candidates'] == []


@pytest.mark.parametrize('mutation', ['duplicate', 'missing', 'naive', 'bad_status', 'wrong_counts'])
def test_slot_integrity(tmp_path: Path, mutation: str) -> None:
    item = report()
    if mutation == 'duplicate': item['slots'][1] = item['slots'][0]
    if mutation == 'missing': item['slots'][0]['slot'] = '2026-10-15T03:50:00Z'
    if mutation == 'naive': item['slots'][0]['slot'] = '2026-10-16T03:50:00'
    if mutation == 'bad_status': item['slots'][0]['status'] = 'INVENTED'
    if mutation == 'wrong_counts': item['slots'][0]['status'] = 'RAW_ONLY_NO_DECISION'
    save(tmp_path, item)
    assert reader.inspect(tmp_path, DAY)['invalid_candidates'] == 1


def test_exact_day_names_only_and_conflicts_not_latest_selected(tmp_path: Path) -> None:
    (tmp_path / 'config.json').write_text('private', encoding='utf8')
    (tmp_path / '2026-10-15-00000000000000000000000000000000.json').write_text('private', encoding='utf8')
    assert reader.inspect(tmp_path, DAY)['status'] == 'SAVED_AUDIT_REPORT_NOT_FOUND'
    save(tmp_path, report(), 0); save(tmp_path, report(2), 1)
    result = reader.inspect(tmp_path, DAY)
    assert result['conflicting_claims'] and result['multiple_candidates']
    assert len(result['candidates']) == 2


def test_duplicate_keys_or_truncated_file_are_not_success(tmp_path: Path) -> None:
    file = tmp_path / f'{DAY}-{"0"*32}.json'
    file.write_text('{"status":1,"status":2}', encoding='utf8')
    result = reader.inspect(tmp_path, DAY)
    assert result['unreadable_or_inflight'] == 1
    assert result['status'] == 'SAVED_AUDIT_REPORT_REVIEW_REQUIRED'


def test_later_day_saved_historical_audit_is_supported(tmp_path: Path) -> None:
    item = report(); item['observed_at'] = '2026-10-17T10:10:00Z'
    save(tmp_path, item)
    assert reader.inspect(tmp_path, DAY)['status'] == 'SAVED_AUDIT_REPORT_CLAIMS_VALIDATED'


def test_same_generation_counts_different_slot_map_is_conflict(tmp_path: Path) -> None:
    first = report(2)
    second = report(2)
    second['slots'][1]['status'] = 'MISSING_NOT_OBSERVED'
    second['slots'][2]['status'] = 'OBSERVED_DECISION'
    save(tmp_path, first, 0); save(tmp_path, second, 1)
    result = reader.inspect(tmp_path, DAY)
    assert result['conflicting_claims'] is True
    assert result['status'] == 'SAVED_AUDIT_REPORT_REVIEW_REQUIRED'


def test_real_coverage_projection_schema_without_journal_or_producer(tmp_path: Path) -> None:
    from forward_session_ops import coverage
    item = report(2)
    bundle = dict(config={'session_open': '2026-10-16T03:45:00+00:00'},
                  polls=[{'source': {'slot': slot['slot']}, 'decision': {'synthetic': True}}
                         for slot in item['slots'][:2]],
                  recorded_decisions=2, missing_decisions=73)
    projected = coverage(bundle)
    projected.update(session_date=DAY.isoformat(), observed_at=item['observed_at'],
                     generation_sha256='a'*64, capture_writes=0)
    save(tmp_path, projected)
    assert reader.inspect(tmp_path, DAY)['candidates'][0]['recorded_decisions'] == 2


def test_confirmed_failure_does_not_print_path_or_exception(capsys: pytest.CaptureFixture[str]) -> None:
    assert reader.main(['--ops-root', 'PRIVATE_RELATIVE', '--session-date', str(DAY), '--confirm-read-only']) == 2
    output = capsys.readouterr().out
    assert 'PRIVATE_RELATIVE' not in output
    assert json.loads(output)['raw_error_printed'] is False
