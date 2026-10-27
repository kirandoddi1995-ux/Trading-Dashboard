"""Mocked transport and generated 2022–24 fixtures only; never provider access."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import equity_private_acquire as acq

TOKEN = 'SYNTHETIC_HIDDEN_TOKEN_NOT_REAL'


def candle(window):
    return json.dumps({'status': 'success', 'data': {'candles': [
        [window.start[:4] + '-01-03T00:00:00+05:30', 100, 103, 99, 102, 1000, 0]]}}).encode()


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(acq, '_source_binding', lambda: {'synthetic_public_source': 'a' * 64})
    monkeypatch.setattr(acq, '_parquet', lambda root, decoded: {'synthetic_only': True})
    monkeypatch.setitem(sys.modules, 'equity_real_report', SimpleNamespace(
        build_report=lambda decoded, **kwargs: {'status': 'SYNTHETIC_REPORT', 'symbols': list(decoded), **acq.FLAGS},
        render_html=lambda value: '<!doctype html><html><head></head><body>SYNTHETIC</body></html>'))


def test_preview_is_exactly_36_windows_and_has_no_side_effects(monkeypatch, capsys):
    def denied(*args, **kwargs):
        pytest.fail('Preview attempted I/O')
    monkeypatch.setattr(acq, 'acquire', denied)
    monkeypatch.setattr(Path, 'open', denied)
    assert acq.main([]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value['network_calls'] == value['credential_reads'] == value['writes'] == 0
    windows = value['specification']['windows']
    assert len(windows) == len({w['filename'] for w in windows}) == 36
    assert [w['symbol'] for w in windows[::3]] == list(acq.COHORT)
    assert {w['start'][:4] for w in windows} == {'2022', '2023', '2024'}
    assert all(w['start'][5:] == '01-01' and w['end'][5:] == '12-31' for w in windows)
    assert value['specification']['metadata_requests'] == value['specification']['retries'] == 0
    assert all(value['specification'][flag] is False for flag in acq.FLAGS)


def test_unconfirmed_output_is_still_zero_io(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(acq, 'acquire', lambda *a, **k: pytest.fail('No confirmation'))
    path = tmp_path / 'new'
    assert acq.main(['--output', str(path)]) == 0
    assert not path.exists() and json.loads(capsys.readouterr().out)['writes'] == 0


def test_invalid_arguments_do_not_echo_possible_secret(capsys):
    assert acq.main(['--token', TOKEN]) == 2
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err
    assert json.loads(captured.out)['category'] == 'STUDY_ARGUMENT_REVIEW'


def test_hidden_prompt_refuses_non_tty_before_read(monkeypatch):
    monkeypatch.setattr(acq.sys, 'stdin', SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(acq.getpass, 'getpass', lambda *a: pytest.fail('Must not read'))
    with pytest.raises(acq.StudyBlocked, match='INTERACTIVE_HIDDEN_PROMPT'):
        acq._hidden_token()


def test_hidden_prompt_fallback_warning_is_not_echoed(monkeypatch):
    import warnings
    monkeypatch.setattr(acq.sys, 'stdin', SimpleNamespace(isatty=lambda: True))
    def insecure(*args):
        warnings.warn('synthetic no echo unavailable', acq.getpass.GetPassWarning)
        pytest.fail('Warning must abort before fallback input')
    monkeypatch.setattr(acq.getpass, 'getpass', insecure)
    with pytest.raises(acq.getpass.GetPassWarning):
        acq._hidden_token()


@pytest.mark.parametrize('value', ['', 'short', 'X' * 8193, 'A' * 16 + '\n', 'A' * 16 + ' ', 'A' * 16 + '\u00e9'])
def test_invalid_tokens_never_reach_network(tmp_path, isolated, value):
    result = acq.acquire(tmp_path / 'attempt', token_reader=lambda: value,
                         fetch=lambda *a: pytest.fail('Token must be rejected'))
    assert result['status'] == 'BLOCKED' and result['request_attempts'] == 0
    assert result['category'] == 'STUDY_TOKEN_INPUT_REVIEW'
    assert result['retry_authorised'] is False


def test_exact_request_budget_and_byte_preservation(tmp_path, isolated):
    calls, pauses = [], []
    def fetch(window, token):
        calls.append(window)
        assert token == TOKEN
        return acq.Response(200, candle(window))
    root = tmp_path / 'attempt'
    result = acq.acquire(root, token_reader=lambda: TOKEN, fetch=fetch, pause=pauses.append)
    assert result['status'] == 'SYNTHETIC_STUDY_REHEARSAL_NOT_REAL_DATA'
    assert calls == list(acq.windows()) and pauses == [1.] * 35
    assert result['request_attempts'] == result['completed_windows'] == result['rows'] == 36
    assert result['transport'] == 'INJECTED_NOT_PROVIDER_EVIDENCE'
    assert hashlib.sha256((root / 'acquisition.json').read_bytes()).hexdigest() == result['acquisition_sha256']
    for window in calls:
        assert (root / window.filename).read_bytes() == candle(window)
    assert all(result[flag] is False for flag in acq.FLAGS)
    assert len(list(root.glob('request-*-intent.json'))) == len(list(root.glob('request-*-result.json'))) == 36
    assert TOKEN not in '\n'.join(path.read_text() for path in root.glob('*.json'))
    assert json.loads((root / 'report.json').read_text())['input_origin'] == 'INJECTED_SYNTHETIC_NOT_MARKET_EVIDENCE'
    page = (root / 'report.html').read_text()
    assert 'INJECTED_SYNTHETIC_NOT_MARKET_EVIDENCE' in page and 'Content-Security-Policy' in page


def test_failed_get_is_consumed_no_retry_and_originals_survive(tmp_path, isolated):
    calls = []
    def fetch(window, token):
        calls.append(window.ordinal)
        if window.ordinal == 3:
            raise RuntimeError('SENSITIVE ' + token)
        return acq.Response(200, candle(window))
    root = tmp_path / 'attempt'
    result = acq.acquire(root, token_reader=lambda: TOKEN, fetch=fetch, pause=lambda _: None)
    assert calls == [1, 2, 3] and result['request_attempts'] == 3
    assert result['originals_retained'] == 2 and result['category'] == 'UNCLASSIFIED_FAILURE'
    assert (root / 'request-003-intent.json').exists()
    assert not (root / 'request-003-result.json').exists()
    assert TOKEN not in (root / 'failure.json').read_text()
    with pytest.raises(acq.StudyBlocked, match='NEW_ROOT_REQUIRED_NO_RETRY'):
        acq.acquire(root, token_reader=lambda: pytest.fail('No second prompt'))


@pytest.mark.parametrize('mode,category', [
    ('oversize', 'STUDY_RESPONSE_BYTES_BOUND'), ('empty', 'STUDY_RESPONSE_BYTES_BOUND'),
    ('status', 'STUDY_RESPONSE_REVIEW'), ('content_type', 'STUDY_RESPONSE_REVIEW'),
    ('secret_echo', 'STUDY_RESPONSE_SECRET_ECHO_REJECTED')])
def test_bad_responses_rejected_before_private_write(tmp_path, isolated, mode, category):
    def fetch(window, token):
        if mode == 'oversize': return acq.Response(200, b'X' * (acq.MAX_BYTES + 1))
        if mode == 'empty': return acq.Response(200, b'')
        if mode == 'status': return acq.Response(401, token.encode())
        if mode == 'content_type': return acq.Response(200, token.encode(), 'text/html')
        return acq.Response(200, b'{"error":"' + token.encode() + b'"}')
    root = tmp_path / mode
    result = acq.acquire(root, token_reader=lambda: TOKEN, fetch=fetch)
    assert result['request_attempts'] == 1 and result['originals_retained'] == 0
    assert result['category'] == category
    assert not list(root.glob('001-*.json'))
    assert TOKEN not in '\n'.join(path.read_text() for path in root.glob('*.json'))


def test_malformed_success_is_not_retained_or_admitted(tmp_path, isolated):
    raw = b'{"status":"success","data":{"candles":[]}}'
    root = tmp_path / 'attempt'
    result = acq.acquire(root, token_reader=lambda: TOKEN,
                         fetch=lambda *a: acq.Response(200, raw))
    assert result['stage'] == 'DECODE' and result['originals_retained'] == 0
    assert not (root / acq.windows()[0].filename).exists()
    assert not (root / 'acquisition.json').exists()


@pytest.mark.parametrize('encoding', ['unicode', 'url', 'html', 'duplicate'])
def test_escaped_secret_echo_cannot_be_retained(tmp_path, isolated, encoding):
    encoded = ''.join('\\u%04x' % ord(c) for c in TOKEN)
    if encoding == 'url':
        encoded = ''.join('%%%02X' % ord(c) for c in TOKEN)
    elif encoding == 'html':
        encoded = ''.join('&#%d;' % ord(c) for c in TOKEN)
    if encoding == 'duplicate':
        raw = ('{"echo":"' + encoded + '","echo":"not a secret"}').encode()
    else:
        raw = ('{"echo":"' + encoded + '"}').encode()
    root = tmp_path / encoding
    result = acq.acquire(root, token_reader=lambda: TOKEN,
                         fetch=lambda *a: acq.Response(200, raw))
    assert result['category'] == 'STUDY_RESPONSE_SECRET_ECHO_REJECTED'
    assert result['originals_retained'] == 0
    assert not list(root.glob('001-*.json'))


def test_unparseable_json_is_not_retained_before_secret_screen(tmp_path, isolated):
    root = tmp_path / 'attempt'
    result = acq.acquire(root, token_reader=lambda: TOKEN,
                         fetch=lambda *a: acq.Response(200, b'not-json'))
    assert result['category'] == 'STUDY_JSON_SYNTAX_REVIEW'
    assert result['originals_retained'] == 0


def test_unknown_provider_fields_cannot_retain_encoded_credentials(tmp_path, isolated):
    # Even an encoding the token matcher does not decode is outside the schema.
    double = ''.join('\\u%04x' % ord(c) for c in TOKEN)
    payload = json.loads(candle(acq.windows()[0]))
    payload['diagnostic'] = double
    root = tmp_path / 'attempt'
    result = acq.acquire(root, token_reader=lambda: TOKEN,
                         fetch=lambda *a: acq.Response(200, json.dumps(payload).encode()))
    assert result['category'] == 'STUDY_RESPONSE_SHAPE_REVIEW'
    assert result['originals_retained'] == 0


def test_report_receives_bound_annual_decoded_chunks(tmp_path, isolated, monkeypatch):
    observed = {}
    def build(decoded, *, manifest):
        observed.update(decoded=decoded, manifest=manifest)
        return {'status': 'SYNTHETIC_REPORT'}
    monkeypatch.setitem(sys.modules, 'equity_real_report', SimpleNamespace(build_report=build,
        render_html=lambda value: '<html><head></head><body>SYNTHETIC</body></html>'))
    result = acq.acquire(tmp_path / 'attempt', token_reader=lambda: TOKEN,
        fetch=lambda w, t: acq.Response(200, candle(w)), pause=lambda _: None)
    assert result['completed_windows'] == 36
    assert all(len(value) == 3 for value in observed['decoded'].values())
    assert all(c['status'] == 'UPSTOX_DAILY_STRUCTURE_ONLY_NOT_ADMISSION'
               for values in observed['decoded'].values() for c in values)
    for symbol in acq.COHORT:
        assert observed['manifest']['symbols'][symbol]['chunks'] == [
            {key: chunk[key] for key in ('start', 'end', 'source_sha256', 'decoded_sha256')}
            for chunk in observed['decoded'][symbol]]


@pytest.mark.parametrize('name', ['Forward', 'ForwardOps', 'kiran_forward_example'])
def test_capture_locations_rejected_without_credentials(tmp_path, name):
    parent = tmp_path / name
    parent.mkdir()
    with pytest.raises(acq.StudyBlocked, match='CAPTURE_OR_REPOSITORY'):
        acq.acquire(parent / 'study', token_reader=lambda: pytest.fail('No capture credential reads'))
    assert not (parent / 'study').exists()


def test_repository_and_existing_destinations_rejected(tmp_path):
    (tmp_path / '.git').mkdir()
    with pytest.raises(acq.StudyBlocked, match='CAPTURE_OR_REPOSITORY'):
        acq._new_private_root(tmp_path / 'output')


def test_source_change_blocks_after_retaining_all_originals(tmp_path, isolated, monkeypatch):
    values = iter([{'code': 'a'}, {'code': 'b'}])
    monkeypatch.setattr(acq, '_source_binding', lambda: next(values))
    result = acq.acquire(tmp_path / 'attempt', token_reader=lambda: TOKEN,
        fetch=lambda w, t: acq.Response(200, candle(w)), pause=lambda _: None)
    assert result['request_attempts'] == result['originals_retained'] == 36
    assert result['category'] == 'STUDY_SOURCE_CHANGED'


def test_https_uses_pinned_host_tls_no_proxy_no_redirect_and_bounded_read(monkeypatch):
    observed = {}
    window = acq.windows()[0]
    expected = acq.HOST + '/v3/historical-candle/NSE_EQ%7CINE002A01018/days/1/2022-12-31/2022-01-01'
    class Headers:
        def get(self, name, default=None): return default
        def get_content_type(self): return 'application/json'
    class Stream:
        status, headers = 200, Headers()
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def geturl(self): return expected
        def read(self, count): observed['bound'] = count; return candle(window)
    class Opener:
        def open(self, req, timeout):
            observed.update(url=req.full_url, headers=dict(req.header_items()), timeout=timeout)
            return Stream()
    monkeypatch.setattr(acq, 'build_opener', lambda *handlers: (observed.update(handlers=handlers) or Opener()))
    result = acq._https_get(window, TOKEN)
    assert result.body == candle(window) and observed['url'] == expected
    assert observed['bound'] == acq.MAX_BYTES + 1 and observed['timeout'] == 20
    assert observed['headers']['Authorization'] == 'Bearer ' + TOKEN
    proxy, redirects, tls = observed['handlers']
    assert proxy.proxies == {} and tls._context.check_hostname is True
    assert tls._context.verify_mode == acq.ssl.CERT_REQUIRED
    with pytest.raises(acq.StudyBlocked, match='REDIRECT'):
        redirects.redirect_request(None, None, 302, 'ignored', {}, 'https://example.invalid/')


def test_parquet_roundtrip_is_derived_and_exact_decimal_text(tmp_path):
    decoded = {symbol: [] for symbol in acq.COHORT}
    decoded[acq.COHORT[0]] = [{'date': '2022-01-03', 'open': '100.123456789123456789',
        'high': '103', 'low': '99', 'close': '102', 'volume': 1, 'open_interest': 0,
        'provider_timestamp': '2022-01-03T00:00:00+05:30'}]
    result = acq._parquet(tmp_path, decoded)
    import pyarrow.parquet as pq
    assert result['rows'] == 1 and result['readback_equal'] is True
    assert pq.read_table(tmp_path / 'candles.parquet').to_pylist()[0]['open'] == '100.123456789123456789'


def test_disk_floor_blocks_before_credentials_or_new_directory(tmp_path, isolated, monkeypatch):
    monkeypatch.setattr(acq.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1))
    root = tmp_path / 'attempt'
    with pytest.raises(acq.StudyBlocked, match='LOCAL_FREE_SPACE'):
        acq.acquire(root, token_reader=lambda: pytest.fail('No secret read'))
    assert not root.exists()


def test_disk_pressure_during_run_stops_without_another_get(tmp_path, isolated, monkeypatch):
    values = iter([acq.MIN_FREE_BYTES, acq.MIN_FREE_BYTES, 1])
    monkeypatch.setattr(acq.shutil, 'disk_usage', lambda _: SimpleNamespace(free=next(values)))
    calls = []
    def fetch(window, token):
        calls.append(window.ordinal)
        return acq.Response(200, candle(window))
    result = acq.acquire(tmp_path / 'attempt', token_reader=lambda: TOKEN, fetch=fetch, pause=lambda _: None)
    assert calls == [1] and result['request_attempts'] == result['originals_retained'] == 1
    assert result['category'] == 'STUDY_LOCAL_FREE_SPACE_REVIEW'


def test_frozen_prerequisite_mismatch_blocks_before_secret_or_write(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'equity_real_report', SimpleNamespace(
        APP_SHA256='0' * 64, ENGINE_SHA256='0' * 64, INDICATORS_SHA256='0' * 64))
    root = tmp_path / 'attempt'
    with pytest.raises(acq.StudyBlocked, match='SOURCE_CHANGED'):
        acq.acquire(root, token_reader=lambda: pytest.fail('No secret read'))
    assert not root.exists()


def test_unreviewed_numerical_profile_is_rejected(monkeypatch):
    monkeypatch.setattr(acq.metadata, 'version', lambda _: '0.0')
    with pytest.raises(acq.StudyBlocked, match='RUNTIME_PROFILE'):
        acq._runtime_profile()


def test_generated_batch_to_real_report_html_and_parquet_without_network(tmp_path):
    """End-to-end adapter test. All prices/dates here are generated fixtures."""
    from datetime import date, timedelta
    def generated(window, token):
        assert token == TOKEN
        year = int(window.start[:4])
        day = date(year, 1, 1)
        candles = []
        while len(candles) < 120:
            if day.weekday() < 5:  # A fixture schedule, NOT an NSE calendar.
                price = 100 + (year - 2022) * 30 + len(candles) * .2
                candles.append([day.isoformat() + 'T00:00:00+05:30',
                    round(price, 2), round(price + 1, 2), round(price - 1, 2),
                    round(price + .4, 2), 10000, 0])
            day += timedelta(days=1)
        return acq.Response(200, json.dumps({'status': 'success', 'data': {'candles': candles}}).encode())
    root = tmp_path / 'generated-only'
    result = acq.acquire(root, token_reader=lambda: TOKEN, fetch=generated, pause=lambda _: None)
    assert result['status'] == 'SYNTHETIC_STUDY_REHEARSAL_NOT_REAL_DATA'
    assert result['rows'] == 12 * 3 * 120 and result['completed_windows'] == 36
    wrapper = json.loads((root / 'report.json').read_text())
    assert wrapper['input_origin'] == 'INJECTED_SYNTHETIC_NOT_MARKET_EVIDENCE'
    report = wrapper['analysis']
    assert report['dataset_quality']['total_rows'] == 4320
    assert report['dataset_quality']['calendar_verified'] is False
    assert report['performance_claim_verified'] is report['out_of_sample_claim'] is False
    assert report['full_app_reproduction'] is False
    for symbol in acq.COHORT:
        technical = report['per_name'][symbol]['technical']
        for scenario in technical.get('scenarios', {}).values():
            assert all('2023' <= trade['entry_at'][:4] <= '2024' for trade in scenario['trades'])
    assert result['parquet']['rows'] == 4320 and result['parquet']['readback_equal'] is True
    assert '<table' in (root / 'report.html').read_text()
    for descriptor in result['files']:
        assert hashlib.sha256((root / descriptor['name']).read_bytes()).hexdigest() == descriptor['sha256']
