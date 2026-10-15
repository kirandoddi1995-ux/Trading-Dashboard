"""Inert, owner-confirmed local session evidence preservation; stdlib only.

Select exact allowlisted files or subtrees, never an entire capsule or session
root. The explicit ISO day must match the source directory name (not fixed to
Oct 14). config.json is a frozen recipe and is permitted, but is never parsed.
Without --select, use only the known recipe, journal, input, quarantine,
versioned and receipt locations below. --select narrows that allowlist further.
No scheduler, producer, credential or network modules are imported.
The destination parent must ALREADY be private and preconfigured by the owner.
Permissions are queried, never repaired. Windows trusts only the current user,
SYSTEM and local Administrators (machine administrators are trusted); this is
not an owner-only or independent-custody claim. New Windows entries inherit
that verified ACL. POSIX entries use private creation modes, without chmod.

Writers MUST be paused by the owner throughout preservation. Matching before /
after hashes detect changes, not transient writes restored between checks, nor
an atomic multi-file snapshot. Filesystem adversaries changing ancestors during
the operation are outside this local owner-controlled workflow.

Owner first-preservation uses exact copies ONLY. SQLite is never opened:
even mode=ro can affect a WAL shm file. Any known SQLite sidecar or producer
lock blocks preservation, including when it is not selected. The owner must
pause writers separately; --confirm-preserve attests that they remain paused.
No SQLite backup, checkpoint, source repair or logical transformation occurs.
The full operational image, ops and scheduler root are NOT included.
No full-image or independent-custody claim is made.
Failure retains the new private destination; no overwrite, deletion or retry.
Only a completed manifest marks completion.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, BinaryIO, Callable, Never, NotRequired, TypedDict, cast


MAX_FILES = 4096
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_DEPTH = 12
CODE_ROOT = Path(__file__).absolute().parent
DATABASES = ('state/observations.sqlite', 'state/versioned-v1/journal.sqlite')
DIRECTORIES = frozenset({
    'state/inputs', 'state/quarantine-v1', 'state/quarantine-v1/snapshots',
    'state/quarantine-v1/receipts', 'state/versioned-v1',
    'state/versioned-v1/receipts',
})


class PreserveError(Exception):
    """Messages are fixed categories only; never include supplied values."""


def require(condition: bool, category: str) -> None:
    if not condition:
        raise PreserveError(category)


def allowed_file(name: str) -> bool:
    if name in {'config.json', 'state/quarantine-v1/policy.json',
                'state/versioned-v1/recipe.json'}:
        return True
    if name in DATABASES:
        return True
    patterns = (
        r'state/inputs/[0-9a-f]{64}\.json',
        r'state/(?:receipt|failure)-[0-9a-f]{32}\.json',
        r'state/quarantine-v1/snapshots/[0-9]{4}\.json',
        r'state/(?:quarantine-v1|versioned-v1)/receipts/(?:receipt|failure)-[0-9a-f]{32}\.json',
    )
    return any(re.fullmatch(pattern, name) is not None for pattern in patterns)


def selection(value: str) -> str:
    require(bool(value) and '\\' not in value and ':' not in value,
            'SELECTION_INVALID')
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in ('', '.', '..') for p in value.split('/')),
            'SELECTION_INVALID')
    require(value in DIRECTORIES or allowed_file(value), 'SELECTION_NOT_ALLOWLISTED')
    return value


def checked_path(path: Path, *, missing_leaf: bool = False) -> None:
    require(path.is_absolute() and '..' not in path.parts, 'ABSOLUTE_PATH_REQUIRED')
    require(not str(path).startswith(('\\\\', '//')), 'LOCAL_PATH_REQUIRED')
    require(not any(part.lower() in {'.venv', 'capsule', 'secrets', 'credentials',
                'credentialstores', '.aws', '.ssh', 'ops', 'tasks', 'scheduler-receipts',
                'task-plans'} for part in path.parts), 'PROTECTED_SCOPE_FORBIDDEN')
    if os.name == 'nt':
        import ctypes
        drive_type = ctypes.windll.kernel32.GetDriveTypeW
        drive_type.argtypes = [ctypes.c_wchar_p]
        require(drive_type(path.anchor) != 4, 'LOCAL_PATH_REQUIRED')
    # lstat every ancestor, including dangling links and Windows reparse points.
    for item in reversed((path, *path.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            require(missing_leaf and item == path, 'PATH_MISSING')
            continue
        require(not stat.S_ISLNK(info.st_mode)
                and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'LINK_OR_REPARSE_FORBIDDEN')
        if item != path:
            require(stat.S_ISDIR(info.st_mode), 'PATH_INVALID')


def external_paths(source: Path, destination: Path, day: date) -> None:
    checked_path(source)
    checked_path(destination, missing_leaf=True)
    require(source.name == day.isoformat() and source.is_dir(), 'SESSION_DATE_MISMATCH')
    source_real, dest_real = source.resolve(), destination.resolve()
    require(not source_real.is_relative_to(CODE_ROOT.resolve())
            and not dest_real.is_relative_to(CODE_ROOT.resolve()), 'EXTERNAL_PATH_REQUIRED')
    require(not dest_real.is_relative_to(source_real)
            and not source_real.is_relative_to(dest_real), 'SOURCE_DESTINATION_OVERLAP')
    require(not os.path.lexists(destination), 'DESTINATION_EXISTS')
    require(destination.parent.is_dir(), 'DESTINATION_PARENT_REQUIRED')
    private_permissions(destination.parent)


def default_selection(source: Path) -> list[str]:
    """Fixed session roots; only shallow receipt names inspected in state."""
    candidates = ['config.json', DATABASES[0], 'state/inputs',
                  'state/quarantine-v1', 'state/versioned-v1']
    result = [name for name in candidates if os.path.lexists(source / name)]
    state = source / 'state'
    if os.path.lexists(state):
        checked_path(state)
        require(state.is_dir(), 'PATH_INVALID')
        with os.scandir(state) as children:
            for index, child in enumerate(children):
                require(index < MAX_FILES * 2, 'TREE_BOUND')
                name = 'state/' + child.name
                if re.fullmatch(r'state/(?:receipt|failure)-[0-9a-f]{32}\.json', name):
                    result.append(name)
    return result


@dataclass(frozen=True)
class Fingerprint:
    size: int
    sha256: str
    identity: tuple[int, int, int, int, int]


class EvidenceRecord(TypedDict):
    relative_path: str
    kind: str
    size: int
    source_before_sha256: str
    preserved_sha256: str
    source_after_sha256: NotRequired[str]


def identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    # Windows lstat/fstat disagree about deprecated ctime on Python 3.13.
    change = getattr(info, 'st_birthtime_ns', info.st_ctime_ns) if os.name == 'nt' else info.st_ctime_ns
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, change)


def fingerprint(path: Path) -> Fingerprint:
    checked_path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'REGULAR_SINGLE_LINK_REQUIRED')
    require(before.st_size <= MAX_FILE_BYTES, 'SIZE_BOUND')
    digest = hashlib.sha256()
    count = 0
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        require(identity(os.fstat(stream.fileno())) == identity(before), 'SOURCE_CHANGED')
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            require(count <= MAX_FILE_BYTES, 'SIZE_BOUND')
            digest.update(chunk)
        require(identity(os.fstat(stream.fileno())) == identity(before), 'SOURCE_CHANGED')
    require(identity(path.lstat()) == identity(before) and count == before.st_size,
            'SOURCE_CHANGED')
    return Fingerprint(count, digest.hexdigest(), identity(before))


def inventory(source: Path, selected: tuple[str, ...]) -> tuple[list[str], list[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    entries = 0

    def visit(name: str, depth: int) -> None:
        nonlocal entries
        entries += 1
        require(entries <= MAX_FILES * 2 and depth <= MAX_DEPTH, 'TREE_BOUND')
        path = source / name
        checked_path(path)
        require(path.resolve().is_relative_to(source.resolve()), 'SOURCE_CONTAINMENT')
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            require(name in DIRECTORIES, 'SELECTION_NOT_ALLOWLISTED')
            directories.add(name)
            with os.scandir(path) as children:
                for child in children:
                    visit(name + '/' + child.name, depth + 1)
        else:
            require(allowed_file(name), 'SELECTION_NOT_ALLOWLISTED')
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                    'REGULAR_SINGLE_LINK_REQUIRED')
            files.add(name)
            require(len(files) <= MAX_FILES, 'TREE_BOUND')

    for name in selected:
        visit(name, 0)
    return sorted(files), sorted(directories)


def quiescence_guards(source: Path) -> None:
    """Probe only exact public-layout guards, never enumerate other state."""
    for db in DATABASES:
        database = source / db
        for suffix in ('-wal', '-shm', '-journal'):
            path = Path(str(database) + suffix)
            # Check existing ancestors without traversing links. A missing
            # namespace is fine, but a linked namespace must be refused.
            for ancestor in reversed((path, *path.parents)):
                if os.path.lexists(ancestor):
                    checked_path(ancestor)
            require(not os.path.lexists(path), 'SQLITE_SIDECARS_REQUIRE_QUIESCENCE')
        for path in (database.with_suffix('.producer-lock'), Path(str(database) + '.producer-lock')):
            for ancestor in reversed((path, *path.parents)):
                if os.path.lexists(ancestor):
                    checked_path(ancestor)
            require(not os.path.lexists(path), 'PRODUCER_LOCK_REQUIRES_REVIEW')


def snapshot(source: Path, selected: tuple[str, ...]) -> tuple[dict[str, Fingerprint], list[str]]:
    quiescence_guards(source)
    names, directories = inventory(source, selected)
    result: dict[str, Fingerprint] = {}
    total = 0
    for name in names:
        result[name] = fingerprint(source / name)
        total += result[name].size
        require(total <= MAX_TOTAL_BYTES, 'SIZE_BOUND')
    return result, directories


def windows_private(path: Path) -> None:
    """Read-only bounded owner/DACL query; trust user, SYSTEM and Administrators."""
    import ctypes
    from ctypes import wintypes

    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                       wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    adv.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    adv.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    adv.GetSecurityDescriptorOwner.argtypes = [ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    adv.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    token = wintypes.HANDLE()
    def sid_name(sid: ctypes.c_void_p) -> str:
        sid_text = wintypes.LPWSTR()
        try:
            require(bool(adv.ConvertSidToStringSidW(sid, ctypes.byref(sid_text))),
                    'PRIVATE_PERMISSIONS_UNVERIFIED')
            return str(sid_text.value)
        finally:
            if sid_text:
                kernel.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))

    try:
        require(bool(adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token))),
                'PRIVATE_PERMISSIONS_UNVERIFIED')
        size = wintypes.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        require(0 < size.value <= 65536, 'PRIVATE_PERMISSIONS_UNVERIFIED')
        buffer = ctypes.create_string_buffer(size.value)
        require(bool(adv.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size))),
                'PRIVATE_PERMISSIONS_UNVERIFIED')
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        trusted = {sid_name(sid), 'S-1-5-18', 'S-1-5-32-544'}
        size = wintypes.DWORD()
        adv.GetFileSecurityW(str(path), 5, None, 0, ctypes.byref(size))
        require(0 < size.value <= 65536, 'PRIVATE_PERMISSIONS_UNVERIFIED')
        descriptor = ctypes.create_string_buffer(size.value)
        require(bool(adv.GetFileSecurityW(str(path), 5, descriptor, size, ctypes.byref(size))),
                'PRIVATE_PERMISSIONS_UNVERIFIED')
        owner, acl = ctypes.c_void_p(), ctypes.c_void_p()
        defaulted, present = wintypes.BOOL(), wintypes.BOOL()
        require(bool(adv.GetSecurityDescriptorOwner(descriptor, ctypes.byref(owner),
            ctypes.byref(defaulted))) and bool(owner), 'PRIVATE_PERMISSIONS_UNVERIFIED')
        require(sid_name(owner) in trusted, 'PRIVATE_PERMISSIONS_EXPOSED')
        # OWNER RIGHTS grants only to the already-verified descriptor owner;
        # Python's Windows private temporary directories use this standard SID.
        trusted.add('S-1-3-4')
        require(bool(adv.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present),
            ctypes.byref(acl), ctypes.byref(defaulted))) and bool(present.value) and bool(acl),
            'PRIVATE_PERMISSIONS_EXPOSED')
        header = ctypes.string_at(acl, 8)
        count = int.from_bytes(header[4:6], 'little')
        require(1 <= count <= 128, 'PRIVATE_PERMISSIONS_UNVERIFIED')
        effective_allow = False
        for index in range(count):
            ace = ctypes.c_void_p()
            require(bool(adv.GetAce(acl, index, ctypes.byref(ace))), 'PRIVATE_PERMISSIONS_UNVERIFIED')
            raw = ctypes.string_at(ace, 8)
            kind, flags = raw[0], raw[1]
            require(kind in (0, 1) and int.from_bytes(raw[2:4], 'little') >= 16,
                    'PRIVATE_PERMISSIONS_UNVERIFIED')
            principal = sid_name(ctypes.c_void_p(cast(int, ace.value) + 8))
            # CREATOR OWNER is allowed only as an inheritance template.
            require(principal in trusted or (principal == 'S-1-3-0' and bool(flags & 8)),
                    'PRIVATE_PERMISSIONS_EXPOSED')
            if kind == 0 and not flags & 8 and principal in trusted:
                effective_allow = True
        require(effective_allow, 'PRIVATE_PERMISSIONS_UNVERIFIED')
    finally:
        if token:
            kernel.CloseHandle(token)


def private_permissions(path: Path) -> None:
    """Verify existing permissions without changing any file or directory."""
    checked_path(path)
    if os.name == 'nt':
        windows_private(path)
    else:
        info = path.stat()
        getuid = cast(Callable[[], int], getattr(os, 'getuid'))
        require(info.st_uid == getuid() and not stat.S_IMODE(info.st_mode) & 0o077,
                'PRIVATE_PERMISSIONS_EXPOSED')
        required = 0o700 if path.is_dir() else 0o600
        require(stat.S_IMODE(info.st_mode) & required == required,
                'PRIVATE_PERMISSIONS_UNVERIFIED')


def private_directory(path: Path) -> None:
    checked_path(path, missing_leaf=True)
    private_permissions(path.parent)
    # Windows 3.13 treats mkdir(0700) as a special DACL request; use ordinary
    # inheritance there. POSIX creation mode is allowed, never chmod/repair.
    path.mkdir(mode=0o777 if os.name == 'nt' else 0o700)
    private_permissions(path)


def new_file(path: Path) -> BinaryIO:
    checked_path(path, missing_leaf=True)
    private_permissions(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        private_permissions(path)
        return os.fdopen(fd, 'wb')
    except Exception:
        os.close(fd)
        raise


def make_parents(root: Path, relative: str) -> Path:
    path = root / relative
    for parent in reversed(path.parent.parents):
        if parent.is_relative_to(root) and not parent.exists():
            private_directory(parent)
    if not path.parent.exists():
        private_directory(path.parent)
    return path


def exact_copy(source: Path, target: Path, expected: Fingerprint) -> None:
    require(fingerprint(source) == expected, 'SOURCE_CHANGED')
    fd = os.open(source, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as incoming, new_file(target) as outgoing:
        require(identity(os.fstat(incoming.fileno())) == expected.identity, 'SOURCE_CHANGED')
        count = 0
        while chunk := incoming.read(1024 * 1024):
            count += len(chunk)
            require(count <= expected.size, 'SOURCE_CHANGED')
            outgoing.write(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    copied = fingerprint(target)
    require((copied.size, copied.sha256) == (expected.size, expected.sha256), 'COPY_HASH_MISMATCH')


def preserve(source: Path, destination: Path, day: date, selected: list[str] | None = None, *,
             confirm: bool = False) -> dict[str, Any]:
    """Preview returns before path validation, enumeration, clocks or any IO."""
    if not confirm:
        return {'status': 'PREVIEW', 'reads': 0, 'writes': 0, 'network_calls': 0,
                'credential_reads': 0, 'approval_authority': False,
                'scope': 'SELECTED_SESSION_ONLY_NOT_FULL_IMAGE_OPS_OR_SCHEDULER_ROOT',
                'confirmation_attests_writers_paused': True}
    require(type(day) is date, 'SESSION_DATE_REQUIRED')
    external_paths(source, destination, day)
    quiescence_guards(source)
    default_scope = selected is None
    if selected is None:
        selected = default_selection(source)
    require(0 < len(selected) <= MAX_FILES, 'SELECTION_REQUIRED')
    names = tuple(sorted({selection(name) for name in selected}))
    before, directories = snapshot(source, names)
    private_directory(destination)
    originals = destination / 'originals'
    private_directory(originals)
    for directory in directories:
        path = make_parents(originals, directory)
        if not path.exists():
            private_directory(path)
    records: list[EvidenceRecord] = []
    for name, info in before.items():
        exact_copy(source / name, make_parents(originals, name), info)
        records.append({'relative_path': name, 'kind': 'EXACT_FILE',
            'size': info.size, 'source_before_sha256': info.sha256,
            'preserved_sha256': info.sha256})
    after, after_directories = snapshot(source, names)
    require(before == after and directories == after_directories, 'SOURCE_CHANGED')
    if default_scope:
        require(tuple(sorted({selection(name) for name in default_selection(source)})) == names,
                'SOURCE_CHANGED')
    # Rehash every retained evidence file before publishing completion.
    for record in records:
        info = fingerprint(originals / record['relative_path'])
        require(info.sha256 == record['preserved_sha256'], 'COPY_HASH_MISMATCH')
        record['source_after_sha256'] = after[record['relative_path']].sha256
    manifest = {'format': 'forward-selected-evidence-v1', 'status': 'COMPLETE',
                'session_date': day.isoformat(), 'selected': names, 'directories': directories,
                'files': records, 'sqlite_method': 'EXACT_BYTES_NO_SQLITE_OPEN',
                'database_integrity_checked': False,
                'permissions': 'VERIFIED_INHERITANCE_NO_PERMISSION_CHANGES',
                'machine_administrators_trusted': os.name == 'nt', 'owner_only_claim': False,
                'quiescence': 'OWNER_ATTESTED_NOT_INDEPENDENTLY_PROVEN',
                'source_before_after_match': True, 'full_image': False,
                'independent_custody': False, 'atomic_snapshot': False,
                'ops_included': False, 'scheduler_root_included': False,
                'approval_authority': False}
    with new_file(destination / 'manifest.json') as stream:
        stream.write((json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    return {'status': 'PRESERVED_SELECTED_EVIDENCE', 'files': len(records),
            'network_calls': 0, 'credential_reads': 0,
            'source_writes': 0, 'approval_authority': False, 'full_image': False,
            'independent_custody': False, 'ops_included': False, 'scheduler_root_included': False}


class RedactedParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise PreserveError('ARGUMENTS_INVALID')


def main(argv: list[str] | None = None) -> int:
    parser = RedactedParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--source', '--source-session', dest='source', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--session-date', required=True, type=date.fromisoformat)
    parser.add_argument('--select', action='append',
                        help='Exact allowlisted relative file/subtree; repeat to narrow default scope')
    parser.add_argument('--confirm-preserve', action='store_true',
                        help='Attest owner authorization and writers paused for the entire exact copy')
    try:
        args = parser.parse_args(argv)
        result = preserve(args.source, args.destination, args.session_date, args.select,
                          confirm=args.confirm_preserve)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        category = str(error) if isinstance(error, PreserveError) else 'PRESERVATION_FAILED'
        print(json.dumps({'status': 'BLOCKED', 'category': category,
                          'partial_destination_retained_if_created': True,
                          'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
