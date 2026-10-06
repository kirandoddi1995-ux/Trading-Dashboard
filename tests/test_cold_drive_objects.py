"""Offline Drive protocol, ACL, size, cross-client identity and retry tests."""
import hashlib
import json
from unittest.mock import Mock

import pytest

from cold_drive_objects import (API, UPLOAD, CAPS, FORMAT, ColdDriveObjects,
                               DriveObjectError, READ_SCOPE, TOKEN_URI, viewer_session)


class Reply:
    def __init__(self, data, status=200):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.status_code = status
        self.closed = False

    def iter_content(self, _chunk_size):
        for start in range(0, len(self.data), 65536):
            yield self.data[start:start+65536]

    def close(self):
        self.closed = True


class DriveSession:
    def __init__(self):
        self.calls = []
        self.files = {}
        self.acls = {'folder': [{'type': 'user', 'role': 'owner'}]}
        self.folder = {'id': 'folder', 'trashed': False,
                       'mimeType': 'application/vnd.google-apps.folder',
                       'capabilities': {'canAddChildren': True}}
        self.search_override = None
        self.status = 200
        self.responses = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        params = kwargs.get('params', {})
        if url.endswith('/permissions'):
            result = {'permissions': self.acls.get(url.split('/')[-2], [])}
        elif method == 'GET' and url == API+'/folder':
            result = self.folder
        elif method == 'GET' and url == API:
            if self.search_override is not None:
                result = self.search_override
            else:
                matches = []
                for file in self.files.values():
                    if all(f"key='{key}' and value='{value}'" in params['q']
                           for key, value in file['properties'].items()):
                        matches.append({key: value for key, value in file.items() if key != 'data'})
                result = {'files': matches, 'incompleteSearch': False}
        elif method == 'GET' and params.get('alt') == 'media':
            result = self.files[url.split('/')[-1]]['data']
        elif method == 'POST' and url == UPLOAD:
            boundary = kwargs['headers']['Content-Type'].split('boundary=')[1]
            pieces = kwargs['data'].split(('--'+boundary).encode())
            metadata = json.loads(pieces[1].split(b'\r\n\r\n', 1)[1].rstrip(b'\r\n'))
            data = pieces[2].split(b'\r\n\r\n', 1)[1][:-2]
            identifier = f'file{len(self.files)+1}'
            self.files[identifier] = {**metadata, 'id': identifier, 'data': data,
                                      'size': str(len(data)), 'trashed': False}
            self.acls[identifier] = [{'type': 'user', 'role': 'owner'},
                                     {'type': 'user', 'role': 'reader'}]
            result = {'id': identifier}
        else:
            raise AssertionError('Unexpected offline HTTP path')
        reply = Reply(result, self.status)
        self.responses.append(reply)
        return reply

    def close(self):
        self.closed = True


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr('cold_drive_objects.secrets.token_hex', lambda _size: 'a'*32)
    session = DriveSession()
    return session, ColdDriveObjects(session, 'folder', writable=True)


def stored(transport, kind='catalog-page', data=b'original fixture'):
    session, writer = transport
    sha = hashlib.sha256(data).hexdigest()
    writer.put(kind, sha, data)
    return session, writer, sha, data


def test_verified_put_retry_and_distinct_read_only_client_share_properties(transport):
    session, writer, sha, data = stored(transport)
    reader = ColdDriveObjects(session, 'folder')
    assert reader.get('catalog-page', sha) == data
    writer.put('catalog-page', sha, data)
    assert len(session.files) == 1
    assert len([call for call in session.calls if call[0] == 'POST']) == 1
    assert all('appProperties' not in file for file in session.files.values())
    for _, _, kwargs in session.calls:
        assert kwargs['verify'] is True and kwargs['allow_redirects'] is False
        assert kwargs['timeout'] == (10, 30)
    assert all(reply.closed for reply in session.responses)


def test_runtime_put_is_blocked_before_any_network_or_refresh():
    session = DriveSession()
    with pytest.raises(DriveObjectError, match='READ_ONLY'):
        ColdDriveObjects(session, 'folder').put('catalog-page', 'a'*64, b'fixture')
    assert session.calls == []


