"""Deterministic fixtures only. No installed tasks, state, NTP or OS invocation."""
from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import replace
from datetime import date, datetime, timedelta
import io
import json
from pathlib import Path, PureWindowsPath
import subprocess
import sys
from typing import Any, cast
from unittest.mock import patch
import xml.etree.ElementTree as ET

import pytest

import forward_morning_readiness as readiness
from forward_ops_host import exact_action_matches, expected_task_actions
from forward_ops_plan import plans

DAY = date(2026, 10, 15)
SPEC = readiness.ReadinessSpec(DAY, r'C:\Reviewed Code\capture',
    r'C:\Reviewed Code\capture\.venv\Scripts\python.exe', r'C:\Reviewed State\capsule',
    r'C:\Reviewed State\operations')
EARLY = datetime(2026, 10, 15, 9, 29, 59, tzinfo=readiness.IST)


def facts(*, enabled: bool = True) -> dict[str, object]:
    return {identity: {'exists': True, 'action_matches': True, 'enabled': enabled,
        'disabled': not enabled, 'running': False, 'state': 'Ready' if enabled else 'Disabled',
        'last_result': 0} for identity in SPEC.task_names}


def actions() -> dict[str, dict[str, str]]:
    poll, audit = SPEC.task_names
    return expected_task_actions(DAY, poll, audit, code=SPEC.code_directory,
        python=SPEC.python_executable, root=SPEC.state_root, ops=SPEC.ops_root, system_root=r'C:\Windows')


def test_exact_helper_matches_existing_plan_both_actions() -> None:
    ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    expected = actions()
    xmls = plans(DAY, sid='S-1-5-21-1', code=SPEC.code_directory,
        python=SPEC.python_executable, state=SPEC.state_root, ops=SPEC.ops_root)
    for identity in SPEC.task_names:
        tree = ET.fromstring(xmls[identity])
        action = tree.find('t:Actions/t:Exec', ns)
        assert action is not None
        actual = {'Execute': action.findtext('t:Command', namespaces=ns),
            'Arguments': action.findtext('t:Arguments', namespaces=ns),
            'WorkingDirectory': action.findtext('t:WorkingDirectory', namespaces=ns)}
        assert exact_action_matches(actual, expected[identity])


@pytest.mark.parametrize('field,mutation', [('Execute', 'wrong_executable'),
    ('WorkingDirectory', 'prefix'), ('Arguments', 'root_prefix'), ('Arguments', 'ops_prefix'),
    ('Arguments', 'date'), ('Arguments', 'mode'), ('Arguments', 'wrapper'),
    ('Arguments', 'python'), ('Arguments', 'extra_flags'), ('Arguments', 'missing_flags'),
    ('Arguments', 'reordered')])
def test_action_substring_escape_is_rejected(field: str, mutation: str) -> None:
    identity = SPEC.task_names[0]
    expected = actions()[identity]
    actual = dict(expected)
    if mutation == 'wrong_executable':
        actual[field] = r'C:\Windows\System32\cmd.exe'
    elif mutation == 'prefix':
        actual[field] += '-other'
    elif mutation == 'root_prefix':
        actual[field] = actual[field].replace(SPEC.state_root, SPEC.state_root + '-other')
    elif mutation == 'ops_prefix':
        actual[field] = actual[field].replace(SPEC.ops_root, SPEC.ops_root + '-other')
    elif mutation == 'date':
        actual[field] = actual[field].replace(DAY.isoformat(), '2026-10-16')
    elif mutation == 'mode':
        actual[field] = actual[field].replace('-Mode poll', '-Mode audit')
    elif mutation == 'wrapper':
        actual[field] = actual[field].replace('forward_ops_task.ps1', 'forward_ops_task.ps1.other')
    elif mutation == 'python':
        actual[field] = actual[field].replace('python.exe', 'python.exe.other')
    elif mutation == 'extra_flags':
        actual[field] += ' -Command unsafe'
    elif mutation == 'missing_flags':
        actual[field] = actual[field].replace('-NonInteractive ', '')
    else:
        actual[field] = actual[field].replace('-NoProfile -NonInteractive', '-NonInteractive -NoProfile')
    assert not exact_action_matches(actual, expected)


