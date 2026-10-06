"""Private content-addressed Drive transport for cold storage, with read-only mode.

No connection, credential loading or network at import. The owner supplies a
separate Viewer identity for runtime reads; never reuse the archiver's write
OAuth credential in the dashboard. Custom properties are cross-client metadata,
not public sharing. Every object is checked against a pinned SHA and private ACL.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
import hashlib
import json
import re
import secrets
from typing import Protocol, cast

from catalog_receipts import MAX_BYTES as RECEIPT_BYTES
from cold_catalog import PAGE_BYTES
from ledger_archive_publication import Kind
from ledger_segments import MAX_FILE_BYTES

API = 'https://www.googleapis.com/drive/v3/files'
UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files'
FORMAT = 'cold-objects-v1'
READ_SCOPE = 'https://www.googleapis.com/auth/drive.readonly'
TOKEN_URI = 'https://oauth2.googleapis.com/token'
ID = re.compile(r'[A-Za-z0-9_-]{1,200}')
SHA = re.compile(r'[0-9a-f]{64}')
JSON_BYTES = 256 * 1024
CAPS = {'ledger-segment': MAX_FILE_BYTES, 'catalog-page': PAGE_BYTES,
        'root-receipt': RECEIPT_BYTES}


class DriveObjectError(ValueError):
    """Safe error code; never HTTP bodies, payloads or credential details."""


class Response(Protocol):
    status_code: int

    def iter_content(self, chunk_size: int) -> Iterator[bytes]: ...

    def close(self) -> None: ...


class Session(Protocol):
    def request(self, method: str, url: str, **kwargs: object) -> Response: ...

    def close(self) -> None: ...


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise DriveObjectError('COLD_DRIVE_ID_INVALID')
    return value


def _identity(kind: Kind, digest: str) -> dict[str, str]:
    if kind not in CAPS or not isinstance(digest, str) or not SHA.fullmatch(digest):
        raise DriveObjectError('COLD_DRIVE_OBJECT_INVALID')
    return {'storage-format': FORMAT, 'storage-kind': kind, 'storage-sha256': digest}


def _map(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise DriveObjectError('COLD_DRIVE_METADATA_INVALID')
    return cast(dict[str, object], value)


def viewer_session(info: Mapping[str, object]) -> Session:
    """Build a non-delegated, read-only service-account session locally.

    Folder Viewer sharing is a separate owner step. Only the fixed Google token
    endpoint is accepted. Parsing never prints the JSON/key or refreshes tokens.
    """
    if (info.get('type') != 'service_account' or info.get('token_uri') != TOKEN_URI
            or info.get('universe_domain', 'googleapis.com') != 'googleapis.com'
            or any(not isinstance(info.get(name), str) or not info[name]
                   for name in ('client_email', 'private_key', 'private_key_id'))):
        raise DriveObjectError('COLD_DRIVE_VIEWER_CONFIGURATION_INVALID')
    try:
        from google.oauth2.service_account import Credentials
        from google.auth.transport.requests import AuthorizedSession
        # Do not forward delegation, quota-project or alternate-universe fields
        # from a supplied credential document into the authentication transport.
        selected = {name: info[name] for name in (
            'type', 'token_uri', 'client_email', 'private_key', 'private_key_id')}
        credentials = Credentials.from_service_account_info(selected, scopes=[READ_SCOPE])
        return cast(Session, AuthorizedSession(credentials))
    except Exception:
        raise DriveObjectError('COLD_DRIVE_VIEWER_CONFIGURATION_INVALID') from None


class ColdDriveObjects:
    """GET-only by default; explicit private worker mode may create, never replace.

    This implementation deliberately supports My Drive only. Ambiguous/incomplete
    searches, shared-drive scope or uninspectable permissions block use. No delete,
    PATCH, redirect, arbitrary URL or response-body logging path exists.
    """

    def __init__(self, session: Session, folder_id: str, *, writable: bool = False):
        if type(writable) is not bool:
            raise DriveObjectError('COLD_DRIVE_MODE_INVALID')
        self.session = session
        self.folder_id = _identifier(folder_id)
        self.writable = writable

    def close(self) -> None:
        """Close the owned session without revealing provider exceptions."""
        try:
            self.session.close()
        except Exception:
            raise DriveObjectError('COLD_DRIVE_CLOSE_FAILED') from None

    def _bytes(self, method: str, url: str, cap: int, **kwargs: object) -> bytes:
        if method not in ('GET', 'POST') or (method == 'POST' and not self.writable):
            raise DriveObjectError('COLD_DRIVE_READ_ONLY')
        response: Response | None = None
        try:
            response = self.session.request(method, url, timeout=(10, 30), stream=True,
                                            verify=True, allow_redirects=False, **kwargs)
            if type(response.status_code) is not int or not 200 <= response.status_code < 300:
                raise DriveObjectError('COLD_DRIVE_HTTP_FAILED')
            data = bytearray()
            for chunk in response.iter_content(65536):
                if not isinstance(chunk, bytes):
                    raise DriveObjectError('COLD_DRIVE_RESPONSE_INVALID')
                if len(data) + len(chunk) > cap:
                    raise DriveObjectError('COLD_DRIVE_SIZE_LIMIT')
                data.extend(chunk)
            return bytes(data)
        except DriveObjectError:
            raise
        except Exception:
            raise DriveObjectError('COLD_DRIVE_REQUEST_FAILED') from None
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    raise DriveObjectError('COLD_DRIVE_RESPONSE_CLOSE_FAILED') from None

    def _json(self, method: str, url: str, **kwargs: object) -> dict[str, object]:
        try:
            return _map(json.loads(self._bytes(method, url, JSON_BYTES, **kwargs)))
        except (ValueError, UnicodeError) as exc:
            if isinstance(exc, DriveObjectError):
                raise
            raise DriveObjectError('COLD_DRIVE_METADATA_INVALID') from None

    def _private(self, file_id: str) -> None:
        info = self._json('GET', f'{API}/{_identifier(file_id)}/permissions',
                          params={'pageSize': 100, 'fields': 'permissions(type,role,deleted),nextPageToken'})
        permissions = info.get('permissions')
        if (info.get('nextPageToken') or not isinstance(permissions, list) or not permissions
                or any(not isinstance(p, dict) or p.get('type') != 'user'
                       or p.get('role') not in ('owner', 'writer', 'reader', 'commenter')
                       or p.get('deleted') is True for p in permissions)):
            raise DriveObjectError('COLD_DRIVE_PRIVATE_ACCESS_UNVERIFIED')

    def check_folder(self) -> None:
        """Inspect private ACL using this actual identity; do not trust a saved flag."""
        info = self._json('GET', f'{API}/{self.folder_id}', params={
            'fields': 'id,mimeType,trashed,driveId,capabilities(canAddChildren)'})
        capabilities = info.get('capabilities')
        if (info.get('id') != self.folder_id or info.get('trashed') is not False
                or info.get('mimeType') != 'application/vnd.google-apps.folder'
                or info.get('driveId')
                or (self.writable and (not isinstance(capabilities, dict)
                                       or capabilities.get('canAddChildren') is not True))):
            raise DriveObjectError('COLD_DRIVE_FOLDER_UNVERIFIED')
        self._private(self.folder_id)

    def _find(self, kind: Kind, digest: str) -> dict[str, object] | None:
        properties = _identity(kind, digest)
        clauses = [f"'{self.folder_id}' in parents", 'trashed=false']
        clauses.extend(f"properties has {{ key='{key}' and value='{value}' }}"
                       for key, value in properties.items())
        info = self._json('GET', API, params={'q': ' and '.join(clauses), 'pageSize': 2,
            'fields': 'files(id,parents,trashed,mimeType,size,properties,driveId),nextPageToken,incompleteSearch'})
        files = info.get('files')
        if (not isinstance(files, list) or info.get('nextPageToken')
                or info.get('incompleteSearch') is not False or len(files) > 1):
            raise DriveObjectError('COLD_DRIVE_SEARCH_UNVERIFIED')
        if not files:
            return None
        file = _map(files[0])
        _identifier(file.get('id'))
        size = file.get('size')
        if (file.get('parents') != [self.folder_id] or file.get('trashed') is not False
                or file.get('mimeType') != 'application/octet-stream' or file.get('driveId')
                or file.get('properties') != properties
                or not isinstance(size, str) or not re.fullmatch(r'[0-9]{1,10}', size)
                or not 1 <= int(size) <= CAPS[kind]):
            raise DriveObjectError('COLD_DRIVE_OBJECT_METADATA_MISMATCH')
        return file

    def _download(self, file: dict[str, object], kind: Kind, digest: str) -> bytes:
        identifier = _identifier(file['id'])
        self._private(identifier)
        data = self._bytes('GET', f'{API}/{identifier}', CAPS[kind], params={'alt': 'media'})
        if len(data) != int(cast(str, file['size'])) or hashlib.sha256(data).hexdigest() != digest:
            raise DriveObjectError('COLD_DRIVE_OBJECT_DIGEST_MISMATCH')
        return data

    def get(self, kind: Kind, digest: str) -> bytes | None:
        """Verified missing object is None; denied/incomplete/corrupt never is."""
        _identity(kind, digest)
        self.check_folder()
        file = self._find(kind, digest)
        return None if file is None else self._download(file, kind, digest)

    def put(self, kind: Kind, digest: str, data: bytes) -> None:
        """Create once; retry discovers and verifies, never overwrites or deletes."""
        if not self.writable:
            raise DriveObjectError('COLD_DRIVE_READ_ONLY')
        properties = _identity(kind, digest)
        if (not isinstance(data, bytes) or not 1 <= len(data) <= CAPS[kind]
                or hashlib.sha256(data).hexdigest() != digest):
            raise DriveObjectError('COLD_DRIVE_OBJECT_INVALID')
        self.check_folder()
        existing = self._find(kind, digest)
        if existing is not None:
            if self._download(existing, kind, digest) != data:
                raise DriveObjectError('COLD_DRIVE_OBJECT_CONFLICT')
            return
        metadata = {'name': f'{FORMAT}-{kind}-{digest}.bin', 'parents': [self.folder_id],
                    'mimeType': 'application/octet-stream', 'properties': properties}
        boundary = 'cold_' + secrets.token_hex(16)
        body = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode()
                + json.dumps(metadata).encode() +
                f'\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
                + data + f'\r\n--{boundary}--\r\n'.encode())
        created = self._json('POST', UPLOAD, params={'uploadType': 'multipart', 'fields': 'id'},
                             data=body, headers={'Content-Type': f'multipart/related; boundary={boundary}'})
        identifier = _identifier(created.get('id'))
        # Query discovery through the same cross-client namespace and check ACL
        # and bytes. A successful POST alone is not archive evidence.
        file = self._find(kind, digest)
        if file is None or file['id'] != identifier or self._download(file, kind, digest) != data:
            raise DriveObjectError('COLD_DRIVE_UPLOAD_UNVERIFIED')
