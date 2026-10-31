"""Synthetic fault injection only; never consult native state or transport."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import socket
from threading import Barrier, Lock

import pytest

import equity_request_campaign as campaign
import test_equity_request_campaign as original_tests
from test_equity_request_campaign import TOKEN, ready, response


SUCCESS = 'CAMPAIGN_STAGE_RETAINED_NOT_DATA_ADMISSION'
BLOCKED = (campaign.StageBlocked, campaign.acq.StudyBlocked,
           FileNotFoundError, json.JSONDecodeError)


@pytest.fixture
def context(tmp_path, monkeypatch):
    return original_tests.context.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def synthetic_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Real network or hidden credential input is forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(campaign.acq.getpass, 'getpass', forbidden)
    # These tests exercise state transitions, not workstation package installation.
    monkeypatch.setattr(campaign.acq, '_runtime_profile', lambda: {
        'pandas': '2.3.3', 'numpy': '2.4.6', 'pyarrow': '24.0.0',
        'certifi': '2026.10.23'})


def load(path):
    return json.loads(path.read_bytes())


def save(path, value):
    raw = campaign.old._canonical(value)
    path.write_bytes(raw)
    return {'name': path.name, 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


def completed(context):
    ctx, prepared, ack = ready(context)
    result = campaign.execute(ctx, 1, ack, token_reader=lambda: TOKEN, fetch=response)
    assert result['status'] == SUCCESS
    return ctx, ctx.state / 'stage-01'


def later(context, allowance=2):
    ctx, _ = completed(context)
    prepared = campaign.prepare(ctx, context[1], allowance, confirm_history=True)
    return ctx, campaign.ACK_PREFIX + prepared['binding_sha256']


def assert_no_continuation(context, number, ack):
    ctx, roots = context
    before = {str(p): p.read_bytes() for p in ctx.state.rglob('*') if p.is_file()}
    directories = {str(p) for p in ctx.state.rglob('*') if p.is_dir()}
    with pytest.raises(BLOCKED):
        campaign.prepare(ctx, roots, 1, confirm_history=True)
    with pytest.raises(BLOCKED):
        campaign.execute(ctx, number, ack,
                         token_reader=lambda: pytest.fail('retry prompt'),
                         fetch=lambda *args: pytest.fail('retry dispatch'))
    after = {str(p): p.read_bytes() for p in ctx.state.rglob('*') if p.is_file()}
    assert after == before  # Review must not manufacture a marker or repair evidence.
    assert directories == {str(p) for p in ctx.state.rglob('*') if p.is_dir()}


@pytest.mark.parametrize('mutation', [
    'delete-binding', 'edit-binding', 'binding-digest', 'execution-commit',
    'source', 'credentials', 'user-agent', 'runtime',
])
def test_historical_binding_and_reservation_tampering(context, mutation):
    ctx, claim = completed(context)
    reservation = load(claim / 'reservation.json')
    result = load(claim / 'result.json')
    binding = campaign._binding_path(ctx, 1)
    if mutation == 'delete-binding':
        binding.unlink()
    elif mutation == 'edit-binding':
        value = load(binding)
        value['approval_granted'] = True
        save(binding, value)
    elif mutation == 'binding-digest':
        reservation['binding_sha256'] = '0' * 64
    elif mutation == 'execution-commit':
        reservation['execution_commit'] = 'b' * 40
    elif mutation == 'source':
        reservation['source_sha256'][campaign.NAME] = '0' * 64
    elif mutation == 'credentials':
        reservation['credentials_saved'] = True
    elif mutation == 'user-agent':
        reservation['user_agent'] = 'changed-synthetic-agent'
    else:
        reservation['runtime_versions']['numpy'] = '0.0'
    result['reservation_sha256'] = save(claim / 'reservation.json', reservation)['sha256']
    save(claim / 'result.json', result)
    with pytest.raises(BLOCKED):
        campaign.prepare(ctx, context[1], 1, confirm_history=True)
    assert not campaign._binding_path(ctx, 2).exists()


def test_new_commit_uses_exact_historical_binding_without_resetting_prefix(context, monkeypatch):
    ctx, claim = completed(context)
    old_binding = campaign._binding_path(ctx, 1)
    original_bytes = (claim / campaign.acq.windows()[0].filename).read_bytes()
    new_ctx = campaign.Context(ctx.local, ctx.source, 'b' * 40)
    original_git = campaign.old._git
    def git(root, *args):
        if args == ('rev-parse', 'HEAD'):
            return new_ctx.reviewed_commit
        return original_git(root, *args)
    monkeypatch.setattr(campaign.old, '_git', git)
    prepared = campaign.prepare(new_ctx, context[1], 1, confirm_history=True)
    assert prepared['stage_number'] == 2 and prepared['prior_consumed_requests'] == 4
    calls = []
    def fetch(window, value):
        calls.append(window.ordinal)
        return response(window, value)
    result = campaign.execute(new_ctx, 2, campaign.ACK_PREFIX + prepared['binding_sha256'],
                              token_reader=lambda: TOKEN, fetch=fetch)
    assert result['status'] == SUCCESS and calls == [2]
    assert old_binding.exists() and not campaign._binding_path(new_ctx, 1).exists()
    assert (claim / campaign.acq.windows()[0].filename).read_bytes() == original_bytes


@pytest.mark.parametrize('mutation', ['rows', 'first-date', 'last-date', 'decoded',
                                      'coverage-json', 'coverage-html'])
def test_self_consistent_artifact_hashes_do_not_replace_reconstruction(context, mutation):
    ctx, claim = completed(context)
    result = load(claim / 'result.json')
    item = result['retained'][0]
    if mutation == 'rows':
        item['rows'] = 2
    elif mutation == 'first-date':
        item['first_date'] = '2022-01-02'
    elif mutation == 'last-date':
        item['last_date'] = '2022-01-04'
    elif mutation == 'decoded':
        path = claim / item['decoded']['name']
        value = load(path)
        value['rows'][0]['close'] = '106'
        item['decoded'] = save(path, value)
    elif mutation == 'coverage-json':
        value = load(claim / 'coverage.json')
        value['rows'] = 42
        result['reports'][0] = save(claim / 'coverage.json', value)
    else:
        path = claim / 'coverage.html'
        raw = path.read_bytes() + b'<p>fabricated coverage</p>'
        path.write_bytes(raw)
        result['reports'][1] = {'name': path.name, 'bytes': len(raw),
                                'sha256': hashlib.sha256(raw).hexdigest()}
    save(claim / 'result.json', result)
    with pytest.raises(BLOCKED):
        campaign.prepare(ctx, context[1], 1, confirm_history=True)


def mutate_live(ctx, roots, number, mutation):
    if mutation == 'history':
        path = roots[0] / 'failure.json'
        value = load(path)
        value['synthetic_change'] = True  # Still semantically valid, different bytes.
        save(path, value)
    elif mutation == 'binding':
        path = campaign._binding_path(ctx, number)
        path.write_bytes(path.read_bytes() + b'\n')
    elif mutation == 'reservation':
        path = ctx.state / f'stage-{number:02d}' / 'reservation.json'
        path.write_bytes(path.read_bytes() + b'\n')
    elif mutation == 'genesis':
        path = ctx.state / 'campaign-history.json'
        value = load(path)
        value['history']['consumed_requests'] += 1
        save(path, value)
    else:
        path = ctx.state / 'stage-01' / campaign.acq.windows()[0].filename
        path.write_bytes(b'CORRUPTED_SYNTHETIC_ORIGINAL')


@pytest.mark.parametrize('number,mutation', [
    (number, mutation) for number in (1, 2)
    for mutation in ('history', 'binding', 'reservation', 'genesis', 'prior-original')
    if number != 1 or mutation != 'prior-original'
])
def test_hidden_prompt_mutation_prevents_first_dispatch(context, number, mutation):
    if number == 1:
        ctx, _, ack = ready(context)
    else:
        ctx, ack = later(context)
    calls = []
    def token():
        mutate_live(ctx, context[1], number, mutation)
        return TOKEN
    def fetch(window, value):
        calls.append(window.ordinal)
        return response(window, value)
    result = campaign.execute(ctx, number, ack, token_reader=token, fetch=fetch)
    assert calls == []
    assert result['status'] != SUCCESS and result['request_attempts'] == 0
    assert result['reservation_held'] is True and result['retry_authorised'] is False


@pytest.mark.parametrize('mutation', ['history', 'binding', 'reservation', 'genesis', 'prior-original'])
def test_pause_mutation_prevents_next_dispatch(context, mutation):
    ctx, ack = later(context)
    calls, pauses = [], []
    def fetch(window, value):
        calls.append(window.ordinal)
        return response(window, value)
    def pause(_):
        pauses.append(1)
        mutate_live(ctx, context[1], 2, mutation)
    result = campaign.execute(ctx, 2, ack, token_reader=lambda: TOKEN, fetch=fetch, pause=pause)
    assert calls == [2] and pauses == [1]
    assert result['status'] != SUCCESS and result['request_attempts'] == 1
    assert (ctx.state / 'stage-02' / campaign.acq.windows()[1].filename).exists()
    assert not (ctx.state / 'stage-02/003-intent.json').exists()
    assert_no_continuation(context, 2, ack)


class SimulatedProcessDeath(BaseException):
    """Bypass normal failure recording, like termination between durable steps."""


@pytest.mark.parametrize('name', [
    'campaign-history.json', 'reservation.json', '001-intent.json',
    '001-RELIANCE-2022.json', '001-decoded.json', 'coverage.json',
    'coverage.html', 'result.json',
])
@pytest.mark.parametrize('boundary', ['before', 'partial', 'write-then-raise', 'death-after-write'])
def test_crash_write_boundaries_never_resume_or_discard_bytes(context, monkeypatch, name, boundary):
    ctx, _, ack = ready(context)
    real_write = campaign.acq._write
    calls, prompts, fired = [], [], []
    def broken(root, output_name, raw):
        if output_name != name:
            return real_write(root, output_name, raw)
        fired.append(1)
        if boundary == 'partial':
            (root / output_name).write_bytes(raw[:max(1, len(raw) // 2)])
        elif boundary in ('write-then-raise', 'death-after-write'):
            real_write(root, output_name, raw)
        if boundary == 'death-after-write':
            raise SimulatedProcessDeath()
        raise OSError('SYNTHETIC_FAULT')
    def token():
        prompts.append(1)
        return TOKEN
    def fetch(window, value):
        calls.append(window.ordinal)
        return response(window, value)
    with monkeypatch.context() as patch:
        patch.setattr(campaign.acq, '_write', broken)
        try:
            result = campaign.execute(ctx, 1, ack, token_reader=token, fetch=fetch)
        except (OSError, SimulatedProcessDeath):
            pass
        else:
            assert result['status'] != SUCCESS
    assert fired == [1]
    pre_dispatch = name in ('campaign-history.json', 'reservation.json', '001-intent.json')
    assert calls == ([] if pre_dispatch else [1])
    assert len(prompts) == (0 if name in ('campaign-history.json', 'reservation.json') else 1)
    target = (ctx.state if name == 'campaign-history.json' else ctx.state / 'stage-01') / name
    assert target.exists() is (boundary != 'before')
    assert not (ctx.state / 'stage-01/complete').exists()
    assert_no_continuation(context, 1, ack)


@pytest.mark.parametrize('after_mkdir', [False, True])
@pytest.mark.parametrize('failure_write_fails', [False, True])
def test_complete_marker_error_acknowledges_only_verified_local_commit(
    context, monkeypatch, after_mkdir, failure_write_fails,
):
    ctx, _, ack = ready(context)
    real_mkdir, real_write = Path.mkdir, campaign.acq._write
    calls, failure_writes = [], []
    def mkdir(path, *args, **kwargs):
        if path == ctx.state / 'stage-01/complete':
            if after_mkdir:
                real_mkdir(path, *args, **kwargs)
            raise OSError('SYNTHETIC_MARKER_FAULT')
        return real_mkdir(path, *args, **kwargs)
    def write(root, name, raw):
        if name == 'failure.json':
            failure_writes.append(1)
            if failure_write_fails:
                raise OSError('SYNTHETIC_FAILURE_EVIDENCE_FAULT')
        return real_write(root, name, raw)
    def fetch(window, value):
        calls.append(window.ordinal)
        return response(window, value)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'mkdir', mkdir)
        patch.setattr(campaign.acq, '_write', write)
        result = campaign.execute(ctx, 1, ack, token_reader=lambda: TOKEN, fetch=fetch)
    assert (ctx.state / 'stage-01/result.json').is_file()
    assert calls == [1]
    if after_mkdir:
        assert result['status'] == SUCCESS
        assert load(ctx.state / 'stage-01/result.json') == result
        assert failure_writes == [] and not (ctx.state / 'stage-01/failure.json').exists()
        with pytest.raises(BLOCKED):
            campaign.execute(ctx, 1, ack, token_reader=lambda: pytest.fail('repeat prompt'),
                             fetch=lambda *args: pytest.fail('repeat dispatch'))
        # Preparing the next binding is inert; it grants no automatic next GET.
        prepared = campaign.prepare(ctx, context[1], 1, confirm_history=True)
        assert prepared['stage_number'] == 2 and calls == [1]
        assert not (ctx.state / 'stage-02').exists()
    else:
        assert result['status'] != SUCCESS and failure_writes == [1]
        assert not (ctx.state / 'stage-01/complete').exists()
        assert_no_continuation(context, 1, ack)


def test_process_death_after_complete_preserves_local_commit_without_automatic_get(context, monkeypatch):
    ctx, _, ack = ready(context)
    real_mkdir = Path.mkdir
    calls = []
    def mkdir(path, *args, **kwargs):
        value = real_mkdir(path, *args, **kwargs)
        if path == ctx.state / 'stage-01/complete':
            raise SimulatedProcessDeath()
        return value
    def fetch(window, value):
        calls.append(window.ordinal)
        return response(window, value)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'mkdir', mkdir)
        with pytest.raises(SimulatedProcessDeath):
            campaign.execute(ctx, 1, ack, token_reader=lambda: TOKEN, fetch=fetch)
    assert calls == [1] and (ctx.state / 'stage-01/complete').is_dir()
    assert not (ctx.state / 'stage-01/failure.json').exists()
    before = {str(p): p.read_bytes() for p in ctx.state.rglob('*') if p.is_file()}
    with pytest.raises(BLOCKED):
        campaign.execute(ctx, 1, ack, token_reader=lambda: pytest.fail('repeat prompt'),
                         fetch=lambda *args: pytest.fail('repeat GET'))
    with pytest.raises(BLOCKED):
        campaign.execute(ctx, 2, campaign.ACK_PREFIX + '0' * 64,
                         token_reader=lambda: pytest.fail('unapproved prompt'),
                         fetch=lambda *args: pytest.fail('unapproved GET'))
    prepared = campaign.prepare(ctx, context[1], 1, confirm_history=True)
    assert prepared['stage_number'] == 2 and prepared['approval_granted'] is False
    assert calls == [1] and not (ctx.state / 'stage-02').exists()
    assert before == {str(p): p.read_bytes() for p in ctx.state.rglob('*') if p.is_file()}


@pytest.mark.parametrize('damage', ['nonempty', 'result-bytes', 'readback-error',
                                   'preexisting-marker', 'failure-marker'])
def test_uncertain_marker_requires_clean_readback_and_no_preexisting_commit(context, monkeypatch, damage):
    ctx, _, ack = ready(context)
    claim = ctx.state / 'stage-01'
    real_mkdir, real_read = Path.mkdir, campaign.old._read
    published = []
    def token():
        if damage == 'preexisting-marker':
            (claim / 'complete').mkdir()
        return TOKEN
    def mkdir(path, *args, **kwargs):
        if path != claim / 'complete' or damage == 'preexisting-marker':
            return real_mkdir(path, *args, **kwargs)
        real_mkdir(path, *args, **kwargs)
        published.append(1)
        if damage == 'nonempty':
            (path / 'unexpected').write_bytes(b'SYNTHETIC')
        elif damage == 'result-bytes':
            result_path = claim / 'result.json'
            result_path.write_bytes(result_path.read_bytes() + b'\n')
        elif damage == 'failure-marker':
            (claim / 'failure.json').write_bytes(b'{}')
        raise OSError('SYNTHETIC_UNCERTAIN_PUBLICATION')
    def read(path, *args, **kwargs):
        if damage == 'readback-error' and published and path == claim / 'result.json':
            raise OSError('SYNTHETIC_READBACK_ERROR')
        return real_read(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'mkdir', mkdir)
        patch.setattr(campaign.old, '_read', read)
        result = campaign.execute(ctx, 1, ack, token_reader=token, fetch=response)
    assert result['status'] != SUCCESS
    assert_no_continuation(context, 1, ack)


@pytest.mark.parametrize('number', [1, 2])
def test_barrier_competing_executions_have_one_claim_prompt_and_dispatch(context, monkeypatch, number):
    if number == 1:
        ctx, _, ack = ready(context)
        gate_path = ctx.state
    else:
        ctx, ack = later(context, allowance=1)
        gate_path = ctx.state / 'stage-02'
    gate, lock = Barrier(2), Lock()
    real_mkdir = Path.mkdir
    counts = []
    def mkdir(path, *args, **kwargs):
        if path == gate_path:
            gate.wait(timeout=15)
        return real_mkdir(path, *args, **kwargs)
    def token():
        with lock:
            counts.append('prompt')
        return TOKEN
    def fetch(window, value):
        with lock:
            counts.append(window.ordinal)
        return response(window, value)
    def run():
        try:
            return campaign.execute(ctx, number, ack, token_reader=token, fetch=fetch)['status']
        except BLOCKED:
            return 'BLOCKED'
    monkeypatch.setattr(Path, 'mkdir', mkdir)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert results.count(SUCCESS) == 1 and results.count('BLOCKED') == 1
    assert counts.count('prompt') == counts.count(number) == 1


def test_history_order_and_safe_alternate_spelling_are_invariant(context):
    ctx, roots = context
    expected = campaign._history(ctx, roots)
    assert campaign._history(ctx, list(reversed(roots))) == expected
    alternate = [Path(root.as_posix() + '/.') for root in roots]
    assert campaign._history(ctx, alternate) == expected
    if campaign.old.os.name == 'nt':
        assert campaign._history(ctx, [Path(str(root).swapcase()) for root in roots]) == expected
    ctx, _, ack = ready(context)
    assert campaign.execute(ctx, 1, ack, token_reader=lambda: TOKEN, fetch=response)['status'] == SUCCESS
    prepared = campaign.prepare(ctx, list(reversed(alternate)), 1, confirm_history=True)
    assert prepared['stage_number'] == 2


def test_duplicate_and_traversal_roots_are_rejected_before_binding(context):
    ctx, roots = context
    for values in ([roots[0], Path(roots[0].as_posix() + '/.')],
                   [roots[0] / '..' / roots[0].name, roots[1]]):
        with pytest.raises(campaign.StageBlocked):
            campaign.prepare(ctx, values, 1, confirm_history=True)
        assert not campaign._binding_path(ctx, 1).exists() and not ctx.state.exists()


def test_symlink_history_root_is_rejected_before_resolution(context):
    ctx, roots = context
    alias = ctx.legacy_parent / ('study-' + '3' * 32)
    try:
        alias.symlink_to(roots[0], target_is_directory=True)
    except OSError as exc:
        if getattr(exc, 'winerror', None) == 1314:
            pytest.skip('Windows symlink privilege unavailable')
        raise
    with pytest.raises(campaign.StageBlocked, match='LINKED_PATH_REJECTED'):
        campaign.prepare(ctx, [alias, roots[1]], 1, confirm_history=True)
    assert not campaign._binding_path(ctx, 1).exists() and not ctx.state.exists()


def test_reparse_history_root_is_rejected_even_without_symlink_privilege(context, monkeypatch):
    from types import SimpleNamespace
    ctx, roots = context
    real_lstat = Path.lstat
    def lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if path == roots[0]:
            return SimpleNamespace(st_mode=info.st_mode,
                st_file_attributes=getattr(info, 'st_file_attributes', 0) | 0x400)
        return info
    monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(campaign.StageBlocked, match='LINKED_PATH_REJECTED'):
        campaign.prepare(ctx, roots, 1, confirm_history=True)
    assert not campaign._binding_path(ctx, 1).exists() and not ctx.state.exists()