def test_action_case_and_separator_normalization_only() -> None:
    expected = actions()[SPEC.task_names[0]]
    actual = {k: v.upper().replace('\\', '/') for k, v in expected.items()}
    assert exact_action_matches(actual, expected)
    assert not exact_action_matches({}, expected)
    assert not exact_action_matches(expected, {})


def test_invalid_helper_date_and_names_are_validation_errors() -> None:
    kwargs = {'code': SPEC.code_directory, 'python': SPEC.python_executable,
              'root': SPEC.state_root, 'ops': SPEC.ops_root, 'system_root': r'C:\Windows'}
    with pytest.raises(ValueError, match='IDENTITY_INVALID'):
        expected_task_actions(cast(date, 'invalid'), *SPEC.task_names, **kwargs)
    with pytest.raises(ValueError, match='IDENTITY_INVALID'):
        expected_task_actions(DAY, 'old-poll', 'old-audit', **kwargs)


def test_preview_zero_io_even_with_invalid_paths() -> None:
    def denied(*args: object, **kwargs: object) -> Any:
        raise AssertionError('preview entered I/O')
    output = io.StringIO()
    with patch.object(readiness, 'guided_check', denied), patch.object(readiness, '_prepared', denied), \
            patch.object(readiness, '_inspect', denied), patch.object(Path, 'resolve', denied), \
            patch.object(subprocess, 'run', denied), redirect_stdout(output):
        assert readiness.main(['--session-date', 'not-a-date', '--state-root', 'invalid']) == 0
    value = json.loads(output.getvalue())
    assert value['status'] == 'PREVIEW'
    assert value['missing_capture_count'] is None
    assert not value['action_exact_binding_verified'] and value['network_calls'] == value['waits'] == 0


def test_checked_tasks_are_not_fresh_capsule_or_producer_clock_acceptance() -> None:
    result = readiness.assess_readiness(SPEC, EARLY, 'VERIFIED', facts())
    assert result.status == 'TASK_READINESS_CHECKED_ACCEPTANCE_PENDING'
    assert result.action_exact_binding_verified and result.both_tasks_enabled_verified
    assert result.enable_deadline.endswith('09:30:00+05:30')  # type: ignore[union-attr]
    assert result.next_future_slot.endswith('09:30:00+05:30')  # type: ignore[union-attr]
    assert result.next_expected_task_trigger.endswith('09:30:30+05:30')  # type: ignore[union-attr]
    assert result.supervised_slots == ('2026-10-15T09:20:00+05:30', '2026-10-15T09:25:00+05:30')
    assert result.fresh_capsule_acceptance == 'PENDING'
    assert result.supervised_acceptance == 'NOT_CHECKED'
    assert not result.producer_clock_verified and not result.scheduler_triggers_verified
    assert result.missing_capture_count is None and not result.local_receipt_verified


@pytest.mark.parametrize('offset', [0, 1, 30, 300])
def test_missed_enable_deadline_and_strict_future_slot_no_catchup(offset: int) -> None:
    now = EARLY + timedelta(seconds=1 + offset)
    result = readiness.assess_readiness(SPEC, now, 'VERIFIED', facts(enabled=False))
    assert result.status == 'BLOCKED' and result.enable_deadline_status == 'MISSED_ENABLE_DEADLINE'
    assert result.next_future_slot is not None
    assert datetime.fromisoformat(result.next_future_slot) > now
    assert not result.catchup_allowed


def test_late_enabled_snapshot_cannot_prove_enable_before_deadline() -> None:
    result = readiness.assess_readiness(SPEC, EARLY + timedelta(seconds=1), 'VERIFIED', facts())
    assert result.enable_deadline_status == 'ENABLE_BEFORE_DEADLINE_NOT_ESTABLISHED'
    assert result.status == 'BLOCKED'
    assert result.next_future_slot == '2026-10-15T09:35:00+05:30'


