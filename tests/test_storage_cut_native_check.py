"""Preview/confirmation guard; native tests are never part of offline pytest."""
import json

import pytest

import storage_cut_native_check as module


@pytest.mark.parametrize('arguments', [[], ['--confirm-disposable'], ['--execute']])
def test_no_native_execute_without_both_gates(arguments: list[str], monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    def deny() -> None:
        raise AssertionError('Native network/SQL must not run')
    monkeypatch.setattr(module, 'execute', deny)
    expected = 2 if arguments == ['--execute'] else 0
    assert module.main(arguments) == expected
    assert json.loads(capsys.readouterr().out)['hosted_changes'] == 0


def test_confirmed_uses_injected_runner_only(monkeypatch: pytest.MonkeyPatch,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(module, 'execute', lambda: {'status':'DISPOSABLE_NATIVE_CUT_CASES_PASSED'})
    assert module.main(['--execute', '--confirm-disposable']) == 0
    assert 'DISPOSABLE_NATIVE_CUT_CASES_PASSED' in capsys.readouterr().out


def test_runner_failure_is_redacted(monkeypatch: pytest.MonkeyPatch,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    def broken() -> None:
        raise RuntimeError('private password source path')
    monkeypatch.setattr(module, 'execute', broken)
    assert module.main(['--execute', '--confirm-disposable']) == 2
    output = capsys.readouterr().out
    assert 'private' not in output and 'password' not in output
    assert json.loads(output)['stage'] == 'RUNNER_DEPENDENCY_OR_CLEANUP'
