"""Windows per-user Credential Manager storage; no plaintext secret files."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import getpass
import json
from pathlib import Path
import sys
from typing import Any, Callable, cast

from drive_archive import ArchiveError, credentials
from research_integrity import IntegrityError
from research_replay_comparison import instant

NAMES = ('UPSTOX_ANALYTICS_TOKEN', 'FORWARD_TOKEN_EXPIRES_AT', 'DRIVE_OAUTH_TOKEN_JSON',
         'OPTION_CAPTURE_DRIVE_FOLDER_ID', 'FORWARD_CAPTURE_LICENSE_ACK')
PREFIX = 'KiranTrading/Forward/'
MAX_BYTES = 2560
MAX_OAUTH_FILE_BYTES = 64 * 1024


def read_oauth_file(path: Path) -> str:
    """Read bounded private JSON without changing it or disclosing its contents.

    Only the path travels through argv. Resolve links so a file in the repository
    cannot be used accidentally; the owner manages the original private file.
    """
    try:
        resolved = path.resolve(strict=True)
        if resolved.is_relative_to(Path(__file__).resolve().parent):
            raise IntegrityError('PRIVATE_OAUTH_FILE_REQUIRED')
        with resolved.open('rb') as handle:
            raw = handle.read(MAX_OAUTH_FILE_BYTES + 1)
        if len(raw) > MAX_OAUTH_FILE_BYTES:
            raise IntegrityError('PRIVATE_OAUTH_FILE_INVALID')
        info = json.loads(raw.decode('utf-8-sig'))
        cast(Callable[[Any], Any], credentials)(info)
        value = json.dumps(info, separators=(',', ':'), ensure_ascii=False)
        if len(value.encode('utf-8')) > MAX_BYTES:
            raise IntegrityError('PRIVATE_OAUTH_FILE_INVALID')
        return value
    except Exception:
        raise IntegrityError('PRIVATE_OAUTH_FILE_INVALID') from None


class Credential(ctypes.Structure):
    """Native CREDENTIALW layout; generic blobs contain UTF-8, not passwords in argv."""
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
                ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


def api() -> Any:
    """Bind only on explicit invocation; import never touches the credential store."""
    if sys.platform != 'win32':
        raise IntegrityError('WINDOWS_CREDENTIAL_MANAGER_REQUIRED')
    library = getattr(ctypes, 'WinDLL')('Advapi32.dll', use_last_error=True)
    library.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(ctypes.POINTER(Credential))]
    library.CredReadW.restype = wintypes.BOOL
    library.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    library.CredWriteW.restype = wintypes.BOOL
    library.CredFree.argtypes = [ctypes.c_void_p]
    library.CredFree.restype = None
    return library


def read_secret(name: str, *, library: Any = None) -> str:
    """Read only this application's fixed generic credential names; sanitized errors."""
    if name not in NAMES:
        raise IntegrityError('CREDENTIAL_NAME_INVALID')
    library = api() if library is None else library
    pointer = ctypes.POINTER(Credential)()
    if not library.CredReadW(PREFIX + name, 1, 0, ctypes.byref(pointer)):
        raise IntegrityError('PRIVATE_CREDENTIAL_REQUIRED')
    try:
        item = pointer.contents
        if item.CredentialBlobSize > MAX_BYTES or not item.CredentialBlobSize or not item.CredentialBlob:
            raise IntegrityError('PRIVATE_CREDENTIAL_INVALID')
        return ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize).decode('utf-8')
    finally:
        library.CredFree(pointer)


def write_secret(name: str, value: str, *, library: Any = None) -> None:
    """Persist under current Windows user; no export, delete, logging or SYSTEM use."""
    if name not in NAMES or not value or len(value.encode()) > MAX_BYTES:
        raise IntegrityError('PRIVATE_CREDENTIAL_INVALID')
    library = api() if library is None else library
    raw = value.encode('utf-8')
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    item = Credential(Type=1, TargetName=PREFIX + name, CredentialBlobSize=len(raw),
                      CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
                      Persist=2, UserName='forward-research')
    if not library.CredWriteW(ctypes.byref(item), 0):
        raise IntegrityError('PRIVATE_CREDENTIAL_STORE_FAILED')


def validate(values: dict[str, str]) -> None:
    """Validate the full setup before writing any credential; never refresh tokens."""
    if (set(values) != set(NAMES) or any(not value or len(value.encode()) > MAX_BYTES for value in values.values())
            or values['FORWARD_CAPTURE_LICENSE_ACK'] != 'true'):
        raise IntegrityError('PRIVATE_CREDENTIAL_CONFIG_INVALID')
    try:
        instant(values['FORWARD_TOKEN_EXPIRES_AT'])
        cast(Callable[[Any], Any], credentials)(json.loads(values['DRIVE_OAUTH_TOKEN_JSON']))
    except (ValueError, TypeError, ArchiveError):
        raise IntegrityError('PRIVATE_CREDENTIAL_CONFIG_INVALID') from None


def load() -> dict[str, str]:
    """Return secrets programmatically; caller restores its environment afterwards."""
    values = {name: read_secret(name) for name in NAMES}
    validate(values)
    return values


def main(argv: list[str] | None = None) -> int:
    """Explicit local hidden prompts only; no command-line secret arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', action='store_true')
    parser.add_argument('--drive-oauth-file', type=Path,
                        help='Private OAuth JSON file outside the repository; requires --store')
    args = parser.parse_args(argv)
    try:
        if not args.store:
            print('CREDENTIAL_SETUP_PREVIEW: no credentials read or written')
            return 0
        if not sys.stdin.isatty():
            raise IntegrityError('INTERACTIVE_PRIVATE_PROMPT_REQUIRED')
        oauth = read_oauth_file(args.drive_oauth_file) if args.drive_oauth_file else None
        values = {name: (oauth if name == 'DRIVE_OAUTH_TOKEN_JSON' and oauth is not None
                         else getpass.getpass(name + ' (hidden): ')) for name in NAMES}
        validate(values)
        for name in NAMES:
            write_secret(name, values[name])
        if load() != values:
            raise IntegrityError('PRIVATE_CREDENTIAL_READBACK_FAILED')
        print('PRIVATE_CREDENTIALS_STORED')
        return 0
    except Exception:
        print('BLOCKED: PRIVATE_CREDENTIAL_SETUP_FAILED')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