@pytest.mark.parametrize('mode', [0, 1])
def test_both_tasks_required_and_bool_identity_exact(mode: int) -> None:
    value = facts()
    entry = cast(dict[str, object], value[SPEC.task_names[mode]])
    entry['enabled'] = 1
    result = readiness.assess_readiness(SPEC, EARLY, 'VERIFIED', value)
    assert not result.both_tasks_enabled_verified and result.status == 'BLOCKED'
    entry['enabled'] = True
    entry['action_matches'] = False
    result = readiness.assess_readiness(SPEC, EARLY, 'VERIFIED', value)
    assert not result.action_exact_binding_verified and result.status == 'BLOCKED'


def test_running_is_not_idle_and_does_not_falsely_claim_disabled_deadline() -> None:
    value = facts()
    entry = cast(dict[str, object], value[SPEC.task_names[0]])
    entry.update(state='Running', running=True)
    result = readiness.assess_readiness(SPEC, EARLY + timedelta(seconds=2), 'VERIFIED', value)
    assert result.status == 'BLOCKED'
    assert result.enable_deadline_status != 'MISSED_ENABLE_DEADLINE'


def test_missing_tasks_and_last_exit_zero_are_not_readiness() -> None:
    result = readiness.assess_readiness(SPEC, EARLY + timedelta(seconds=2), 'NOT_CHECKED', {})
    assert result.status == 'BLOCKED'
    assert result.enable_deadline_status == 'ENABLE_DEADLINE_STATE_NOT_VERIFIED'
    assert result.prepared_status == 'NOT_CHECKED'
    assert not result.remote_receipt_verified


def test_previous_evening_bounded_next_morning_and_no_future_unattended_wait() -> None:
    now = datetime(2026, 10, 14, 20, tzinfo=readiness.IST)
    result = readiness.assess_readiness(SPEC, now, 'VERIFIED', facts())
    assert result.next_future_slot == '2026-10-15T09:30:00+05:30' and result.waits == 0
    assert readiness.assess_readiness(SPEC, now - timedelta(days=1), 'VERIFIED', facts()).next_future_slot is None
    assert readiness.assess_readiness(SPEC, now + timedelta(days=2), 'VERIFIED', facts()).next_future_slot is None


def test_guided_callbacks_once_and_errors_redacted() -> None:
    events: list[str] = []
    def clock() -> datetime:
        events.append('clock')
        return EARLY
    def prepared(spec: readiness.ReadinessSpec) -> str:
        events.append('prepared')
        raise ValueError('private config')
    def inspect(spec: readiness.ReadinessSpec) -> dict[str, object]:
        events.append('inspect')
        raise RuntimeError('private task')
    result = readiness.guided_check(SPEC, clock=clock, prepared=prepared, inspect=inspect)
    assert events == ['clock', 'prepared', 'inspect', 'clock']
    assert result.status == 'BLOCKED' and 'private' not in str(result)


def test_invalid_and_out_of_bound_date_do_not_read_prepared_or_host() -> None:
    def denied(spec: readiness.ReadinessSpec) -> Any:
        raise AssertionError('read entered')
    result = readiness.guided_check(replace(SPEC, state_root='relative'), clock=lambda: EARLY,
                                    prepared=denied, inspect=denied)
    assert result.status == 'BLOCKED'
    result = readiness.guided_check(SPEC, clock=lambda: EARLY - timedelta(days=3),
                                    prepared=denied, inspect=denied)
    assert result.blockers == ('NO_FUTURE_SLOT_WITHIN_24_HOUR_BOUND',)


def test_inspect_script_exact_binding_leaf_checks_and_optional_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import forward_ops_host as host
    scripts: list[str] = []
    def capture(script: str) -> dict[str, Any]:
        scripts.append(script)
        return {}
    monkeypatch.setattr(host, 'powershell', capture)
    host.inspect_tasks(DAY, *SPEC.task_names)
    script = scripts[-1]
    assert '$expected=@{};' in script and '.ContainsKey($n)' in script
    assert 'IndexOf' not in script and '[String]::Equals' in script
    assert "@('Execute','WorkingDirectory','Arguments')" in script
    assert script.count('Test-Path -LiteralPath') == 3
    assert 'enabled=($t.Settings.Enabled -eq $true)' in script
    assert "-TaskPath '\\'" in script
    for command in ('Enable-ScheduledTask', 'Register-ScheduledTask', 'Start-ScheduledTask', 'w32tm'):
        assert command not in script


