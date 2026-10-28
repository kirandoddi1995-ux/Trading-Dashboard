"""Synthetic legacy records and transport only. Never actual credentials/provider."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import equity_staged_request as stage
REAL_GIT = stage._git

COMMIT = 'a' * 40
TOKEN = 'SYNTHETIC_STAGE_ONLY_NOT_REAL'


@pytest.fixture
def context(tmp_path, monkeypatch):
    local = tmp_path / 'local'
    local.mkdir()
    source = Path(__file__).resolve().parents[1]
    ctx = stage.Context(local, source, COMMIT)
    def git(root, *args):
        if args == ('rev-parse', 'HEAD'): return COMMIT
        if args == ('symbolic-ref', '--short', 'HEAD'): return 'main'
        if args == ('rev-parse', '--show-toplevel'): return str(source)
        if args == ('ls-files', '-v'): return 'H synthetic.py'
        if args == ('status', '--porcelain', '--untracked-files=all'): return ''
        pytest.fail('unexpected git query')
    monkeypatch.setattr(stage, '_git', git)
    roots = []
    for number in (1, 2):
        root = ctx.legacy_parent / ('study-' + str(number) * 32)
        root.mkdir(parents=True)
        (root / 'intent.json').write_text(json.dumps({'source_sha256': {
            'equity_private_acquire.py': stage.LEGACY_SHA}, 'transport': 'NATIVE_TLS',
            'credentials_saved': False, 'synthetic_attempt': number}))
        (root / 'failure.json').write_text(json.dumps({'status': 'BLOCKED',
            'code': 'PRIVATE_EQUITY_STUDY_STOP_REVIEW', 'stage': 'REQUEST',
            'category': 'STUDY_HTTP_AUTH_REVIEW', 'request_attempts': 1,
            'originals_retained': 0, 'retry_authorised': False, 'raw_error_printed': False}))
        (root / 'request-001-intent.json').write_text(json.dumps(stage.acq.windows()[0]._asdict()))
        roots.append(root)
    return ctx, roots


def body():
    return json.dumps({'status': 'success', 'data': {'candles': [
        ['2022-01-03T00:00:00+05:30', 100, 110, 90, 105, 1000, 0]]}}).encode()


def approved(context):
    ctx, roots = context
    stage.prepare(ctx, COMMIT, roots)
    return ctx


def test_preview_has_no_operational_io(monkeypatch, capsys):
    monkeypatch.setattr(stage, 'native_context', lambda: pytest.fail('native context'))
    monkeypatch.setattr(Path, 'open', lambda *a, **k: pytest.fail('file read'))
    assert stage.main([]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value['network_requests'] == value['credential_reads'] == value['writes'] == 0
    assert value['approval_granted'] is False and value['proposed_aggregate_maximum'] == 3


def test_prepare_is_unapproved_and_leaves_legacy_unchanged(context):
    ctx, roots = context
    before = {str(p): p.read_bytes() for r in roots for p in r.iterdir()}
    result = stage.prepare(ctx, COMMIT, roots)
    assert result['approval_granted'] is False and not ctx.state.exists()
    assert json.loads(ctx.binding.read_text())['aggregate_maximum'] == 3
    assert before == {str(p): p.read_bytes() for r in roots for p in r.iterdir()}
    with pytest.raises(stage.StageBlocked, match='OWNER_BINDING_ALREADY_EXISTS'):
        stage.prepare(ctx, COMMIT, roots)


def test_requester_successor_pin_does_not_admit_an_old_binding(context):
    ctx = approved(context)
    binding = json.loads(ctx.binding.read_text())
    binding['source_sha256']['equity_private_acquire.py'] = (
        '2ed9792fb606f5d77ec0856323b085beda788ecf9abf5c094f885c15d524ac81')
    ctx.binding.write_text(json.dumps(binding))
    with pytest.raises(stage.StageBlocked, match='BINDING_REVIEW_REQUIRED'):
        stage.execute(ctx, stage.ACK,
            token_reader=lambda: pytest.fail('Old binding must not prompt'),
            fetch=lambda *args: pytest.fail('Old binding must not dispatch'))
    assert not ctx.state.exists()


def test_missing_approval_cannot_read_or_reserve(context, monkeypatch):
    ctx, _ = context
    monkeypatch.setattr(stage, '_context', lambda *a: pytest.fail('admission I/O'))
    with pytest.raises(stage.StageBlocked, match='APPROVAL_ACK_REQUIRED'):
        stage.execute(ctx, '')
    assert not ctx.state.exists()


def test_one_success_stops_and_preserves_reusable_exact_original(context):
    ctx = approved(context)
    calls = []
    raw = body()
    def fetch(window, token):
        assert token == TOKEN
        assert ctx.state.is_dir() and (ctx.state / 'reservation.json').is_file()
        calls.append(window)
        return stage.acq.Response(200, raw)
    result = stage.execute(ctx, stage.ACK, token_reader=lambda: TOKEN, fetch=fetch)
    assert len(calls) == 1 and calls[0] == stage.acq.windows()[0]
    assert result['known_aggregate_attempts'] == 3 and result['http_status'] == 200
    assert result['input_origin'] == 'INJECTED_SYNTHETIC'
    assert result['training_eligible'] is result['promotion_authorised'] is False
    assert (ctx.state / calls[0].filename).read_bytes() == raw
    assert result['original']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert TOKEN not in json.dumps(result)
    with pytest.raises(stage.StageBlocked, match='CAMPAIGN_ALREADY_RESERVED'):
        stage.execute(ctx, stage.ACK, token_reader=lambda: pytest.fail('second prompt'), fetch=fetch)
    assert len(calls) == 1


@pytest.mark.parametrize('category,status', [('STUDY_HTTP_401_UNAUTHENTICATED', 401),
    ('STUDY_HTTP_403_FORBIDDEN', 403), ('STUDY_HTTP_REVIEW', None)])
def test_failure_stops_once_preserves_reservation_and_never_retries(context, category, status):
    ctx = approved(context)
    calls = []
    def fetch(window, token):
        calls.append(window)
        raise stage.acq.StudyBlocked(category)
    result = stage.execute(ctx, stage.ACK, token_reader=lambda: TOKEN, fetch=fetch)
    assert len(calls) == 1 and result['http_status'] == status
    assert result['reservation_held'] is True and result['new_request_attempts'] == 1
    assert result['retry_authorised'] is False and ctx.state.exists()
    assert not (ctx.state / 'result.json').exists()
    with pytest.raises(stage.StageBlocked, match='CAMPAIGN_ALREADY_RESERVED'):
        stage.execute(ctx, stage.ACK, token_reader=lambda: pytest.fail('retry'))


def test_credential_abort_keeps_reserved_slot_without_claiming_http_was_sent(context):
    ctx = approved(context)
    def interrupted(): raise KeyboardInterrupt
    result = stage.execute(ctx, stage.ACK, token_reader=interrupted,
                           fetch=lambda *a: pytest.fail('network'))
    assert result['new_request_attempts'] == 0 and result['known_aggregate_attempts'] == 2
    assert result['new_requests_reserved'] == 1 and result['reservation_held'] is True


@pytest.mark.parametrize('mutation', ['boolean-counter', 'larger-budget', 'other-window', 'changed-source'])
def test_edited_binding_cannot_prompt_or_reserve(context, mutation):
    ctx = approved(context)
    value = json.loads(ctx.binding.read_text())
    if mutation == 'boolean-counter': value['new_request_maximum'] = True
    if mutation == 'larger-budget': value['aggregate_maximum'] = 38
    if mutation == 'other-window': value['window']['start'] = '2023-01-01'
    if mutation == 'changed-source': value['source_sha256']['equity_staged_request.py'] = '0' * 64
    ctx.binding.write_text(json.dumps(value))
    with pytest.raises(stage.StageBlocked):
        stage.execute(ctx, stage.ACK, token_reader=lambda: pytest.fail('prompt'))
    assert not ctx.state.exists()


def test_changed_predecessor_blocks_before_new_claim(context):
    ctx = approved(context)
    _, roots = context
    value = json.loads((roots[0] / 'failure.json').read_text())
    value['request_attempts'] = 2
    (roots[0] / 'failure.json').write_text(json.dumps(value))
    with pytest.raises(stage.StageBlocked):
        stage.execute(ctx, stage.ACK, token_reader=lambda: pytest.fail('prompt'))
    assert not ctx.state.exists()


def test_duplicate_predecessor_not_counted_twice(context):
    ctx, roots = context
    with pytest.raises(stage.StageBlocked, match='LEGACY_REVIEW_REQUIRED'):
        stage.prepare(ctx, COMMIT, [roots[0], roots[0]])
    assert not ctx.binding.exists()


def test_partial_claim_write_failure_still_blocks_fresh_invocation(context, monkeypatch):
    ctx = approved(context)
    original = stage.acq._write
    def denied(root, name, raw):
        if name == 'reservation.json': raise OSError('SYNTHETIC_ONLY')
        return original(root, name, raw)
    monkeypatch.setattr(stage.acq, '_write', denied)
    with pytest.raises(OSError):
        stage.execute(ctx, stage.ACK, token_reader=lambda: pytest.fail('prompt'))
    assert ctx.state.is_dir()
    with pytest.raises(stage.StageBlocked, match='CAMPAIGN_ALREADY_RESERVED'):
        stage.execute(ctx, stage.ACK, token_reader=lambda: pytest.fail('prompt'))


def test_concurrent_invocations_have_one_prompt_and_one_dispatch(context):
    ctx = approved(context)
    prompted, dispatched = [], []
    def token(): prompted.append(1); return TOKEN
    def fetch(window, value): dispatched.append(1); return stage.acq.Response(200, body())
    def invoke(_):
        try: return stage.execute(ctx, stage.ACK, token_reader=token, fetch=fetch)['status']
        except stage.StageBlocked: return 'BLOCKED'
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(invoke, range(8)))
    assert results.count('STAGE_ONE_STRUCTURE_PASSED_NOT_DATA_ADMISSION') == 1
    assert len(prompted) == len(dispatched) == 1


def test_native_process_reservation_race_has_exactly_one_winner(tmp_path):
    root = tmp_path / 'fixed-campaign'
    code = ('from pathlib import Path;import sys;from equity_staged_request import reserve,StageBlocked;'
            '\ntry: reserve(Path(sys.argv[1]), b"{}")'
            '\nexcept StageBlocked: sys.exit(2)')
    env = {key: value for key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC',
        'PATHEXT', 'TEMP', 'TMP', 'USERPROFILE') if (value := os.environ.get(key)) is not None}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    processes = [subprocess.Popen([sys.executable, '-B', '-c', code, str(root)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) for _ in range(6)]
    results = [p.communicate(timeout=30) for p in processes]
    assert all(not out and not err for out, err in results)
    assert [p.returncode for p in processes].count(0) == 1
    assert [p.returncode for p in processes].count(2) == 5


def test_unknown_options_and_error_text_are_not_echoed(capsys):
    assert stage.main(['--token', TOKEN]) == 2
    output = capsys.readouterr()
    assert TOKEN not in output.out + output.err


def test_closed_wrong_source_is_rejected(context, monkeypatch):
    ctx, roots = context
    monkeypatch.setattr(stage, '_git', lambda *a: 'WRONG')
    with pytest.raises(stage.StageBlocked, match='SOURCE_REVIEW_REQUIRED'):
        stage.prepare(ctx, COMMIT, roots)
    assert not ctx.binding.exists()


def test_missing_ack_cli_blocks_before_any_native_or_private_read(monkeypatch, capsys):
    monkeypatch.setattr(stage, 'native_context', lambda: pytest.fail('native/private read'))
    assert stage.main(['--mode', 'execute']) == 2
    value = json.loads(capsys.readouterr().out)
    assert value['code'] == 'APPROVAL_ACK_REQUIRED'
    assert value['new_request_attempts'] == 0 and value['reservation_held'] is None


def test_cli_prepare_and_reservation_failure_report_real_held_state(context, monkeypatch, capsys):
    ctx, roots = context
    monkeypatch.setattr(stage, 'native_context', lambda: ctx)
    assert stage.main(['--mode', 'prepare', '--reviewed-commit', COMMIT,
        '--previous-root', str(roots[0]), '--previous-root', str(roots[1])]) == 0
    assert json.loads(capsys.readouterr().out)['approval_granted'] is False
    original = stage.acq._write
    def full_disk(root, name, raw):
        if name == 'reservation.json': raise OSError(TOKEN)
        return original(root, name, raw)
    monkeypatch.setattr(stage.acq, '_write', full_disk)
    assert stage.main(['--mode', 'execute', '--approval-ack', stage.ACK]) == 2
    output = capsys.readouterr()
    assert TOKEN not in output.out + output.err
    value = json.loads(output.out)
    assert value['reservation_held'] is True and value['new_request_attempts'] == 0


@pytest.mark.parametrize('mutate', ['extra-key', 'previous-boolean', 'window-boolean', 'nan'])
def test_more_binding_corruption_is_closed_before_reservation(context, mutate):
    ctx = approved(context)
    value = json.loads(ctx.binding.read_text())
    if mutate == 'extra-key': value['unreviewed'] = TOKEN
    if mutate == 'previous-boolean': value['previous'][0]['consumed_requests'] = True
    if mutate == 'window-boolean': value['window']['ordinal'] = True
    if mutate == 'nan': value['aggregate_maximum'] = float('nan')
    ctx.binding.write_text(json.dumps(value))
    with pytest.raises(stage.StageBlocked):
        stage.execute(ctx, stage.ACK, token_reader=lambda: pytest.fail('prompt'))
    assert not ctx.state.exists()


def test_clock_or_token_exception_text_never_leaks(context):
    ctx = approved(context)
    def failed_reader(): raise ValueError(TOKEN)
    result = stage.execute(ctx, stage.ACK, token_reader=failed_reader,
                           fetch=lambda *a: pytest.fail('network'))
    assert TOKEN not in json.dumps(result)
    assert result['new_request_attempts'] == 0 and result['reservation_held'] is True


def test_invalid_200_body_not_preserved_as_original(context):
    ctx = approved(context)
    result = stage.execute(ctx, stage.ACK, token_reader=lambda: TOKEN,
        fetch=lambda *a: stage.acq.Response(200, b'{"status":"error","secret":"' + TOKEN.encode() + b'"}'))
    assert result['new_request_attempts'] == 1 and result['retry_authorised'] is False
    assert not (ctx.state / stage.acq.windows()[0].filename).exists()
    assert TOKEN not in (ctx.state / 'failure.json').read_text()


def test_git_reads_only_explicit_noncredential_environment_names(context, monkeypatch):
    ctx, _ = context
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP', 'USERPROFILE'}
    class NamedOnly:
        def items(self): pytest.fail('enumerated environment')
        def __iter__(self): pytest.fail('enumerated environment')
        def get(self, key):
            assert key in allowed
            return 'SYNTHETIC_FIXED_ENV'
    observed = {}
    def run(*args, **kwargs):
        observed.update(kwargs['env'])
        return SimpleNamespace(returncode=0, stdout=b'fixed')
    with monkeypatch.context() as patch:
        patch.setattr(stage.os, 'environ', NamedOnly())
        patch.setattr(stage.subprocess, 'run', run)
        assert REAL_GIT(ctx.source, 'rev-parse', 'HEAD') == 'fixed'
    assert set(observed) == allowed | {'GIT_CONFIG_GLOBAL','GIT_CONFIG_SYSTEM',
        'GIT_TERMINAL_PROMPT','GIT_OPTIONAL_LOCKS','GIT_NO_REPLACE_OBJECTS'}


def test_opened_sidecar_identity_checked_before_read(context, monkeypatch):
    ctx = approved(context)
    original = stage.os.fstat
    def changed(fd):
        value = original(fd)
        return SimpleNamespace(st_dev=value.st_dev, st_ino=value.st_ino+1,
            st_size=value.st_size, st_mtime_ns=value.st_mtime_ns, st_ctime_ns=value.st_ctime_ns)
    monkeypatch.setattr(stage.os, 'fstat', changed)
    with pytest.raises(stage.StageBlocked, match='BINDING_REVIEW_REQUIRED'):
        stage._read(ctx.binding)


def test_sidecar_modified_during_read_is_rejected(context, monkeypatch):
    ctx = approved(context)
    original = stage.os.fstat
    calls = []
    def changed(fd):
        value = original(fd)
        calls.append(1)
        return SimpleNamespace(st_dev=value.st_dev, st_ino=value.st_ino,
            st_size=value.st_size, st_mtime_ns=value.st_mtime_ns + (1 if len(calls)>1 else 0),
            st_ctime_ns=value.st_ctime_ns)
    monkeypatch.setattr(stage.os, 'fstat', changed)
    with pytest.raises(stage.StageBlocked, match='BINDING_REVIEW_REQUIRED'):
        stage._read(ctx.binding)


def test_stable_cross_api_ctime_difference_is_not_false_mutation(context, monkeypatch):
    ctx = approved(context)
    original = stage.os.fstat
    def different_semantics(fd):
        value = original(fd)
        return SimpleNamespace(st_dev=value.st_dev, st_ino=value.st_ino,
            st_size=value.st_size, st_mtime_ns=value.st_mtime_ns,
            st_ctime_ns=value.st_ctime_ns + 1000000)
    monkeypatch.setattr(stage.os, 'fstat', different_semantics)
    value, _ = stage._read(ctx.binding)
    assert value['format'] == 'equity-stage-one-binding-v1'


def test_new_source_binding_generation_does_not_reset_campaign_claim(context):
    ctx = approved(context)
    other = stage.Context(ctx.local, ctx.source, 'b' * 40)
    assert ctx.binding != other.binding
    assert ctx.state == other.state  # Commit updates cannot buy another request.
    stage.reserve(ctx.state, b'{}')
    with pytest.raises(stage.StageBlocked, match='CAMPAIGN_ALREADY_RESERVED'):
        stage.execute(other, stage.ACK, token_reader=lambda: pytest.fail('prompt'))
