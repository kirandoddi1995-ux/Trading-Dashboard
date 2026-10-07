"""Deterministic public-source diagnostics; no real requests or source prices."""
from datetime import date
import hashlib
import json

import pytest
import requests

import nse_close_transport_check as diagnostic


class Response:
    def __init__(self, status=200, raw=b'synthetic fixture', error=None):
        self.status_code, self.raw, self.error = status, raw, error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def iter_content(self, size):
        assert size == 65536
        if self.error:
            raise self.error
        yield self.raw


class Session:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, 0

    def get(self, url, **kwargs):
        self.calls += 1
        assert url == 'https://nsearchives.nseindia.com/content/indices/ind_close_all_06102026.csv'
        assert kwargs == dict(timeout=(5, 20), verify=True, allow_redirects=False, stream=True)
        if self.error:
            raise self.error
        return self.response


def test_success_is_transport_only_and_single_request():
    session = Session(Response())
    result = diagnostic.probe(session, date(2026, 10, 6))
    assert session.calls == 1
    assert result['sha256'] == hashlib.sha256(b'synthetic fixture').hexdigest()
    assert result['status'] == 'TRANSPORT_CHECK_COMPLETE'
    assert result['payload_validated'] is False
    assert result['session_prepared'] is False
    assert result['writes'] == 0 and result['approval_authority'] is False


@pytest.mark.parametrize('error,code', [
    (requests.exceptions.ProxyError, 'NSE_CLOSE_PROXY_ERROR'),
    (requests.exceptions.SSLError, 'NSE_CLOSE_TLS_ERROR'),
    (requests.exceptions.ConnectTimeout, 'NSE_CLOSE_CONNECT_TIMEOUT'),
    (requests.exceptions.ReadTimeout, 'NSE_CLOSE_READ_TIMEOUT'),
    (requests.exceptions.Timeout, 'NSE_CLOSE_TIMEOUT'),
    (requests.exceptions.ConnectionError, 'NSE_CLOSE_CONNECTION_ERROR'),
    (requests.exceptions.RequestException, 'NSE_CLOSE_REQUEST_ERROR'),
])
@pytest.mark.parametrize('stream', [False, True])
def test_transport_errors_redacted_at_request_and_stream(error, code, stream):
    failure = error('PRIVATE_URL_PASSWORD_COOKIE')
    session = Session(Response(error=failure)) if stream else Session(error=failure)
    result = diagnostic.probe(session, date(2026, 10, 6))
    assert result['code'] == code
    assert 'PRIVATE' not in json.dumps(result)
    assert session.calls == 1 and result['writes'] == 0


@pytest.mark.parametrize('status', [301, 302, 403, 404, 429, 500])
def test_non_200_never_read_body_or_follow_redirect(status):
    result = diagnostic.probe(Session(Response(status=status, error=AssertionError())),
                              date(2026, 10, 6))
    assert result['code'] == 'NSE_CLOSE_HTTP_NON_200'
    assert result['http_status'] == status
    assert 'sha256' not in result


@pytest.mark.parametrize('raw,code', [
    (b'', 'NSE_CLOSE_EMPTY_BODY'),
    (b'x' * (diagnostic.LIMIT + 1), 'NSE_CLOSE_SIZE_LIMIT_EXCEEDED'),
], ids=['empty', 'oversize'])
def test_size_and_empty_fail_closed(raw, code):
    assert diagnostic.probe(Session(Response(raw=raw)), date(2026, 10, 6))['code'] == code


@pytest.mark.parametrize('args,expected', [
    (['--close-date', '2026-10-06'], 0),
    (['--close-date', '20261006', '--check'], 2),
    (['--close-date', 'https://private.invalid/', '--check'], 2),
    (['--close-date', '2026-02-30', '--check'], 2),
])
def test_preview_invalid_date_offline(args, expected, monkeypatch, capsys):
    monkeypatch.setattr(requests, 'Session', lambda: pytest.fail('Network'))
    assert diagnostic.main(args) == expected
    assert json.loads(capsys.readouterr().out)['network_calls'] == 0


def test_unexpected_failure_is_redacted(monkeypatch, capsys):
    def broken():
        raise RuntimeError('PRIVATE_PATH_OR_SECRET')
    monkeypatch.setattr(requests, 'Session', broken)
    assert diagnostic.main(['--close-date', '2026-10-06', '--check']) == 2
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output
    assert json.loads(output)['code'] == 'TRANSPORT_DIAGNOSTIC_UNAVAILABLE'