@pytest.fixture
def prepared_adapter(monkeypatch: pytest.MonkeyPatch) -> tuple[
        dict[PureWindowsPath, bytes], list[tuple[PureWindowsPath, int]], list[str]]:
    """Simulate Windows path semantics on every host; exercise the real guard.

    PureWindowsPath never performs host filesystem IO. Its three concrete-path
    queries are explicit fixture facts, not mocks of separate()/is_absolute().
    Native temporary-path guard tests remain in test_forward_session_ops.py.
    """
    import forward_revision_evidence as evidence
    import forward_nifty_producer as producer
    import forward_versioned_producer as versioned
    import forward_session_ops as operations
    code = PureWindowsPath(SPEC.code_directory)
    base = PureWindowsPath(SPEC.state_root) / DAY.isoformat()
    payloads = {
        base / 'config.json': json.dumps({'session_open': '2026-10-15T09:15:00+05:30',
                                         'fixture': 'generated-config'}).encode(),
        base / 'state/versioned-v1/recipe.json': json.dumps({'fixture': 'generated-policy'}).encode(),
    }
    reads: list[tuple[PureWindowsPath, int]] = []
    calls: list[str] = []
    monkeypatch.setattr(readiness, '__file__', str(code / 'forward_morning_readiness.py'))
    monkeypatch.setattr(operations, '__file__', str(code / 'forward_session_ops.py'))
    monkeypatch.setattr(sys, 'executable', SPEC.python_executable)
    monkeypatch.setattr(readiness, 'Path', PureWindowsPath)
    monkeypatch.setattr(operations, 'Path', PureWindowsPath)
    monkeypatch.setattr(PureWindowsPath, 'resolve', lambda self: self, raising=False)
    monkeypatch.setattr(PureWindowsPath, 'is_symlink', lambda self: False, raising=False)
    monkeypatch.setattr(PureWindowsPath, 'is_junction', lambda self: False, raising=False)
    def denied(*args: object, **kwargs: object) -> Any:
        raise AssertionError('actual filesystem/host access in prepared fixture')
    monkeypatch.setattr(PureWindowsPath, 'open', denied, raising=False)
    monkeypatch.setattr(PureWindowsPath, 'read_bytes', denied, raising=False)
    monkeypatch.setattr(subprocess, 'run', denied)
    def private_read(path: PureWindowsPath, maximum: int) -> bytes:
        reads.append((path, maximum))
        assert maximum == readiness.PREPARED_BYTES == 65536
        if path not in payloads:
            raise FileNotFoundError('private missing fixture')
        return payloads[path]
    def config_validator(config: dict[str, Any], root: PureWindowsPath) -> str:
        assert root == code
        assert config == json.loads(payloads[base / 'config.json'])
        calls.append('config')
        return 'a' * 64
    def policy_validator(config: dict[str, Any], policy: dict[str, Any], root: PureWindowsPath) -> str:
        assert root == code
        assert config == json.loads(payloads[base / 'config.json'])
        assert policy == json.loads(payloads[base / 'state/versioned-v1/recipe.json'])
        calls.append('policy')
        return 'b' * 64
    monkeypatch.setattr(evidence, 'private_read', private_read)
    monkeypatch.setattr(producer, 'validate_config', config_validator)
    monkeypatch.setattr(versioned, 'validate_recipe', policy_validator)
    return payloads, reads, calls


