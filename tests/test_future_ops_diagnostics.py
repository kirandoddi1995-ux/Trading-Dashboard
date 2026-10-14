"""Deterministic offline coverage: fake host, no installed tasks/capture/credentials."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
from datetime import date, datetime, timezone
import io
from importlib import metadata
import json
import re
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

import future_ops_diagnostics as diagnostics


class FutureDiagnosticsTests(unittest.TestCase):
    def test_preview_never_enters_io_for_any_mode(self) -> None:
        for mode in ('package', 'dependencies', 'clock', 'task', 'rehearsal'):
            with self.subTest(mode=mode), ExitStack() as stack:
                for target in ('package_check', 'dependencies', 'clock_query', 'task_query',
                               'rehearsal', 'notify_local'):
                    stack.enter_context(patch.object(diagnostics, target, side_effect=AssertionError('IO')))
                stack.enter_context(patch.object(Path, 'resolve', side_effect=AssertionError('PATH IO')))
                stack.enter_context(patch.object(subprocess, 'run', side_effect=AssertionError('PROCESS')))
                stack.enter_context(patch.object(subprocess, 'Popen', side_effect=AssertionError('PROCESS')))
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(diagnostics.main(['--mode', mode, '--notify-local']), 0)
                self.assertEqual(json.loads(output.getvalue())['status'], 'PREVIEW')

    def test_permissions_do_not_cross_modes(self) -> None:
        with patch.object(diagnostics, 'rehearsal', side_effect=AssertionError('IO')), redirect_stdout(io.StringIO()):
            self.assertEqual(diagnostics.main(['--mode', 'rehearsal', '--allow-read-only']), 0)
        with patch.object(diagnostics, 'clock_query', side_effect=AssertionError('IO')), redirect_stdout(io.StringIO()):
            self.assertEqual(diagnostics.main(['--mode', 'clock', '--allow-rehearsal']), 0)

    def test_exception_allowlist_and_redaction(self) -> None:
        examples = (
            (metadata.PackageNotFoundError('secret'), 'DEPENDENCY_MISSING'),
            (PermissionError('secret'), 'DIAGNOSTIC_ACCESS_DENIED'),
            (FileNotFoundError('secret'), 'DIAGNOSTIC_EXECUTABLE_MISSING'),
            (subprocess.TimeoutExpired('secret', 12), 'DIAGNOSTIC_TIMEOUT'),
            (ValueError('secret'), 'DIAGNOSTIC_INPUT_INVALID'),
            (RuntimeError('secret'), 'DIAGNOSTIC_UNAVAILABLE'),
        )
        for error, expected in examples:
            self.assertEqual(diagnostics.classify_exception(error), expected)

    def test_dependency_all_pins_missing_mismatch_and_broken_metadata(self) -> None:
        self.assertEqual(diagnostics.dependencies(diagnostics.PINS.__getitem__).status, 'CHECKED')
        for error in (metadata.PackageNotFoundError('private'), PermissionError('private'),
                      RuntimeError('private')):
            def missing(name: str) -> str:
                raise error
            result = diagnostics.dependencies(missing)
            self.assertEqual(result.status, 'BLOCKED')
            self.assertEqual(len(result.blockers), len(diagnostics.PINS))
            self.assertNotIn('private', str(result))
        self.assertEqual(len(diagnostics.dependencies(lambda name: 'wrong').blockers), len(diagnostics.PINS))

    def test_public_package_closure_and_requirement_pins(self) -> None:
        public = Path(__file__).resolve().parents[1]
        self.assertEqual(diagnostics.package_check(public).code, 'PUBLIC_IMPORT_CLOSURE_PINNED')
        with patch.object(Path, 'read_text', side_effect=PermissionError('private')):
            result = diagnostics.package_check(public)
            self.assertEqual(result.code, 'DIAGNOSTIC_ACCESS_DENIED')
            self.assertNotIn('private', str(result))

    def test_package_rejects_missing_pin_and_unmapped_import(self) -> None:
        def read(path: Path, **kwargs: object) -> str:
            if path.name == 'forward_session_ops.py':
                return 'import unknown_future_package\n'
            return ''
        with patch.object(Path, 'read_text', read), patch.object(Path, 'is_file', return_value=False):
            result = diagnostics.package_check(Path('public'))
        self.assertEqual(result.status, 'BLOCKED')
        self.assertIn('UNMAPPED_IMPORT:unknown_future_package', result.blockers)
        self.assertIn('PUBLIC_PIN_MISMATCH:pandas', result.blockers)

    def test_clock_query_only_never_confers_gate(self) -> None:
        calls: list[list[str]] = []
        def run(args: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, 'secret host source', 'secret error')
        result = diagnostics.clock_query(run)
        self.assertEqual(calls, [['w32tm.exe', '/query', '/status']])
        self.assertFalse(result.capture_clock_verified)
        self.assertNotIn('secret', str(result))
        self.assertEqual(diagnostics.clock_query(lambda args: subprocess.CompletedProcess(args, 1)).status, 'BLOCKED')
        def failed(args: list[str]) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired('private', 12)
        self.assertEqual(diagnostics.clock_query(failed).code, 'DIAGNOSTIC_TIMEOUT')

    def test_task_codes_are_distinct_signed_and_unsigned(self) -> None:
        self.assertEqual(diagnostics.task_result(2), 'PROCESS_EXIT_TWO')
        self.assertEqual(diagnostics.task_result(0x80070002), 'ACTION_FILE_NOT_FOUND')
        self.assertEqual(diagnostics.task_result(0x41301), 'TASK_RUNNING')
        self.assertEqual(diagnostics.task_result(0xC000013A - 2**32), 'PROCESS_TERMINATED_COMMIT_UNKNOWN')
        self.assertEqual(diagnostics.task_result(2**32), 'TASK_RESULT_REVIEW_REQUIRED')
        self.assertEqual(diagnostics.task_result(True), 'TASK_RESULT_REVIEW_REQUIRED')

    def test_task_names_prevent_existing_scope_and_shell_injection(self) -> None:
        runner = Mock(side_effect=AssertionError('HOST IO'))
        for name in ('KiranTrading-Forward-poll', "KiranFuture-a'; Remove-Item", '', '\\KiranFuture-test'):
            self.assertEqual(diagnostics.task_query(name, runner).code, 'FUTURE_TASK_NAME_REQUIRED')
        runner.assert_not_called()

    def test_task_query_is_allowlisted_and_redacted(self) -> None:
        calls: list[list[str]] = []
        def run(args: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, '{"state":"Disabled","result":267010}')
        result = diagnostics.task_query('KiranFuture-test', run)
        self.assertEqual(result.code, 'TASK_DISABLED')
        self.assertEqual(result.status, 'BLOCKED')
        self.assertFalse(result.approval_authority)
        self.assertNotIn('Arguments', calls[0][-1])
        self.assertNotIn('Enable-ScheduledTask', calls[0][-1])
        for payload in ('[]', '{}', 'secret', '{"state":"Ready","result":true}',
                        '{"state":"secret","result":0}', 'x' * 1025):
            def response(args: list[str]) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args, 0, payload)
            self.assertEqual(diagnostics.task_query('KiranFuture-test', response).status, 'BLOCKED')

    def test_rehearsal_open_boundary_wrong_date_naive_and_no_notification(self) -> None:
        notice = Mock(return_value=True)
        day = date(2026, 10, 14)
        for now in (datetime(2026, 10, 14, 3, 44, 59, tzinfo=timezone.utc),
                    datetime(2026, 10, 13, 4, tzinfo=timezone.utc), datetime(2026, 10, 14, 4)):
            result, code = diagnostics.rehearsal(day, now, exit_code=0, notify=True, notification=notice)
            self.assertEqual((result.status, code), ('BLOCKED', 2))
        notice.assert_not_called()
        for child_exit in (0, 1, 2):
            result, code = diagnostics.rehearsal(day, datetime(2026, 10, 14, 3, 45, tzinfo=timezone.utc),
                                                 exit_code=child_exit, notify=False, notification=notice)
            self.assertEqual((result.status, code), ('REHEARSAL_ONLY', child_exit))
        notice.assert_not_called()

    def test_notification_failure_and_launch_not_delivery(self) -> None:
        day, now = date(2026, 10, 14), datetime(2026, 10, 14, 4, tzinfo=timezone.utc)
        notice = Mock(return_value=True)
        result, code = diagnostics.rehearsal(day, now, exit_code=0, notify=True, notification=notice)
        self.assertEqual((result.code, code), ('NOTIFICATION_LAUNCHED_NOT_DELIVERED', 0))
        for callback in (Mock(return_value=False), Mock(side_effect=OSError('private'))):
            result, code = diagnostics.rehearsal(day, now, exit_code=0, notify=True, notification=callback)
            self.assertEqual((result.status, code), ('BLOCKED', 2))
            self.assertNotIn('private', str(result))

    def test_cli_failure_is_closed_and_redacted(self) -> None:
        output = io.StringIO()
        with patch.object(diagnostics, 'dependencies', side_effect=RuntimeError('private')), redirect_stdout(output):
            self.assertEqual(diagnostics.main(['--mode', 'dependencies', '--allow-read-only']), 2)
        self.assertNotIn('private', output.getvalue())

    def test_future_launcher_preview_has_no_child(self) -> None:
        # Only our new source is read. No native host actions execute in offline tests.
        source = (Path(__file__).resolve().parents[1] / 'future_ops_task.ps1').read_text(encoding='utf-8')
        self.assertLess(source.index('if (-not $AllowRehearsal)'), source.index('Test-Path'))
        self.assertIn('& $PythonExecutable @childArguments', source)
        self.assertIn('$childExit = $LASTEXITCODE', source)
        self.assertIn('exit $childExit', source)
        self.assertNotIn('forward_session_ops', source)
        self.assertNotIn('Start-Process', source)

    def test_future_launcher_rejects_drive_relative_and_nonlocal_paths(self) -> None:
        source = (Path(__file__).resolve().parents[1] / 'future_ops_task.ps1').read_text(encoding='utf-8')
        match = re.search(r"\$PythonExecutable -notmatch '([^']+)'", source)
        self.assertIsNotNone(match)
        assert match is not None
        pattern = re.compile(match[1])
        for value in ('C:python.exe', 'python.exe', '\\python.exe', '/python.exe',
                      '\\\\server\\share\\python.exe', '\\\\?\\C:\\python.exe', ''):
            self.assertIsNone(pattern.match(value), value)
        for value in ('C:\\Python313\\python.exe', 'D:/Python313/python.exe'):
            self.assertIsNotNone(pattern.match(value), value)
        self.assertNotIn('IsPathRooted', source)
        self.assertNotIn('IsPathFullyQualified', source)
        self.assertIn('Test-Path -LiteralPath $PythonExecutable -PathType Leaf', source)
        self.assertLess(source.index('$PythonExecutable -notmatch'), source.index('Test-Path'))


if __name__ == '__main__':
    unittest.main()
