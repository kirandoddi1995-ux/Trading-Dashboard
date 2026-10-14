"""Offline generated public trees; no actual tasks, credentials or Git mutation."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

import daily_volume_upload_check as guarded
import forward_commissioning_upload_check as check


class CommissioningCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix='commissioning-check-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        all_names = set(check.FILES) | set(check.SEEDS) | set(check.EXTRA_PINS) | {'dependency.py'}
        for name in all_names - {check.MANIFEST}:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'# public\r\n')
        (self.root / 'forward_session_ops.py').write_text('import dependency\n', encoding='utf-8')
        prior = (guarded.guarded_members(self.root, list(check.SEEDS)) | set(check.EXTRA_PINS)) - set(check.FILES)
        def pin(name: str) -> dict[str, object]:
            return {'destination': name, 'sha256_lf': None if name == check.MANIFEST
                    else guarded.digest((self.root / name).read_bytes())}
        self.plan: dict[str, Any] = {
            'version': check.VERSION, 'group': check.GROUP, 'base': check.BASE,
            'files': [pin(name) for name in check.FILES],
            'prerequisites': [pin(name) for name in sorted(prior)],
            'seeds': list(check.SEEDS), 'extra_pins': list(check.EXTRA_PINS),
        }
        self.save()

    def save(self) -> None:
        (self.root / check.MANIFEST).write_text(json.dumps(self.plan), encoding='utf-8')

    def test_exact_ten_destinations_and_baseline(self) -> None:
        self.assertEqual(len(check.FILES), 10)
        self.assertEqual(check.BASE, '161ffe082343c20cf118950fdb49e5315bb54e7f')
        self.assertIn('forward_ops_host.py', check.FILES)
        self.assertNotIn('AUTOMATION_PROGRESS.md', check.FILES)
        self.assertEqual(check.verify(self.root, set(check.FILES)), [])

    def test_hash_change_reports_only_public_metadata(self) -> None:
        target = self.root / 'dependency.py'
        old = guarded.digest(target.read_bytes())
        target.write_bytes(b'# changed\n')
        self.assertEqual(check.verify(self.root, set(check.FILES)), [
            {'path': target.name, 'expected': old, 'actual': guarded.digest(b'# changed\n')}])

    def test_manifest_schema_types_omissions_duplicates(self) -> None:
        original = json.dumps(self.plan)
        for mutation in ('base', 'group', 'version', 'extra_field', 'missing_field', 'files_type',
                         'entry_type', 'entry_fields', 'path_type', 'hash_type', 'duplicate',
                         'null_prerequisite', 'self_hash', 'omit_file', 'omit_pin', 'overlap',
                         'seeds', 'extras'):
            with self.subTest(mutation=mutation):
                self.plan = json.loads(original)
                if mutation in ('base', 'group', 'version'):
                    self.plan[mutation] = True
                elif mutation == 'extra_field':
                    self.plan['export'] = 'untrusted'
                elif mutation == 'missing_field':
                    del self.plan['base']
                elif mutation == 'files_type':
                    self.plan['files'] = {}
                elif mutation == 'entry_type':
                    self.plan['files'][0] = 'bad'
                elif mutation == 'entry_fields':
                    self.plan['files'][0]['extra'] = 1
                elif mutation == 'path_type':
                    self.plan['files'][0]['destination'] = []
                elif mutation == 'hash_type':
                    self.plan['files'][0]['sha256_lf'] = False
                elif mutation == 'duplicate':
                    self.plan['files'].append(self.plan['files'][0])
                elif mutation == 'null_prerequisite':
                    self.plan['prerequisites'][0]['sha256_lf'] = None
                elif mutation == 'self_hash':
                    self.plan['files'][-1]['sha256_lf'] = 'a' * 64
                elif mutation == 'omit_file':
                    self.plan['files'].pop()
                elif mutation == 'omit_pin':
                    self.plan['prerequisites'].pop()
                elif mutation == 'overlap':
                    self.plan['prerequisites'].append(self.plan['files'][0])
                elif mutation == 'seeds':
                    self.plan['seeds'].reverse()
                else:
                    self.plan['extra_pins'].reverse()
                self.save()
                with self.assertRaises(ValueError):
                    check.verify(self.root, set(check.FILES))

    def test_duplicate_json_keys_and_nonfinite_rejected(self) -> None:
        for raw in ('[]', 'false', '{"base":NaN}', '{"base":1,"base":2}'):
            with self.subTest(raw=raw):
                (self.root / check.MANIFEST).write_text(raw)
                with self.assertRaises(ValueError):
                    check.verify(self.root, set(check.FILES))

    def test_changed_set_must_be_exact(self) -> None:
        for changed in (set(), set(check.FILES) - {'forward_ops_host.py'}, set(check.FILES) | {'other.py'}):
            with self.assertRaisesRegex(ValueError, 'EXACT_PACKAGE_REQUIRED'):
                check.verify(self.root, changed)

    def test_unknown_json_private_and_malformed_paths_rejected(self) -> None:
        for name in ('../private.py', 'C:/private.py', 'tests/../private.py', 'token_state.py',
                     'untrusted_export.json', guarded.MANIFEST, 'tests\\private.py', None):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'PUBLIC_SOURCE_PATH_REQUIRED'):
                check.public_source(self.root, name)

    def test_control_link_and_strict_size_guard_before_read(self) -> None:
        target = self.root / check.MANIFEST
        with patch.object(Path, 'is_junction', lambda path: path == target):
            with self.assertRaisesRegex(ValueError, 'SOURCE_LINK_REJECTED'):
                check.public_source(self.root, check.MANIFEST)
        target.write_bytes(b' ' * check.CONTROL_LIMIT)
        with patch.object(Path, 'open', side_effect=AssertionError('READ')):
            with self.assertRaisesRegex(ValueError, 'CONTROL_TOO_LARGE'):
                check.verify(self.root, set(check.FILES))

    def test_unsupported_dynamic_import_blocks_no_execution(self) -> None:
        (self.root / 'forward_morning_readiness.py').write_text('importlib.import_module(target)')
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_DYNAMIC_IMPORT'):
            check.verify(self.root, set(check.FILES))

    def test_ordinary_index_checks_reuse_frozen_adapter(self) -> None:
        ordinary = {'dependency.py', 'forward_ops_host.py'}
        with patch.object(guarded, 'index_matches', return_value=[]) as reused:
            self.assertEqual(check.index_matches(self.root, ordinary), [])
            reused.assert_called_once_with(self.root, ordinary)

    def test_control_index_matches_and_divergence(self) -> None:
        content = (self.root / check.MANIFEST).read_bytes()
        for staged in (content, b'# different\n'):
            with self.subTest(matches=staged == content):
                def git(root: Path, *args: str) -> str:
                    return '100644 ' + 'a' * 40 + ' 0\t' + check.MANIFEST if args[0] == 'ls-files' else str(len(staged))
                with patch.object(guarded, 'index_matches', return_value=[]), patch.object(check, 'git', git), \
                        patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, staged)):
                    failures = check.index_matches(self.root, {check.MANIFEST})
                self.assertEqual(failures, [] if staged == content else [
                    {'path': check.MANIFEST, 'expected': guarded.digest(content), 'actual': guarded.digest(staged)}])

    def test_control_index_mode_and_size_before_blob_read(self) -> None:
        for mode, size, rule in (('120000', '1', 'INDEX_ENTRY_INVALID'),
                                 ('100644', str(check.CONTROL_LIMIT), 'INDEX_BLOB_TOO_LARGE'),
                                 ('100644', '-1', 'INDEX_BLOB_INVALID')):
            with self.subTest(mode=mode, size=size):
                def git(root: Path, *args: str) -> str:
                    return mode + ' ' + 'a' * 40 + ' 0\t' + check.MANIFEST if args[0] == 'ls-files' else size
                with patch.object(guarded, 'index_matches', return_value=[]), patch.object(check, 'git', git), \
                        patch.object(subprocess, 'run', side_effect=AssertionError('BLOB READ')):
                    with self.assertRaisesRegex(ValueError, rule):
                        check.index_matches(self.root, {check.MANIFEST})

    def fake_git(self, condition: str, *args: str) -> str:
        if args == ('rev-parse', 'HEAD'):
            return 'a' * 40 if condition == 'stale' else check.BASE
        if args == ('rev-parse', '--show-toplevel'):
            return str(self.root / 'other') if condition == 'not_root' else str(self.root)
        if args == ('diff', '--name-only', '--'):
            return 'private-error-path' if condition == 'unstaged' else ''
        if args == ('ls-files', '--others', '--exclude-standard'):
            return 'private-error-path' if condition == 'untracked' else ''
        if args[:2] == ('diff', '--cached'):
            return '\n'.join((*check.FILES, 'other.py')) if condition == 'extra' else '\n'.join(check.FILES)
        raise AssertionError(args)

    def test_cli_gates_redacted(self) -> None:
        for condition in ('stale', 'bad_base', 'not_root', 'unstaged', 'untracked', 'extra'):
            with self.subTest(condition=condition):
                def git(root: Path, *args: str) -> str:
                    return self.fake_git(condition, *args)
                output = io.StringIO()
                with patch.object(Path, 'cwd', return_value=self.root), patch.object(check, 'git', git), redirect_stdout(output):
                    code = check.main(['--base', 'bad' if condition == 'bad_base' else check.BASE])
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(output.getvalue())['status'], 'BLOCKED')
                self.assertNotIn('private-error-path', output.getvalue())

    def test_cli_binds_all_prerequisites_and_control(self) -> None:
        queried: list[set[str]] = []
        def git(root: Path, *args: str) -> str:
            return self.fake_git('', *args)
        def index(root: Path, names: set[str]) -> list[dict[str, str]]:
            queried.append(names)
            return []
        with patch.object(Path, 'cwd', return_value=self.root), patch.object(check, 'git', git), \
                patch.object(check, 'index_matches', index), redirect_stdout(io.StringIO()):
            self.assertEqual(check.main(['--base', check.BASE]), 0)
        self.assertEqual(queried, [{entry['destination'] for entry in self.plan['files'] + self.plan['prerequisites']}])

    def test_cli_raw_errors_never_printed(self) -> None:
        def git(root: Path, *args: str) -> str:
            return self.fake_git('', *args)
        output = io.StringIO()
        with patch.object(Path, 'cwd', return_value=self.root), patch.object(check, 'git', git), \
                patch.object(check, 'index_matches', side_effect=RuntimeError('PRIVATE_SECRET')), redirect_stdout(output):
            self.assertEqual(check.main(['--base', check.BASE]), 2)
        self.assertNotIn('PRIVATE_SECRET', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['rule'], 'UPLOAD_REVIEW_REQUIRED')


if __name__ == '__main__':
    unittest.main()
