"""Generated candles, local temp claims and mocked transport; no provider calls."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from threading import Lock

import pytest

import equity_request_campaign as campaign

TOKEN = 'SYNTHETIC_CAMPAIGN_NOT_A_REAL_TOKEN'
COMMIT = 'a' * 40


@pytest.fixture
def context(tmp_path, monkeypatch):
    local = tmp_path / 'local'
    local.mkdir()
    ctx = campaign.Context(local, Path(__file__).resolve().parents[1], COMMIT)
    def git(root, *args):
        values = {('rev-parse', 'HEAD'): COMMIT, ('symbolic-ref', '--short', 'HEAD'): 'main',
            ('rev-parse', '--show-toplevel'): str(ctx.source),
            ('status', '--porcelain', '--untracked-files=all'): '', ('ls-files', '-v'): 'H synthetic.py'}
        return values[args]
    monkeypatch.setattr(campaign.old, '_git', git)
    roots = []
    for n in (1, 2):
        root = ctx.legacy_parent / ('study-' + str(n) * 32)
        root.mkdir(parents=True)
        (root / 'intent.json').write_text(json.dumps({'source_sha256': {
            'equity_private_acquire.py': campaign.old.LEGACY_SHA}, 'transport': 'NATIVE_TLS',
            'credentials_saved': False, 'synthetic_attempt': n}))
        (root / 'failure.json').write_text(json.dumps({'status': 'BLOCKED',
            'code': 'PRIVATE_EQUITY_STUDY_STOP_REVIEW', 'stage': 'REQUEST',
            'category': 'STUDY_HTTP_AUTH_REVIEW', 'request_attempts': 1, 'originals_retained': 0,
            'retry_authorised': False, 'raw_error_printed': False}))
        (root / 'request-001-intent.json').write_text(json.dumps(campaign.acq.windows()[0]._asdict()))
        roots.append(root)
    return ctx, roots


def ready(context, allowance=1):
    ctx, roots = context
    value = campaign.prepare(ctx, roots, allowance, confirm_history=True)
    return ctx, value, campaign.ACK_PREFIX + value['binding_sha256']


def response(window, token):
    assert token == TOKEN
    body = json.dumps({'status': 'success', 'data': {'candles': [
        [window.start[:4] + '-01-03T00:00:00+05:30', 100, 110, 90, 105, 1000, 0]]}}).encode()
    return campaign.acq.Response(200, body)


def test_preview_and_missing_approval_have_zero_operational_io(monkeypatch, capsys):
    monkeypatch.setattr(campaign.old, 'native_context', lambda: pytest.fail('native/private I/O'))
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: pytest.fail('file I/O'))
    assert campaign.main([]) == 0
    assert json.loads(capsys.readouterr().out)['writes'] == 0
    assert campaign.main(['--mode', 'execute']) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'APPROVAL_ACK_REQUIRED'
    assert campaign.main(['--mode', 'prepare']) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'OWNER_HISTORY_ATTESTATION_REQUIRED'


def test_prepare_derives_three_without_rewriting_old_records_or_binding(context):
    ctx, roots = context
    before = {str(p): p.read_bytes() for root in roots for p in root.iterdir()}
    campaign.old._parents(ctx.approval_parent)
    ctx.binding.write_bytes(b'OLD_BINDING_UNTOUCHED')
    prepared = campaign.prepare(ctx, roots, 1, confirm_history=True)
    assert prepared['prior_consumed_requests'] == 3
    assert prepared['stage_cumulative_maximum'] == 4 and prepared['stage_allowance'] == 1
    assert prepared['approval_granted'] is False and not ctx.state.exists()
    assert ctx.binding.read_bytes() == b'OLD_BINDING_UNTOUCHED'
    assert before == {str(p): p.read_bytes() for root in roots for p in root.iterdir()}
    value = json.loads(campaign._binding_path(ctx, 1).read_text())
    assert value['history']['external'][0]['original_retained'] is False
    assert value['history']['consumed_requests'] == 3
    with pytest.raises(campaign.StageBlocked, match='OWNER_BINDING_ALREADY_EXISTS'):
        campaign.prepare(ctx, roots, 1, confirm_history=True)


@pytest.mark.parametrize('allowance', [0, -1, True, 2, 36, 37])
def test_initial_stage_never_widens_beyond_one(context, allowance):
    ctx, roots = context
    with pytest.raises(campaign.StageBlocked):
        campaign.prepare(ctx, roots, allowance, confirm_history=True)
    assert not campaign._binding_path(ctx, 1).exists() and not ctx.state.exists()


def test_one_retained_window_and_automatic_honest_coverage(context):
    ctx, prepared, ack = ready(context)
    binding_path = campaign._binding_path(ctx, 1)
    binding_before = binding_path.read_bytes()
    prompts = []
    def token():
        reservation = json.loads((ctx.state / 'stage-01/reservation.json').read_text())
        assert reservation['binding_sha256'] == prepared['binding_sha256']
        assert reservation['prior_consumed_requests'] == 3
        prompts.append(1)
        return TOKEN
    calls = []
    def fetch(window, value):
        calls.append(window.ordinal)
        return response(window, value)
    result = campaign.execute(ctx, 1, ack, token_reader=token, fetch=fetch)
    assert result['status'] == 'CAMPAIGN_STAGE_RETAINED_NOT_DATA_ADMISSION'
    assert result['request_attempts'] == 1 and result['known_cumulative_attempts'] == 4
    assert calls == prompts == [1]
    assert (ctx.state / 'stage-01/001-RELIANCE-2022.json').read_bytes() == response(campaign.acq.windows()[0], TOKEN).body
    coverage = json.loads((ctx.state / 'stage-01/coverage.json').read_text())
    assert coverage['retained_windows'] == coverage['rows'] == 1
    assert coverage['planned_windows'] == 36 and coverage['exchange_calendar_verified'] is False
    assert coverage['missing_exchange_sessions'].startswith('NOT_ESTABLISHED')
    assert coverage['training_eligible'] is coverage['performance_claim_verified'] is False
    assert coverage['input_origins'] == ['INJECTED_SYNTHETIC_NOT_MARKET_EVIDENCE']
    assert 'no accuracy claim' in (ctx.state / 'stage-01/coverage.html').read_text()
    assert binding_path.read_bytes() == binding_before
    assert all(TOKEN not in p.read_text() for p in (ctx.state / 'stage-01').iterdir() if p.is_file())
    assert (ctx.state / 'stage-01/complete').is_dir()


def test_later_allowance_is_computed_and_never_redownloads_first_window(context):
    ctx, _, ack = ready(context)
    campaign.execute(ctx, 1, ack, token_reader=lambda: TOKEN, fetch=response)
    first = (ctx.state / 'stage-01/001-RELIANCE-2022.json').read_bytes()
    prepared = campaign.prepare(ctx, context[1], 35, confirm_history=True)
    assert prepared['stage_number'] == 2 and prepared['prior_consumed_requests'] == 4
    assert prepared['stage_cumulative_maximum'] == 39 and prepared['stage_allowance'] == 35
    calls = []
    def fetch(window, value):
        calls.append(window.ordinal)
        return response(window, value)
    result = campaign.execute(ctx, 2, campaign.ACK_PREFIX + prepared['binding_sha256'],
        token_reader=lambda: TOKEN, fetch=fetch, pause=lambda _: None)
    assert calls == list(range(2, 37))
    assert result['known_cumulative_attempts'] == 39 and result['retained_windows_total'] == 36
    assert (ctx.state / 'stage-01/001-RELIANCE-2022.json').read_bytes() == first
    with pytest.raises(campaign.StageBlocked):
        campaign.prepare(ctx, context[1], 1, confirm_history=True)


@pytest.mark.parametrize('exception,expected', [
    (campaign.acq.StudyBlocked('STUDY_HTTP_401_UNAUTHENTICATED'), 401),
    (campaign.acq.StudyBlocked('STUDY_HTTP_403_FORBIDDEN'), 403),
    (TimeoutError(TOKEN), None), (KeyboardInterrupt(TOKEN), None)])
def test_failed_or_unknown_get_has_sanitized_evidence_and_no_continuation(context, exception, expected):
    ctx, _, ack = ready(context)
    calls = []
    def fetch(*args):
        calls.append(1)
        raise exception
    result = campaign.execute(ctx, 1, ack, token_reader=lambda: TOKEN, fetch=fetch)
    assert calls == [1] and result['request_attempts'] == 1
    assert result['http_status'] == expected and result['reserved_cumulative_ceiling'] == 4
    assert result['retry_authorised'] is False and result['reservation_held'] is True
    assert TOKEN not in json.dumps(result)
    with pytest.raises(campaign.StageBlocked, match='INCOMPLETE_OR_FAILED_STAGE'):
        campaign.prepare(ctx, context[1], 1, confirm_history=True)


def test_token_cancel_consumes_claim_not_a_fabricated_get(context):
    ctx, _, ack = ready(context)
    def abort():
        raise KeyboardInterrupt(TOKEN)
    result = campaign.execute(ctx, 1, ack, token_reader=abort, fetch=lambda *args: pytest.fail('GET'))
    assert result['request_attempts'] == 0 and result['known_cumulative_attempts'] == 3
    assert result['reserved_cumulative_ceiling'] == 4
    with pytest.raises(campaign.StageBlocked):
        campaign.execute(ctx, 1, ack, token_reader=lambda: pytest.fail('retry'))


@pytest.mark.parametrize('mutation', ['allowance-bool', 'prior-two', 'window-bool', 'state', 'approval'])
def test_edited_binding_cannot_prompt_or_claim(context, mutation):
    ctx, _, _ = ready(context)
    path = campaign._binding_path(ctx, 1)
    value = json.loads(path.read_text())
    if mutation == 'allowance-bool': value['stage_allowance'] = True
    if mutation == 'prior-two': value['prior_consumed_requests'] = 2
    if mutation == 'window-bool': value['windows'][0]['ordinal'] = True
    if mutation == 'state': value['previous_state_sha256'] = '0' * 64
    if mutation == 'approval': value['approval_granted'] = True
    raw = campaign.old._canonical(value)
    path.write_bytes(raw)
    with pytest.raises(campaign.StageBlocked, match='BINDING_REVIEW_REQUIRED'):
        campaign.execute(ctx, 1, campaign.ACK_PREFIX + hashlib.sha256(raw).hexdigest(),
            token_reader=lambda: pytest.fail('prompt'))
    assert not ctx.state.exists()


@pytest.mark.parametrize('fault', ['claim', 'report'])
def test_partial_writes_are_preserved_and_never_resume_http(context, monkeypatch, fault):
    ctx, _, ack = ready(context)
    write = campaign.acq._write
    def fail(root, name, raw):
        if name == ('reservation.json' if fault == 'claim' else 'coverage.json'):
            raise OSError(TOKEN)
        return write(root, name, raw)
    monkeypatch.setattr(campaign.acq, '_write', fail)
    if fault == 'claim':
        with pytest.raises(OSError):
            campaign.execute(ctx, 1, ack, token_reader=lambda: pytest.fail('prompt'))
    else:
        result = campaign.execute(ctx, 1, ack, token_reader=lambda: TOKEN, fetch=response)
        assert result['stage'] == 'COVERAGE_REPORT' and result['request_attempts'] == 1
        assert (ctx.state / 'stage-01/001-RELIANCE-2022.json').exists()
    assert (ctx.state / 'stage-01').exists()
    with pytest.raises(campaign.StageBlocked):
        campaign.prepare(ctx, context[1], 1, confirm_history=True)


def test_concurrent_invocations_have_one_claim_one_prompt_one_get(context):
    ctx, _, ack = ready(context)
    counts = []
    lock = Lock()
    def token():
        with lock: counts.append('prompt')
        return TOKEN
    def fetch(window, value):
        with lock: counts.append('get')
        return response(window, value)
    def run():
        try:
            return campaign.execute(ctx, 1, ack, token_reader=token, fetch=fetch)['status']
        except (campaign.StageBlocked, OSError):
            return 'BLOCKED'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert results.count('CAMPAIGN_STAGE_RETAINED_NOT_DATA_ADMISSION') == 1
    assert counts.count('prompt') == counts.count('get') == 1


def test_unknown_old_claim_or_partial_initialization_never_buys_a_new_namespace(context):
    ctx, _, ack = ready(context)
    campaign.old.reserve(ctx.state, b'{}')
    with pytest.raises(campaign.StageBlocked, match='CAMPAIGN_STATE_REVIEW_REQUIRED'):
        campaign.execute(ctx, 1, ack, token_reader=lambda: pytest.fail('prompt'))
    assert campaign.Context(ctx.local, ctx.source, 'b' * 40).state == ctx.state


def test_mutated_retained_original_blocks_later_stage(context):
    ctx, _, ack = ready(context)
    campaign.execute(ctx, 1, ack, token_reader=lambda: TOKEN, fetch=response)
    (ctx.state / 'stage-01/001-RELIANCE-2022.json').write_bytes(b'CORRUPTED_SYNTHETIC')
    with pytest.raises(campaign.acq.StudyBlocked, match='ORIGINAL_OR_ARTIFACT_CHANGED'):
        campaign.prepare(ctx, context[1], 1, confirm_history=True)


def test_secret_echo_200_is_not_retained_as_data(context):
    ctx, _, ack = ready(context)
    raw = b'{"status":"error","secret":"' + TOKEN.encode() + b'"}'
    result = campaign.execute(ctx, 1, ack, token_reader=lambda: TOKEN,
        fetch=lambda *args: campaign.acq.Response(200, raw))
    assert result['http_status'] == 200 and result['request_attempts'] == 1
    assert TOKEN not in json.dumps(result)
    assert not (ctx.state / 'stage-01/001-RELIANCE-2022.json').exists()


def test_cli_unknown_option_is_redacted(capsys):
    assert campaign.main(['--token', TOKEN]) == 2
    assert TOKEN not in capsys.readouterr().out


def test_wrong_digest_ack_cannot_prompt_or_claim(context):
    ctx, _, _ = ready(context)
    with pytest.raises(campaign.StageBlocked, match='APPROVAL_ACK_REQUIRED'):
        campaign.execute(ctx, 1, campaign.ACK_PREFIX + '0' * 64,
            token_reader=lambda: pytest.fail('prompt'))
    assert not ctx.state.exists()


def test_partial_genesis_blocks_without_repair(context):
    ctx, _, ack = ready(context)
    campaign.old._parents(ctx.state)
    with pytest.raises(campaign.StageBlocked, match='PARTIAL_CAMPAIGN_INITIALIZATION'):
        campaign.execute(ctx, 1, ack, token_reader=lambda: pytest.fail('prompt'))
    assert list(ctx.state.iterdir()) == []


@pytest.mark.parametrize('mutation', ['window', 'counter', 'report-path', 'prefix', 'synthetic-origin'])
def test_prior_stage_corruption_blocks_successor(context, mutation):
    ctx, _, ack = ready(context)
    campaign.execute(ctx, 1, ack, token_reader=lambda: TOKEN, fetch=response)
    claim = ctx.state / 'stage-01'
    reservation_path = claim / 'reservation.json'
    result_path = claim / 'result.json'
    reservation = json.loads(reservation_path.read_text())
    result = json.loads(result_path.read_text())
    if mutation == 'window': reservation['windows'][0]['ordinal'] = 2
    if mutation == 'prefix': reservation['previous_state_sha256'] = '0' * 64
    if mutation == 'counter': result['known_cumulative_attempts'] = True
    if mutation == 'report-path': result['reports'][0]['name'] = '../unexpected-private.json'
    if mutation == 'synthetic-origin': result['retained'][0]['input_origin'] = 'NATIVE_TLS_NOT_PROVIDER_SIGNATURE'
    raw = campaign.old._canonical(reservation)
    reservation_path.write_bytes(raw)
    result['reservation_sha256'] = hashlib.sha256(raw).hexdigest()
    result_path.write_bytes(campaign.old._canonical(result))
    with pytest.raises(campaign.StageBlocked):
        campaign.prepare(ctx, context[1], 1, confirm_history=True)


@pytest.mark.parametrize('failure_marker_also_fails', [False, True])
def test_complete_result_bytes_followed_by_write_error_never_admit_next_stage(
    context, monkeypatch, failure_marker_also_fails,
):
    ctx, _, ack = ready(context)
    original_write = campaign.acq._write
    def broken_write(root, name, raw):
        if name == 'failure.json' and failure_marker_also_fails:
            raise OSError(TOKEN)
        result = original_write(root, name, raw)
        if name == 'result.json':
            raise OSError(TOKEN)
        return result
    monkeypatch.setattr(campaign.acq, '_write', broken_write)
    result = campaign.execute(ctx, 1, ack, token_reader=lambda: TOKEN, fetch=response)
    assert result['status'] == 'CAMPAIGN_STAGE_BLOCKED_RESERVATION_HELD'
    assert (ctx.state / 'stage-01/result.json').exists()
    assert not (ctx.state / 'stage-01/complete').exists()
    with pytest.raises(campaign.StageBlocked, match='INCOMPLETE_OR_FAILED_STAGE_NO_RETRY'):
        campaign.prepare(ctx, context[1], 1, confirm_history=True)


def test_failure_marker_vetoes_even_a_complete_local_result(context):
    ctx, _, ack = ready(context)
    campaign.execute(ctx, 1, ack, token_reader=lambda: TOKEN, fetch=response)
    (ctx.state / 'stage-01/failure.json').write_text('{}')
    with pytest.raises(campaign.StageBlocked, match='INCOMPLETE_OR_FAILED_STAGE_NO_RETRY'):
        campaign.prepare(ctx, context[1], 1, confirm_history=True)


@pytest.mark.parametrize('candles', [
    [['2022-01-03T00:00:00+05:30', 100, 90, 80, 105, 1000, 0]],
    '<html>unexpected diagnostic</html>', {'diagnostic': 'unexpected'},
    [['2022-01-03T00:00:00+05:30', {'unexpected': 'diagnostic'}, 110, 90, 105, 1000, 0]],
    [['2026-01-03T00:00:00+05:30', 100, 110, 90, 105, 1000, 0]],
])
def test_invalid_200_is_not_retained_before_all_existing_decoder_checks(context, candles):
    ctx, _, ack = ready(context)
    raw = json.dumps({'status': 'success', 'data': {'candles': candles}}).encode()
    result = campaign.execute(ctx, 1, ack, token_reader=lambda: TOKEN,
        fetch=lambda *args: campaign.acq.Response(200, raw))
    assert result['status'] == 'CAMPAIGN_STAGE_BLOCKED_RESERVATION_HELD'
    assert result['stage'] == 'DECODE' and result['http_status'] == 200
    assert result['request_attempts'] == 1 and result['retained_windows_this_stage'] == 0
    assert result['safe_originals_not_data_admission'] == []
    assert not (ctx.state / 'stage-01/001-RELIANCE-2022.json').exists()
    assert not (ctx.state / 'stage-01/complete').exists()
    with pytest.raises(campaign.StageBlocked):
        campaign.prepare(ctx, context[1], 1, confirm_history=True)