def test_absence_is_verified_but_incomplete_or_denied_is_not(transport):
    session, writer = transport
    assert writer.get('catalog-page', 'a'*64) is None
    for override in ({'files': [], 'incompleteSearch': True},
                     {'files': [], 'incompleteSearch': False, 'nextPageToken': 'next'},
                     {'files': []}):
        session.search_override = override
        with pytest.raises(DriveObjectError, match='SEARCH_UNVERIFIED'):
            writer.get('catalog-page', 'a'*64)
    session.search_override = None
    session.status = 403
    with pytest.raises(DriveObjectError, match='HTTP_FAILED'):
        writer.get('catalog-page', 'a'*64)


@pytest.mark.parametrize('acl', [[], [{'type': 'anyone', 'role': 'reader'}],
                                 [{'type': 'domain', 'role': 'reader'}],
                                 [{'type': 'group', 'role': 'reader'}],
                                 [{'type': 'user', 'role': 'reader', 'deleted': True}]])
def test_folder_privacy_must_be_inspectable(transport, acl):
    session, writer = transport
    session.acls['folder'] = acl
    with pytest.raises(DriveObjectError, match='PRIVATE_ACCESS_UNVERIFIED'):
        writer.get('catalog-page', 'a'*64)


def test_public_file_inside_private_folder_is_also_blocked(transport):
    session, writer, sha, _ = stored(transport)
    session.acls['file1'].append({'type': 'anyone', 'role': 'reader'})
    with pytest.raises(DriveObjectError, match='PRIVATE_ACCESS_UNVERIFIED'):
        writer.get('catalog-page', sha)


@pytest.mark.parametrize('field,value', [('driveId', 'shared'), ('trashed', True),
                                        ('id', 'other'), ('mimeType', 'text/plain')])
def test_folder_metadata_mismatch_blocks(transport, field, value):
    session, writer = transport
    session.folder[field] = value
    with pytest.raises(DriveObjectError, match='FOLDER_UNVERIFIED'):
        writer.get('catalog-page', 'a'*64)


def test_folder_read_does_not_require_write_capability(transport):
    session, writer = transport
    session.folder['capabilities']['canAddChildren'] = False
    assert ColdDriveObjects(session, 'folder').get('catalog-page', 'a'*64) is None
    with pytest.raises(DriveObjectError, match='FOLDER_UNVERIFIED'):
        writer.put('catalog-page', hashlib.sha256(b'fixture').hexdigest(), b'fixture')


def test_duplicate_search_requires_review_no_arbitrary_first_file(transport):
    session, writer, sha, _ = stored(transport)
    file = {k: v for k, v in session.files['file1'].items() if k != 'data'}
    session.search_override = {'files': [file, file], 'incompleteSearch': False}
    with pytest.raises(DriveObjectError, match='SEARCH_UNVERIFIED'):
        writer.get('catalog-page', sha)


@pytest.mark.parametrize('field,value', [('parents', ['other']), ('size', '999999999'),
                                        ('mimeType', 'text/plain'), ('trashed', True),
                                        ('properties', {}), ('id', '../bad')])
def test_object_metadata_mismatch_never_downloads(transport, field, value):
    session, writer, sha, _ = stored(transport)
    file = {k: v for k, v in session.files['file1'].items() if k != 'data'}
    file[field] = value
    session.search_override = {'files': [file], 'incompleteSearch': False}
    before = len(session.calls)
    with pytest.raises(DriveObjectError):
        writer.get('catalog-page', sha)
    assert not any(c[2].get('params', {}).get('alt') == 'media' for c in session.calls[before:])


def test_corruption_and_oversize_are_not_overwritten(transport):
    session, writer, sha, data = stored(transport)
    session.files['file1']['data'] = b'x'*len(data)
    with pytest.raises(DriveObjectError, match='DIGEST_MISMATCH'):
        writer.put('catalog-page', sha, data)
    assert len([c for c in session.calls if c[0] == 'POST']) == 1
    session.files['file1']['data'] = b'x'*(CAPS['catalog-page']+1)
    with pytest.raises(DriveObjectError, match='SIZE_LIMIT'):
        writer.get('catalog-page', sha)


