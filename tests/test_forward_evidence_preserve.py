"""Offline temporary fixtures only; run with stdlib unittest on Linux/Windows."""
from contextlib import closing, redirect_stdout
from datetime import date
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from typing import Any, Callable, cast
from unittest.mock import patch

import forward_evidence_preserve as evidence


DAY = date(2026, 10, 14)
RECEIPT = 'receipt-' + 'a' * 32 + '.json'


class PreservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / DAY.isoformat()
        self.source.mkdir()
        self.destination = self.root / 'new-private-evidence'
        (self.source / 'config.json').write_bytes(b'{"recipe":"fixture only"}\r\n')

    def put(self, name: str, raw: bytes = b'fixture\x00\xff\r\n') -> Path:
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def preserve(self, selected: list[str] | None = None) -> dict[str, Any]:
        return evidence.preserve(self.source, self.destination, DAY,
                                 selected or ['config.json'], confirm=True)

    def arguments(self, *extra: str) -> list[str]:
        return ['--source', str(self.source), '--destination', str(self.destination),
                '--session-date', DAY.isoformat(), '--select', 'config.json', *extra]

    def manifest(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads((self.destination / 'manifest.json').read_bytes()))

    def test_preview_has_zero_io_even_invalid_paths_and_selections(self) -> None:
        with patch.object(evidence, 'external_paths', side_effect=AssertionError), \
                patch.object(evidence, 'snapshot', side_effect=AssertionError), \
                patch.object(Path, 'lstat', side_effect=AssertionError), \
                patch.object(os, 'open', side_effect=AssertionError), \
                patch.object(sqlite3, 'connect', side_effect=AssertionError):
            output = io.StringIO()
            with redirect_stdout(output):
                result = evidence.main(self.arguments())
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output.getvalue())['reads'], 0)
            preview = evidence.preserve(Path('bad'), Path('bad'), DAY, ['../secrets'])
            self.assertEqual(preview['writes'], 0)
        self.assertFalse(self.destination.exists())

    def test_import_is_inert_stdlib_only(self) -> None:
        script = """
import sys, argparse, dataclasses, datetime, hashlib, json, os, pathlib, re, stat
def audit(event, args):
    if event in ('os.scandir', 'socket.connect', 'sqlite3.connect'):
        raise AssertionError(event)
    if event == 'open' and not str(args[0]).endswith(('.py', '.pyc')):
        raise AssertionError('non-code read')
sys.addaudithook(audit)
import forward_evidence_preserve
assert not any(x in sys.modules for x in ('forward_windows_credentials', 'requests'))
"""
        completed = subprocess.run([sys.executable, '-B', '-c', script],
                                   cwd=evidence.CODE_ROOT, capture_output=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())

    def test_exact_bytes_hashes_and_claim_limits(self) -> None:
        name = 'state/inputs/' + 'b' * 64 + '.json'
        self.put(name)
        self.put('state/' + RECEIPT)
        result = self.preserve(['config.json', 'state/inputs', 'state/' + RECEIPT])
        self.assertEqual(result['files'], 3)
        manifest = self.manifest()
        for record in manifest['files']:
            relative = record['relative_path']
            self.assertEqual((self.destination / 'originals' / relative).read_bytes(),
                             (self.source / relative).read_bytes())
            self.assertEqual(record['source_before_sha256'], record['source_after_sha256'])
            self.assertEqual(record['preserved_sha256'], record['source_after_sha256'])
        self.assertFalse(manifest['full_image'])
        self.assertFalse(manifest['independent_custody'])
        self.assertNotIn(str(self.source), json.dumps(manifest))
        self.assertNotIn(str(self.destination), json.dumps(result))

    def test_empty_selected_directory_preserved(self) -> None:
        (self.source / 'state/inputs').mkdir(parents=True)
        self.preserve(['state/inputs'])
        self.assertTrue((self.destination / 'originals/state/inputs').is_dir())
        self.assertEqual(self.manifest()['directories'], ['state/inputs'])

    def test_explicit_day_not_hardcoded(self) -> None:
        other = date(2026, 10, 15)
        self.source.rename(self.root / other.isoformat())
        self.source = self.root / other.isoformat()
        result = evidence.preserve(self.source, self.destination, other, ['config.json'],
                                   confirm=True)
        self.assertEqual(result['files'], 1)

    def test_date_mismatch(self) -> None:
        with self.assertRaisesRegex(evidence.PreserveError, 'SESSION_DATE_MISMATCH'):
            evidence.preserve(self.source, self.destination, date(2026, 10, 15),
                              ['config.json'], confirm=True)
        self.assertFalse(self.destination.exists())

    def test_confirmation_attests_quiescence(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(evidence.main(self.arguments('--confirm-preserve')), 0)
        self.assertEqual(self.manifest()['quiescence'], 'OWNER_ATTESTED_NOT_INDEPENDENTLY_PROVEN')

    def test_exact_runbook_flags_default_bounded_allowlist(self) -> None:
        self.put('state/' + RECEIPT)
        self.put('state/credentialstores/never-read')
        output = io.StringIO()
        args = ['--source', str(self.source), '--destination', str(self.destination),
                '--session-date', DAY.isoformat()]
        with redirect_stdout(output):
            self.assertEqual(evidence.main(args), 0)
            self.assertEqual(evidence.main([*args, '--confirm-preserve']), 0)
        self.assertEqual(len(self.manifest()['files']), 2)
        self.assertFalse(self.manifest()['ops_included'])
        self.assertFalse(self.manifest()['scheduler_root_included'])

    def test_no_default_enumeration_of_unselected_stores(self) -> None:
        self.put('state/secrets/do-not-read', b'credential marker')
        self.put('.venv/do-not-read')
        with patch.object(os, 'scandir', side_effect=AssertionError('no directory enumeration')):
            self.preserve()
        self.assertEqual(len(self.manifest()['files']), 1)

    def test_selection_rejects_traversal_and_unknown_scope(self) -> None:
        for name in ('', '.', 'state', '../config.json', '/config.json', 'state/../config.json',
                     'config.json/', './config.json', 'state//inputs', 'state\\inputs',
                     'C:/config.json', '.venv', 'ops', 'secrets', 'state/credentials.json'):
            with self.subTest(name=name), self.assertRaises(evidence.PreserveError):
                self.preserve([name])
        self.assertFalse(self.destination.exists())

    def test_unknown_file_in_selected_tree_blocks_before_copy(self) -> None:
        self.put('state/inputs/secret.json')
        with self.assertRaisesRegex(evidence.PreserveError, 'NOT_ALLOWLISTED'):
            self.preserve(['state/inputs'])
        self.assertFalse(self.destination.exists())

    def test_no_selections(self) -> None:
        with self.assertRaisesRegex(evidence.PreserveError, 'SELECTION_REQUIRED'):
            evidence.preserve(self.source, self.destination, DAY, [], confirm=True)

    def test_overlapping_selection_deduplicated(self) -> None:
        name = 'state/inputs/' + 'c' * 64 + '.json'
        self.put(name)
        self.preserve(['state/inputs', name, name])
        self.assertEqual(len(self.manifest()['files']), 1)

    def test_destination_existing_or_overlapping(self) -> None:
        for target in (self.source, self.source / 'new', self.root):
            with self.subTest(target=target), self.assertRaises(evidence.PreserveError):
                evidence.preserve(self.source, target, DAY, ['config.json'], confirm=True)
        self.destination.mkdir()
        marker = self.destination / 'marker'
        marker.write_bytes(b'keep')
        with self.assertRaisesRegex(evidence.PreserveError, 'DESTINATION_EXISTS'):
            self.preserve()
        self.assertEqual(marker.read_bytes(), b'keep')

    def test_relative_and_parent_traversal_paths(self) -> None:
        for target in (Path('relative'), self.root / '..' / self.root.name / 'new'):
            with self.assertRaisesRegex(evidence.PreserveError, 'ABSOLUTE_PATH_REQUIRED'):
                evidence.preserve(self.source, target, DAY, ['config.json'], confirm=True)

    def test_code_root_rejected(self) -> None:
        with patch.object(evidence, 'CODE_ROOT', self.root):
            with self.assertRaisesRegex(evidence.PreserveError, 'EXTERNAL_PATH_REQUIRED'):
                self.preserve()

    def test_file_and_total_bounds(self) -> None:
        for limit in ('MAX_FILE_BYTES', 'MAX_TOTAL_BYTES'):
            with self.subTest(limit=limit), patch.object(evidence, limit, 1):
                with self.assertRaisesRegex(evidence.PreserveError, 'SIZE_BOUND'):
                    self.preserve()
        self.assertFalse(self.destination.exists())

    def test_count_bound(self) -> None:
        for index in range(3):
            self.put('state/inputs/' + f'{index:064x}' + '.json')
        with patch.object(evidence, 'MAX_FILES', 2):
            with self.assertRaisesRegex(evidence.PreserveError, 'TREE_BOUND'):
                self.preserve(['state/inputs'])

    def test_source_mutation_blocks_retains_partial_never_retries(self) -> None:
        original = evidence.exact_copy

        def changed(source: Path, target: Path, expected: evidence.Fingerprint) -> None:
            original(source, target, expected)
            source.write_bytes(b'changed fixture')

        with patch.object(evidence, 'exact_copy', changed):
            with self.assertRaisesRegex(evidence.PreserveError, 'SOURCE_CHANGED'):
                self.preserve()
        self.assertTrue((self.destination / 'originals/config.json').exists())
        self.assertFalse((self.destination / 'manifest.json').exists())
        with self.assertRaisesRegex(evidence.PreserveError, 'DESTINATION_EXISTS'):
            self.preserve()

    def test_added_selected_file_detected(self) -> None:
        name = 'state/inputs/' + 'd' * 64 + '.json'
        self.put(name)
        original = evidence.exact_copy

        def added(source: Path, target: Path, expected: evidence.Fingerprint) -> None:
            original(source, target, expected)
            self.put('state/inputs/' + 'e' * 64 + '.json')

        with patch.object(evidence, 'exact_copy', added):
            with self.assertRaisesRegex(evidence.PreserveError, 'SOURCE_CHANGED'):
                self.preserve(['state/inputs'])
        self.assertFalse((self.destination / 'manifest.json').exists())

    def test_copy_failure_redacted_and_retained(self) -> None:
        output = io.StringIO()
        with patch.object(evidence, 'exact_copy', side_effect=OSError('secret-value private-path')), \
                redirect_stdout(output):
            code = evidence.main(self.arguments('--confirm-preserve'))
        self.assertEqual(code, 2)
        self.assertNotIn('secret-value', output.getvalue())
        self.assertNotIn(str(self.source), output.getvalue())
        self.assertTrue(self.destination.exists())
        self.assertFalse((self.destination / 'manifest.json').exists())

    def test_invalid_arguments_redacted(self) -> None:
        for args in (['--private-value-secret'], self.arguments('--unknown-private-path'),
                     ['--source-session', 'secret-path']):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(evidence.main(args), 2)
            self.assertEqual(json.loads(output.getvalue())['category'], 'ARGUMENTS_INVALID')
            self.assertNotIn('secret-path', output.getvalue())

    def test_symlink_source_and_destination_ancestors(self) -> None:
        link = self.root / 'linked'
        try:
            link.symlink_to(self.source, target_is_directory=True)
        except OSError:
            self.skipTest('OS denies unprivileged symlink creation')
        for source, target in ((self.source, link / 'new'),
                               (link, self.destination)):
            with self.assertRaisesRegex(evidence.PreserveError, 'LINK_OR_REPARSE'):
                evidence.preserve(source, target, DAY, ['config.json'], confirm=True)

    def test_dangling_file_symlink_rejected(self) -> None:
        path = self.source / 'config.json'
        path.unlink()
        try:
            path.symlink_to(self.root / 'missing')
        except OSError:
            self.skipTest('OS denies unprivileged symlink creation')
        with self.assertRaisesRegex(evidence.PreserveError, 'LINK_OR_REPARSE'):
            self.preserve()

    def test_hardlink_rejected(self) -> None:
        os.link(self.source / 'config.json', self.root / 'hardlink')
        with self.assertRaisesRegex(evidence.PreserveError, 'REGULAR_SINGLE_LINK'):
            self.preserve()

    @unittest.skipUnless(os.name == 'nt', 'Windows junction fixture')
    def test_windows_junction_rejected(self) -> None:
        link = self.source / 'state/inputs'
        link.parent.mkdir()
        actual = self.root / 'outside'
        actual.mkdir()
        completed = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(actual)],
                                   capture_output=True, timeout=10)
        self.assertEqual(completed.returncode, 0)
        with self.assertRaisesRegex(evidence.PreserveError, 'LINK_OR_REPARSE'):
            self.preserve(['state/inputs'])
        link.rmdir()  # Remove only this fixture's junction, never its target.

    def database(self, wal: bool = False, versioned: bool = False) -> tuple[Path, sqlite3.Connection]:
        name = evidence.DATABASES[int(versioned)]
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        self.addCleanup(connection.close)
        if wal:
            self.assertEqual(connection.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            connection.execute('PRAGMA wal_autocheckpoint=0')
        connection.execute('CREATE TABLE evidence (value TEXT)')
        connection.execute("INSERT INTO evidence VALUES ('offline fixture')")
        connection.commit()
        return path, connection

    def test_sqlite_quiescent_exact_bytes_without_sqlite_open(self) -> None:
        database, connection = self.database()
        connection.close()
        before = database.read_bytes()
        with patch.object(sqlite3, 'connect', side_effect=AssertionError('no SQLite access')):
            self.preserve([evidence.DATABASES[0]])
        self.assertEqual(database.read_bytes(), before)
        self.assertEqual((self.destination / 'originals' / evidence.DATABASES[0]).read_bytes(), before)
        self.assertEqual(self.manifest()['sqlite_method'], 'EXACT_BYTES_NO_SQLITE_OPEN')
        with closing(sqlite3.connect((self.destination / 'originals' / evidence.DATABASES[0]).as_uri()
                                     + '?mode=ro', uri=True)) as saved:
            self.assertEqual(saved.execute('SELECT value FROM evidence').fetchall(), [('offline fixture',)])

    def test_wal_blocks_before_destination_even_unselected(self) -> None:
        database, _ = self.database(wal=True, versioned=True)
        before = {p.name: p.read_bytes() for p in database.parent.iterdir()}
        with patch.object(sqlite3, 'connect', side_effect=AssertionError('no SQLite access')):
            with self.assertRaisesRegex(evidence.PreserveError, 'SQLITE_SIDECARS'):
                self.preserve()
        self.assertFalse(self.destination.exists())
        self.assertEqual(before, {p.name: p.read_bytes() for p in database.parent.iterdir()})

    def test_orphan_sidecar_and_rollback_journal_refused(self) -> None:
        self.put(evidence.DATABASES[0] + '-wal')
        with self.assertRaisesRegex(evidence.PreserveError, 'SQLITE_SIDECARS'):
            self.preserve([evidence.DATABASES[0] + '-wal'])
        self.put(evidence.DATABASES[0])
        self.put(evidence.DATABASES[0] + '-journal')
        with self.assertRaisesRegex(evidence.PreserveError, 'SQLITE_SIDECARS'):
            self.preserve([evidence.DATABASES[0]])
        self.assertFalse(self.destination.exists())

    def test_invalid_sqlite_preserved_without_repair_or_integrity_claim(self) -> None:
        self.put(evidence.DATABASES[0], b'not a database')
        with patch.object(sqlite3, 'connect', side_effect=AssertionError('no SQLite access')):
            self.preserve([evidence.DATABASES[0]])
        self.assertEqual((self.destination / 'originals' / evidence.DATABASES[0]).read_bytes(),
                         b'not a database')
        self.assertEqual(self.manifest()['sqlite_method'], 'EXACT_BYTES_NO_SQLITE_OPEN')

    def test_each_sidecar_and_lock_blocks_unselected(self) -> None:
        for db in evidence.DATABASES:
            for suffix in ('-wal', '-shm', '-journal', '.producer-lock'):
                name = db + suffix if suffix != '.producer-lock' else str(Path(db).with_suffix(suffix)).replace('\\', '/')
                path = self.put(name)
                with self.subTest(name=name), self.assertRaises(evidence.PreserveError):
                    self.preserve()
                self.assertFalse(self.destination.exists())
                path.unlink()

    def test_sidecar_appearing_after_copy_blocks_retains_partial(self) -> None:
        original = evidence.exact_copy
        def appeared(source: Path, target: Path, expected: evidence.Fingerprint) -> None:
            original(source, target, expected)
            self.put(evidence.DATABASES[0] + '-wal')
        with patch.object(evidence, 'exact_copy', appeared):
            with self.assertRaisesRegex(evidence.PreserveError, 'SQLITE_SIDECARS'):
                self.preserve()
        self.assertTrue((self.destination / 'originals/config.json').exists())
        self.assertFalse((self.destination / 'manifest.json').exists())

    def test_new_default_receipt_detected(self) -> None:
        original = evidence.exact_copy
        def appeared(source: Path, target: Path, expected: evidence.Fingerprint) -> None:
            original(source, target, expected)
            self.put('state/' + RECEIPT)
        with patch.object(evidence, 'exact_copy', appeared):
            with self.assertRaisesRegex(evidence.PreserveError, 'SOURCE_CHANGED'):
                evidence.preserve(self.source, self.destination, DAY, confirm=True)
        self.assertFalse((self.destination / 'manifest.json').exists())

    def test_retained_copy_tampering_blocks_manifest(self) -> None:
        original = evidence.exact_copy
        def tampered(source: Path, target: Path, expected: evidence.Fingerprint) -> None:
            original(source, target, expected)
            target.write_bytes(b'altered fixture')
        with patch.object(evidence, 'exact_copy', tampered):
            with self.assertRaisesRegex(evidence.PreserveError, 'COPY_HASH_MISMATCH'):
                self.preserve()
        self.assertFalse((self.destination / 'manifest.json').exists())

    def test_unc_forbidden_without_filesystem_access(self) -> None:
        with patch.object(Path, 'lstat', side_effect=AssertionError('no filesystem access')):
            with self.assertRaises(evidence.PreserveError):
                evidence.checked_path(Path('//private-server/share/session'))

    @unittest.skipIf(os.name == 'nt', 'POSIX special file fixture')
    def test_fifo_rejected_without_opening(self) -> None:
        path = self.source / 'config.json'
        path.unlink()
        mkfifo = cast(Callable[[Path], None], getattr(os, 'mkfifo'))
        mkfifo(path)
        with self.assertRaisesRegex(evidence.PreserveError, 'REGULAR_SINGLE_LINK'):
            self.preserve()

    def test_private_permissions_fail_closed(self) -> None:
        with patch.object(evidence, 'private_permissions', side_effect=evidence.PreserveError('PRIVATE_PERMISSIONS_UNVERIFIED')):
            with self.assertRaisesRegex(evidence.PreserveError, 'PRIVATE_PERMISSIONS_UNVERIFIED'):
                self.preserve()
        self.assertFalse(self.destination.exists())
        self.assertFalse((self.destination / 'manifest.json').exists())

    def test_inherited_permissions_verified_without_repair(self) -> None:
        with patch.object(os, 'chmod', side_effect=AssertionError('permission mutation forbidden')):
            self.preserve()
        for path in (self.root, self.destination, *self.destination.rglob('*')):
            evidence.private_permissions(path)
        self.assertFalse(self.manifest()['owner_only_claim'])
        self.assertEqual(self.manifest()['permissions'], 'VERIFIED_INHERITANCE_NO_PERMISSION_CHANGES')

    def test_public_producer_paths_exactly_preserved(self) -> None:
        # Public InputArchive.put, forward_nifty_job.write_once, quarantine
        # receipt_only and versioned_capture.receipt all use these names.
        names = ['state/inputs/' + 'f' * 64 + '.json',
                 'state/' + RECEIPT, 'state/failure-' + 'b' * 32 + '.json',
                 'state/quarantine-v1/policy.json',
                 'state/quarantine-v1/snapshots/0920.json',
                 'state/quarantine-v1/receipts/' + RECEIPT,
                 'state/quarantine-v1/receipts/failure-' + 'b' * 32 + '.json',
                 'state/versioned-v1/recipe.json',
                 'state/versioned-v1/receipts/' + RECEIPT,
                 'state/versioned-v1/receipts/failure-' + 'b' * 32 + '.json']
        for name in names:
            self.put(name)
        evidence.preserve(self.source, self.destination, DAY, confirm=True)
        self.assertEqual({record['relative_path'] for record in self.manifest()['files']},
                         {'config.json', *names})
        for name in names:
            self.assertEqual((self.source / name).read_bytes(),
                             (self.destination / 'originals' / name).read_bytes())

    def test_exposed_parent_blocks_before_source_reads(self) -> None:
        original = evidence.private_permissions
        def exposed(path: Path) -> None:
            if path == self.root:
                raise evidence.PreserveError('PRIVATE_PERMISSIONS_EXPOSED')
            original(path)
        with patch.object(evidence, 'private_permissions', exposed), \
                patch.object(evidence, 'snapshot', side_effect=AssertionError('no source reads')):
            with self.assertRaisesRegex(evidence.PreserveError, 'PRIVATE_PERMISSIONS_EXPOSED'):
                self.preserve()
        self.assertFalse(self.destination.exists())

    def test_inheritance_failure_retains_empty_destination(self) -> None:
        original = evidence.private_permissions
        def exposed(path: Path) -> None:
            if path == self.destination:
                raise evidence.PreserveError('PRIVATE_PERMISSIONS_EXPOSED')
            original(path)
        with patch.object(evidence, 'private_permissions', exposed):
            with self.assertRaisesRegex(evidence.PreserveError, 'PRIVATE_PERMISSIONS_EXPOSED'):
                self.preserve()
        self.assertTrue(self.destination.exists())
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_no_permission_mutators_in_helper(self) -> None:
        import ast
        source = Path(evidence.__file__).read_text(encoding='utf-8')
        tree = ast.parse(source)
        forbidden = {'chmod', 'fchmod', 'chown', 'fchown', 'SetFileSecurityW',
                     'SetNamedSecurityInfoW', 'SetSecurityInfo', 'SetAcl'}
        self.assertFalse(any(isinstance(node, ast.Attribute) and node.attr in forbidden
                             for node in ast.walk(tree)))

    def test_existing_parent_permissions_unchanged(self) -> None:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            adv = ctypes.WinDLL('advapi32', use_last_error=True)
            adv.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
                                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
            def descriptor(path: Path) -> bytes:
                size = wintypes.DWORD()
                adv.GetFileSecurityW(str(path), 5, None, 0, ctypes.byref(size))
                value = ctypes.create_string_buffer(size.value)
                self.assertTrue(adv.GetFileSecurityW(str(path), 5, value, size, ctypes.byref(size)))
                return value.raw
            before = descriptor(self.root)
            self.preserve()
            self.assertEqual(before, descriptor(self.root))
        else:
            before_mode = stat.S_IMODE(self.root.stat().st_mode)
            self.preserve()
            self.assertEqual(before_mode, stat.S_IMODE(self.root.stat().st_mode))
            for path in (self.destination, *self.destination.rglob('*')):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)


if __name__ == '__main__':
    unittest.main()
