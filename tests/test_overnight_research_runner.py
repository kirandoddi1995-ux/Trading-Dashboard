"""Executable synthetic chain and source import boundary checks."""
import ast
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from overnight_research_runner import synthetic_self_check
from overnight_research_runner import offline_boundary, verify_environment
from overnight_research_trials import DurableTrialRegistry

OWNED_MODULES = ('dataset', 'execution', 'ml', 'evidence', 'runner', 'trials', 'paper')


def test_executable_chain_reaches_every_stage_inactively() -> None:
    result = synthetic_self_check()
    assert result['dataset_manifest']['row_count'] == 6
    assert result['scenario_summary']['insufficient_data'] == 1
    assert result['trials'][0]['status'] == 'COMPLETED'
    assert result['ml_result']['status'] == 'COMPLETED_SYNTHETIC_EVALUATION'
    assert result['ml_result']['predictions']
    assert result['paper_gate']['status'] == 'BLOCKED'
    assert not result['paper_gate']['paper_run_authorized']


def test_cli_self_check_exits_success_without_activation() -> None:
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run([sys.executable, '-B', str(root / 'overnight_research_runner.py'),
        '--self-check'], cwd=root, capture_output=True, text=True, check=False, timeout=60)
    assert completed.returncode == 0, completed.stderr
    assert 'INACTIVE_RESEARCH_ONLY' in completed.stdout and 'INSUFFICIENT_DATA' in completed.stdout


def test_direct_imports_have_explicit_offline_boundary() -> None:
    root = Path(__file__).resolve().parents[1]
    approved_existing = {'forward_versioned_producer', 'forward_nifty_producer',
                         'forward_revision_quarantine', 'intraday_fo_costs'}
    for source in (root / ('overnight_research_' + name + '.py') for name in OWNED_MODULES):
        tree = ast.parse(source.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = (node.module or '').split('.')[0]
            elif isinstance(node, ast.Import):
                for name in node.names:
                    assert name.name.split('.')[0] in sys.stdlib_module_names
                continue
            else:
                continue
            assert module in sys.stdlib_module_names or module.startswith('overnight_research_') or module in approved_existing


def test_all_new_functions_have_annotations() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = [root / ('overnight_research_' + name + '.py') for name in OWNED_MODULES]
    sources += [root / 'tests' / ('test_overnight_research_' + name + '.py') for name in OWNED_MODULES]
    for source in sources:
        tree = ast.parse(source.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.returns is not None, (source.name, node.name)
                for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                    assert arg.arg in ('self', 'cls') or arg.annotation is not None, (source.name, node.name, arg.arg)


def test_executable_chain_persists_start_then_completion(tmp_path: Path) -> None:
    path = tmp_path / 'overnight_research_runner_trials.sqlite'
    registry = DurableTrialRegistry(path, create=True)
    result = synthetic_self_check(trial_registry=registry)
    assert result['ml_result']['predictions']
    events = DurableTrialRegistry(path).events()
    assert [event['state'] for event in events] == ['STARTED', 'COMPLETED']
    assert events[1]['metrics']['ridge_mae'] >= 0


def test_session_cv_one_day_is_retained_as_insufficient(tmp_path: Path) -> None:
    registry = DurableTrialRegistry(tmp_path / 'overnight_research_sessions.sqlite', create=True)
    result = synthetic_self_check(trial_registry=registry, session_groups=True)
    assert result['ml_result']['status'] == 'INSUFFICIENT_DATA'
    assert result['folds'] == [] and not result['ml_result']['predictions']
    assert [event['state'] for event in registry.events()] == ['STARTED', 'INSUFFICIENT_DATA']


def test_executable_fit_failure_is_durably_retained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import overnight_research_runner as runner
    path = tmp_path / 'overnight_research_runner_trials.sqlite'
    registry = DurableTrialRegistry(path, create=True)
    def fail(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError('synthetic fit failure')
    monkeypatch.setattr(runner, 'walk_forward_ridge', fail)
    with pytest.raises(RuntimeError):
        runner.synthetic_self_check(trial_registry=registry)
    events = DurableTrialRegistry(path).events()
    assert [event['state'] for event in events] == ['STARTED', 'FAILED']
    assert events[1]['failure_code'] == 'OFFLINE_FIT_FAILED'


def test_network_boundary_denies_socket_and_dns() -> None:
    import socket
    with offline_boundary():
        with pytest.raises(ValueError, match='OFFLINE_NETWORK_FORBIDDEN'):
            socket.create_connection(('example.test', 443))
        with pytest.raises(ValueError, match='OFFLINE_NETWORK_FORBIDDEN'):
            socket.getaddrinfo('example.test', 443)


def test_environment_verifier_never_installs(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata
    monkeypatch.setattr(importlib.metadata, 'version', lambda package: '0.0.0')
    result = verify_environment()
    assert result['status'] == 'PINNED_ENVIRONMENT_BLOCKED'
    assert 'pyarrow' in result['mismatched_packages'] and not result['installed_or_downloaded']


def test_scheduled_workflow_is_inactive_without_owner_activation() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root/'.github/workflows/overnight-research-offline.yml').read_text(encoding='utf-8')
    assert "vars.OVERNIGHT_RESEARCH_OFFLINE_ENABLED == 'true'" in text
    assert "inputs.confirmation == 'RUN_SYNTHETIC_ONLY'" in text
    assert 'runs-on: ubuntu-24.04' in text and 'contents: read' in text
    assert 'self-hosted' not in text and 'secrets.' not in text
    assert 'upload-artifact' not in text and 'download-artifact' not in text
    assert '--explicit-package-bases' in text


def test_failed_preparation_is_retained_not_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import overnight_research_runner as runner
    registry = DurableTrialRegistry(tmp_path / 'overnight_research_rejected.sqlite', create=True)
    from overnight_research_dataset import project_bundle as original
    calls = 0
    def fail(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            # The fixture builder needs row identities before invoking the real
            # preparation boundary. Fail inside run_offline, not fixture setup.
            return original(*args, **kwargs)
        raise ValueError('synthetic projection refusal')
    monkeypatch.setattr(runner, 'project_bundle', fail)
    with pytest.raises(ValueError):
        runner.synthetic_self_check(trial_registry=registry)
    events = registry.events()
    assert [event['state'] for event in events] == ['STARTED', 'FAILED']
    assert events[0]['reference_kind'] == 'REJECTED_INPUT_SHAPE'
    assert events[1]['failure_code'] == 'OFFLINE_PREPARATION_FAILED'