def test_uncertain_post_is_discovered_not_blindly_repeated(transport, monkeypatch):
    session, writer = transport
    original = session.request

    def uncertain(method, url, **kwargs):
        response = original(method, url, **kwargs)
        if method == 'POST':
            response.close()
            raise RuntimeError('PRIVATE_PROVIDER_BODY_MUST_NOT_ESCAPE')
        return response

    monkeypatch.setattr(session, 'request', uncertain)
    data = b'fixture'
    sha = hashlib.sha256(data).hexdigest()
    with pytest.raises(DriveObjectError, match='REQUEST_FAILED') as caught:
        writer.put('catalog-page', sha, data)
    assert 'PRIVATE_PROVIDER' not in str(caught.value)
    monkeypatch.setattr(session, 'request', original)
    writer.put('catalog-page', sha, data)
    assert len([c for c in session.calls if c[0] == 'POST']) == 1


@pytest.mark.parametrize('folder,mode', [('bad\'query', False), ('../bad', False),
                                        ('folder', 'false'), ('folder', 1)])
def test_ids_and_modes_are_strict(folder, mode):
    with pytest.raises(DriveObjectError):
        ColdDriveObjects(DriveSession(), folder, writable=mode)


def test_read_only_credentials_fixed_scope_endpoint_and_no_delegation(monkeypatch):
    loader = Mock(return_value=object())
    session = Mock()
    monkeypatch.setattr('google.oauth2.service_account.Credentials.from_service_account_info', loader)
    monkeypatch.setattr('google.auth.transport.requests.AuthorizedSession', session)
    info = {'type': 'service_account', 'token_uri': TOKEN_URI, 'client_email': 'fixture@example.test',
            'private_key': 'fixture-not-real', 'private_key_id': 'fixture'}
    viewer_session(info)
    assert loader.call_args.kwargs == {'scopes': [READ_SCOPE]}
    assert not any('subject' in str(call) for call in loader.call_args_list)
    for override in ({'token_uri': 'https://untrusted.test'}, {'private_key': ''},
                     {'type': 'authorized_user'}, {'universe_domain': 'untrusted.test'}):
        with pytest.raises(DriveObjectError):
            viewer_session({**info, **override})
    viewer_session({**info, 'subject': 'do-not-delegate', 'quota_project_id': 'do-not-forward'})
    assert set(loader.call_args.args[0]) == set(info)


def test_factory_errors_are_safe_and_session_closes(monkeypatch):
    monkeypatch.setattr('google.oauth2.service_account.Credentials.from_service_account_info',
                        Mock(side_effect=ValueError('PRIVATE_KEY_MUST_NOT_ESCAPE')))
    info = {'type': 'service_account', 'token_uri': TOKEN_URI, 'client_email': 'fixture@example.test',
            'private_key': 'fixture-not-real', 'private_key_id': 'fixture'}
    with pytest.raises(DriveObjectError) as caught:
        viewer_session(info)
    assert 'PRIVATE_KEY' not in str(caught.value)
    session = DriveSession()
    ColdDriveObjects(session, 'folder').close()
    assert session.closed


def test_private_protocol_metadata_is_not_license_or_public_share(transport):
    session, _, _, _ = stored(transport)
    assert session.files['file1']['properties']['storage-format'] == FORMAT
    assert set(session.files['file1']['properties']) == {'storage-format', 'storage-kind', 'storage-sha256'}
    assert all(method in ('GET', 'POST') for method, _, _ in session.calls)


@pytest.mark.parametrize('status', [200, 403])
def test_response_close_failure_never_exposes_provider_details(status):
    response = Reply({}, status)
    response.close = Mock(side_effect=RuntimeError('PRIVATE_PROVIDER_DETAIL'))
    session = Mock()
    session.request.return_value = response
    with pytest.raises(DriveObjectError, match='RESPONSE_CLOSE_FAILED') as caught:
        ColdDriveObjects(session, 'folder').check_folder()
    assert 'PRIVATE_PROVIDER_DETAIL' not in str(caught.value)


def test_session_close_failure_is_also_masked():
    session = Mock()
    session.close.side_effect = RuntimeError('PRIVATE_PROVIDER_DETAIL')
    with pytest.raises(DriveObjectError, match='CLOSE_FAILED') as caught:
        ColdDriveObjects(session, 'folder').close()
    assert 'PRIVATE_PROVIDER_DETAIL' not in str(caught.value)