def test_real_prepared_adapter_exact_two_bounded_paths_and_both_validators(
        prepared_adapter: tuple[dict[PureWindowsPath, bytes], list[tuple[PureWindowsPath, int]], list[str]]) -> None:
    _, reads, calls = prepared_adapter
    assert readiness._prepared(SPEC) == 'VERIFIED'
    base = PureWindowsPath(SPEC.state_root) / DAY.isoformat()
    assert reads == [(base / 'config.json', 65536),
                     (base / 'state/versioned-v1/recipe.json', 65536)]
    assert calls == ['config', 'policy']


@pytest.mark.parametrize('field', ['code_directory', 'python_executable'])
def test_real_prepared_adapter_runtime_bindings_fail_before_bytes(
        prepared_adapter: tuple[dict[PureWindowsPath, bytes], list[tuple[PureWindowsPath, int]], list[str]], field: str) -> None:
    _, reads, calls = prepared_adapter
    wrong = replace(SPEC, **{field: getattr(SPEC, field) + '-other'})
    with pytest.raises(ValueError, match='READINESS_RUNTIME_BINDING_INVALID'):
        readiness._prepared(wrong)
    assert reads == [] and calls == []


@pytest.mark.parametrize('capsule', ['state_in_code', 'ops_in_state', 'same_roots', 'linked_state'])
def test_real_prepared_adapter_separate_capsule_gate_before_bytes(
        prepared_adapter: tuple[dict[PureWindowsPath, bytes], list[tuple[PureWindowsPath, int]], list[str]],
        monkeypatch: pytest.MonkeyPatch, capsule: str) -> None:
    _, reads, calls = prepared_adapter
    spec = SPEC
    if capsule == 'state_in_code':
        spec = replace(SPEC, state_root=str(PureWindowsPath(SPEC.code_directory) / 'state'))
    elif capsule == 'ops_in_state':
        spec = replace(SPEC, ops_root=str(PureWindowsPath(SPEC.state_root) / 'ops'))
    elif capsule == 'same_roots':
        spec = replace(SPEC, ops_root=SPEC.state_root)
    else:
        monkeypatch.setattr(PureWindowsPath, 'is_symlink', lambda self: self == PureWindowsPath(SPEC.state_root))
    with pytest.raises(ValueError, match='SEPARATE_PRIVATE_OPERATIONS_ROOT_REQUIRED'):
        readiness._prepared(spec)
    assert reads == [] and calls == []


@pytest.mark.parametrize('target', ['config', 'policy'])
@pytest.mark.parametrize('damage', ['missing', 'empty', 'truncated', 'duplicate'])
def test_real_prepared_source_failures_are_redacted_in_guided_report(
        prepared_adapter: tuple[dict[PureWindowsPath, bytes], list[tuple[PureWindowsPath, int]], list[str]],
        target: str, damage: str) -> None:
    payloads, reads, calls = prepared_adapter
    base = PureWindowsPath(SPEC.state_root) / DAY.isoformat()
    path = base / ('config.json' if target == 'config' else 'state/versioned-v1/recipe.json')
    if damage == 'missing':
        del payloads[path]
    else:
        payloads[path] = {'empty': b'', 'truncated': b'{"private":',
                          'duplicate': b'{"private":1,"private":2}'}[damage]
    result = readiness.guided_check(SPEC, clock=lambda: EARLY, prepared=readiness._prepared,
                                    inspect=lambda spec: facts())
    assert result.status == 'BLOCKED' and result.prepared_status == 'BLOCKED'
    assert 'PREPARED_READ_ONLY_CHECK_UNAVAILABLE' in result.blockers
    assert 'private' not in str(result) and SPEC.state_root not in str(result)
    assert calls == []
    assert len(reads) == (1 if target == 'config' else 2)


def test_real_prepared_adapter_wrong_session_date_and_redaction(
        prepared_adapter: tuple[dict[PureWindowsPath, bytes], list[tuple[PureWindowsPath, int]], list[str]]) -> None:
    payloads, _, calls = prepared_adapter
    path = PureWindowsPath(SPEC.state_root) / DAY.isoformat() / 'config.json'
    payloads[path] = json.dumps({'session_open': '2026-10-16T09:15:00+05:30',
                                'fixture': 'generated-config'}).encode()
    with pytest.raises(ValueError, match='READINESS_PREPARED_DATE_INVALID'):
        readiness._prepared(SPEC)
    assert calls == ['config', 'policy']
    result = readiness.guided_check(SPEC, clock=lambda: EARLY, prepared=readiness._prepared,
                                    inspect=lambda spec: facts())
    assert result.status == 'BLOCKED' and result.prepared_status == 'BLOCKED'


