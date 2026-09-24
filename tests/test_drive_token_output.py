"""Fake credentials only: never contact Google or write real token files."""
import importlib
import json
from unittest.mock import Mock

import pytest

import authorize_drive as auth
import get_drive_token as helper
from drive_archive import ArchiveError, SCOPE

PRIVATE = ['PRIVATE_CLIENT', 'PRIVATE_SECRET', 'PRIVATE_REFRESH', 'PRIVATE_ACCESS', 'PRIVATE_CODE']


def assert_private(capsys):
    captured = capsys.readouterr()
    assert all(value not in captured.out + captured.err for value in PRIVATE)
    assert 'Traceback' not in captured.out + captured.err


def test_import_is_silent(monkeypatch, capsys):
    prompt = Mock(side_effect=AssertionError('unexpected prompt'))
    monkeypatch.setattr('builtins.input', prompt)
    importlib.reload(helper)
    prompt.assert_not_called()
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('error', [RuntimeError, ArchiveError, KeyboardInterrupt])
def test_wrapper_hides_dependency_errors(monkeypatch, capsys, error):
    monkeypatch.setattr(auth, 'main', Mock(side_effect=error(json.dumps(PRIVATE))))
    assert helper.main() == 1
    assert_private(capsys)


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setattr(auth.Path, 'exists', lambda self: False)
    monkeypatch.setattr(auth.Path, 'read_text', lambda *a, **k: json.dumps({
        'installed': {'client_id': PRIVATE[0], 'client_secret': PRIVATE[1]}}))
    monkeypatch.setattr('builtins.input', lambda *a: 'YES')
    code = Mock(return_value=(PRIVATE[4], 'http://127.0.0.1/oauth2callback'))
    monkeypatch.setattr(auth, 'get_authorization_code', code)
    response = Mock(status_code=200)
    response.json.return_value = {'refresh_token': PRIVATE[2], 'access_token': PRIVATE[3], 'scope': SCOPE}
    post = Mock(return_value=response)
    monkeypatch.setattr(auth.requests, 'post', post)
    credentials = Mock(return_value=object())
    monkeypatch.setattr(auth, 'credentials', credentials)
    folder = Mock(status_code=200)
    folder.json.return_value = {'id': 'folder'}
    session = Mock()
    session.post.return_value = folder
    context = Mock()
    context.__enter__ = Mock(return_value=session)
    context.__exit__ = Mock(return_value=False)
    constructor = Mock(return_value=context)
    monkeypatch.setattr(auth, 'AuthorizedSession', constructor)
    save = Mock()
    monkeypatch.setattr(auth, 'save_private_token', save)
    return dict(code=code, post=post, json=response.json, credentials=credentials,
                constructor=constructor, refresh=context.__enter__, folder_post=session.post,
                folder_json=folder.json, save=save, response=response, folder=folder)


def test_success_only_saves_credentials_privately(flow, capsys):
    assert helper.main() == 0
    path, token = flow['save'].call_args.args
    assert path == 'token.json'
    assert token['refresh_token'] == PRIVATE[2]
    assert token['client_secret'] == PRIVATE[1]
    assert 'access_token' not in token
    assert_private(capsys)


@pytest.mark.parametrize('stage', ['code', 'post', 'json', 'credentials', 'constructor',
                                 'refresh', 'folder_post', 'folder_json', 'save'])
@pytest.mark.parametrize('error', [RuntimeError, ArchiveError])
def test_auth_error_paths_never_print_raw_credentials(flow, capsys, stage, error):
    flow[stage].side_effect = error(json.dumps(PRIVATE))
    assert auth.main() == 1
    assert_private(capsys)


@pytest.mark.parametrize('case', ['existing', 'bad_json', 'cancel', 'exchange_status',
                                 'no_refresh', 'wrong_scope', 'folder_status', 'interrupt'])
def test_validation_and_cancellation_are_private(flow, monkeypatch, capsys, case):
    if case == 'existing':
        monkeypatch.setattr(auth.Path, 'exists', lambda self: True)
    elif case == 'bad_json':
        monkeypatch.setattr(auth.Path, 'read_text', lambda *a, **k: PRIVATE[1])
    elif case == 'cancel':
        monkeypatch.setattr('builtins.input', lambda *a: 'NO')
    elif case == 'exchange_status':
        flow['response'].status_code = 400
    elif case == 'no_refresh':
        flow['json'].return_value = {'access_token': PRIVATE[3], 'scope': SCOPE}
    elif case == 'wrong_scope':
        flow['json'].return_value = {'refresh_token': PRIVATE[2], 'scope': 'wrong'}
    elif case == 'folder_status':
        flow['folder'].status_code = 403
    else:
        flow['code'].side_effect = KeyboardInterrupt(json.dumps(PRIVATE))
    assert auth.main() == 1
    assert_private(capsys)
