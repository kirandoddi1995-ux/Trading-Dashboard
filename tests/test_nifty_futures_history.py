from copy import deepcopy
from datetime import date
import gzip
import json

import pytest
import requests

import nifty_futures_history as history
from download_nifty_history import HistoryError

SECRET = 'NEVER_PRINT_THIS_CREDENTIAL'
DAY = date(2024, 1, 3)
EXPIRY = date(2024, 1, 25)
CONTRACT = {'instrument_key': 'NSE_FO|123|25-01-2024', 'expiry': str(EXPIRY),
            'underlying_key': history.KEY, 'instrument_type': 'FUT',
            'exchange': 'NSE', 'segment': 'NSE_FO', 'lot_size': 50, 'tick_size': 5}


class Response:
    def __init__(self, body, status=200):
        self.raw = json.dumps(body).encode()
        self.status_code = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, size):
        yield self.raw


class Session:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def bodies():
    return [Response({'status': 'success', 'data': [deepcopy(CONTRACT)]}),
            Response({'status': 'success', 'data': {'candles': [
                ['2024-01-03T09:15:00+05:30', 20000, 20010, 19990, 20005, 100, 200]]}})]


def test_provider_key_tls_bounded_request_and_missing_session_visible():
    session = Session(bodies())
    result = history.Reader(SECRET, session).probe(DAY, DAY, EXPIRY)
    assert len(session.calls) == 2
    assert '/NSE_FO%7C123%7C25-01-2024/5minute/' in session.calls[1][0]
    for _, args in session.calls:
        assert args['verify'] is True and args['allow_redirects'] is False
        assert args['timeout'] == (5, 30) and args['stream'] is True
    assert result['session_check']['status'] == 'FAIL'
    assert len(result['session_check']['missing']) == 74
    assert result['replay_ready'] is False and result['approval_authority'] is False
    assert result['provider_contract']['lot_size'] == 50


@pytest.mark.parametrize('year', [2025, 2026])
def test_holdout_and_validation_network_access_blocked(year):
    session = Session([])
    with pytest.raises(HistoryError, match='FROZEN'):
        history.Reader(SECRET, session).probe(date(year, 1, 3), date(year, 1, 3), date(year, 1, 25))
    assert not session.calls


@pytest.mark.parametrize('field,value', [('expiry', '2024-01-26'), ('lot_size', True),
                                        ('underlying_key', 'BANKNIFTY'), ('instrument_type', 'CE'),
                                        ('instrument_key', 'NSE_FO|123|01-01-2024')])
def test_contract_identity_failure_does_not_fetch_candles(field, value):
    contract = deepcopy(CONTRACT)
    contract[field] = value
    session = Session([Response({'status': 'success', 'data': [contract]})])
    with pytest.raises(HistoryError, match='IDENTITY'):
        history.Reader(SECRET, session).probe(DAY, DAY, EXPIRY)
    assert len(session.calls) == 1


@pytest.mark.parametrize('failure', [401, 403, 400, 500, 'transport', 'empty'])
def test_failures_are_sanitized_and_never_claim_history(failure, capsys):
    if failure == 'transport':
        responses = [requests.RequestException(SECRET)] * 3
    elif failure == 'empty':
        responses = [bodies()[0], Response({'status': 'success', 'data': {'candles': []}})]
    else:
        responses = [Response({'secret': SECRET}, status=failure)] * 3
    session = Session(responses)
    with pytest.raises(HistoryError) as error:
        history.Reader(SECRET, session, sleep=lambda seconds: None).probe(DAY, DAY, EXPIRY)
    assert SECRET not in str(error.value)
    assert SECRET not in capsys.readouterr().out


def test_preview_never_prompts_or_opens_network(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(history.getpass, 'getpass', lambda *a: pytest.fail('token prompt in preview'))
    monkeypatch.setattr(history.requests, 'Session', lambda: pytest.fail('network in preview'))
    assert history.main(['--start', str(DAY), '--end', str(DAY), '--expiry', str(EXPIRY),
                         '--output', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['network_calls'] == 0
    assert not list(tmp_path.iterdir())


def test_cli_hidden_token_private_artifact_and_safe_status(tmp_path, monkeypatch, capsys):
    class Managed(Session):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(history.getpass, 'getpass', lambda *a: SECRET)
    monkeypatch.setattr(history.requests, 'Session', lambda: Managed(bodies()))
    args = ['--start', str(DAY), '--end', str(DAY), '--expiry', str(EXPIRY),
            '--output', str(tmp_path), '--confirm-network']
    assert history.main(args) == 0
    output = capsys.readouterr().out
    assert SECRET not in output and str(tmp_path) not in output
    path = next(tmp_path.glob('*.gz'))
    data = json.loads(gzip.decompress(path.read_bytes()))
    assert SECRET not in json.dumps(data)
    assert data['replay_ready'] is False
    monkeypatch.setattr(history.getpass, 'getpass', lambda *a: pytest.fail('existing artifact must not fetch'))
    assert history.main(args) == 2


def test_output_in_repo_rejected_before_token(monkeypatch, capsys):
    monkeypatch.setattr(history.getpass, 'getpass', lambda *a: pytest.fail('token prompt'))
    assert history.main(['--start', str(DAY), '--end', str(DAY), '--expiry', str(EXPIRY),
                         '--output', str(history.Path(history.__file__).parent)]) == 2
    assert 'PRIVATE_OUTPUT' in capsys.readouterr().out