@pytest.mark.parametrize('target', ['config', 'policy'])
@pytest.mark.parametrize('error_type', [ValueError, RuntimeError])
def test_real_prepared_validator_exception_is_redacted(
        prepared_adapter: tuple[dict[PureWindowsPath, bytes], list[tuple[PureWindowsPath, int]], list[str]],
        monkeypatch: pytest.MonkeyPatch, target: str, error_type: type[Exception]) -> None:
    import forward_nifty_producer as producer
    import forward_versioned_producer as versioned
    _, reads, calls = prepared_adapter
    def failed(*args: object) -> str:
        raise error_type('private validator detail')
    monkeypatch.setattr(producer if target == 'config' else versioned,
                        'validate_config' if target == 'config' else 'validate_recipe', failed)
    result = readiness.guided_check(SPEC, clock=lambda: EARLY, prepared=readiness._prepared,
                                    inspect=lambda spec: facts())
    assert result.status == 'BLOCKED' and 'private' not in str(result)
    assert 'PREPARED_READ_ONLY_CHECK_UNAVAILABLE' in result.blockers
    assert len(reads) == 2
    assert calls == ([] if target == 'config' else ['config'])


def test_guided_clock_refresh_crosses_deadline_and_skips_past_slot() -> None:
    times = iter((EARLY, EARLY + timedelta(seconds=11)))
    result = readiness.guided_check(SPEC, clock=lambda: next(times), prepared=lambda spec: 'VERIFIED',
                                    inspect=lambda spec: facts(enabled=False))
    assert result.status == 'BLOCKED'
    assert result.enable_deadline_status == 'MISSED_ENABLE_DEADLINE'
    assert result.next_future_slot == '2026-10-15T09:35:00+05:30'
    assert result.next_expected_task_trigger == '2026-10-15T09:35:30+05:30'


def test_guided_clock_refresh_cannot_prove_late_enable_met_deadline() -> None:
    times = iter((EARLY, EARLY + timedelta(seconds=11)))
    result = readiness.guided_check(SPEC, clock=lambda: next(times), prepared=lambda spec: 'VERIFIED',
                                    inspect=lambda spec: facts())
    assert result.status == 'BLOCKED'
    assert result.enable_deadline_status == 'ENABLE_BEFORE_DEADLINE_NOT_ESTABLISHED'
    assert result.next_future_slot == '2026-10-15T09:35:00+05:30'


def test_guided_backwards_clock_is_blocked() -> None:
    times = iter((EARLY, EARLY - timedelta(seconds=1)))
    result = readiness.guided_check(SPEC, clock=lambda: next(times), prepared=lambda spec: 'VERIFIED',
                                    inspect=lambda spec: facts())
    assert result.status == 'BLOCKED'
    assert result.blockers == ('READINESS_CLOCK_MOVED_BACKWARDS',)
    assert result.next_future_slot is None


@pytest.mark.parametrize('failure', ['exception', 'naive'])
def test_guided_refresh_failure_is_redacted_and_no_stale_readiness(failure: str) -> None:
    calls = 0
    def clock() -> datetime:
        nonlocal calls
        calls += 1
        if calls == 1:
            return EARLY
        if failure == 'exception':
            raise ValueError('private clock detail')
        return EARLY.replace(tzinfo=None)
    result = readiness.guided_check(SPEC, clock=clock, prepared=lambda spec: 'VERIFIED',
                                    inspect=lambda spec: facts())
    assert calls == 2
    assert result.status == 'BLOCKED'
    assert result.blockers == ('READINESS_CLOCK_REFRESH_UNAVAILABLE',)
    assert not result.both_tasks_enabled_verified and result.next_future_slot is None
    assert 'private' not in str(result)
