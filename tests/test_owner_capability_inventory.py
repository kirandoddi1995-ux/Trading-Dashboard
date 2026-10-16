"""Synthetic PATH/metadata only; no launcher, capture, vault or host queries."""
from importlib import metadata
import json
from pathlib import Path
import subprocess
import sys

import pytest

import owner_capability_inventory as check


def forbidden(name: str) -> str:
    raise AssertionError('Preview must perform no discovery')


def test_preview_has_zero_reads_or_execution() -> None:
    report = check.inventory(locate=forbidden, version=forbidden)
    assert report['status'] == 'PREVIEW'
    assert report['tools'] == report['python_packages'] == []
    assert report['executable_location_reads'] == report['package_metadata_reads'] == 0
    assert report['filesystem_network_access'] == 'NOT_REACHED'
    assert report['operational_go'] is report['approval_authority'] is False


@pytest.mark.parametrize('python', [(3, 13, 9), (3, 15, 0), (3, 13, 10)])
def test_inspection_never_runs_discovered_launchers(python: tuple[int, int, int]) -> None:
    calls: list[str] = []

    def locate(name: str) -> str:
        calls.append(name)
        return 'PRIVATE_SYNTHETIC_PATH/' + name

    report = check.inventory(inspect=True, locate=locate, version=lambda _: '1.2.3', python_version=python)
    assert tuple(calls) == check.TOOLS
    assert report['reviewed_python_3139'] is (python == (3, 13, 9))
    assert report['operational_go'] is False
    for key in ('executable_invocations', 'default_launcher_invocations', 'network_requests_issued',
                'credential_api_calls', 'task_queries', 'service_queries', 'operational_writes',
                'installs', 'settings_changes'):
        assert report[key] == 0
    assert report['filesystem_network_access'] == 'NOT_ATTESTED_PATH_AND_METADATA_MAY_BE_REMOTE'
    assert 'PRIVATE_SYNTHETIC_PATH' not in json.dumps(report)


def test_missing_path_is_not_a_machine_wide_absence_claim() -> None:
    def missing(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    report = check.inventory(inspect=True, locate=lambda _: None, version=missing)
    assert 'NOT_FOUND_ON_PATH_NOT_A_MACHINE_WIDE_SEARCH' in json.dumps(report)
    assert 'NOT_INSTALLED_IN_THIS_INTERPRETER' in json.dumps(report)


@pytest.mark.parametrize('bad', ['PRIVATE_TOKEN/secret', '', 'a'*81, '1.0\nPRIVATE_TOKEN',
                               'PRIVATE_TOKEN', '1.0+PRIVATE_TOKEN'])
def test_unsafe_metadata_is_not_printed(bad: str) -> None:
    report = check.inventory(inspect=True, locate=lambda _: None, version=lambda _: bad)
    assert 'PRIVATE_TOKEN' not in json.dumps(report)
    assert '"version":' not in json.dumps(report)


def test_errors_are_redacted_and_report_stays_non_authoritative() -> None:
    def broken(name: str) -> str:
        raise RuntimeError('PRIVATE_TOKEN')

    report = check.inventory(inspect=True, locate=broken, version=broken)
    assert 'PRIVATE_TOKEN' not in json.dumps(report)
    assert report['status'] == 'TOOL_INVENTORY_NOT_CAPTURE_GO'
    assert report['capture_readiness'] == 'NOT_CHECKED'


def test_real_script_preview_uses_no_inspect_flag() -> None:
    script = Path(check.__file__).resolve()
    report = subprocess.run([sys.executable, '-I', '-B', str(script)],
                            check=True, capture_output=True, text=True, timeout=10)
    assert json.loads(report.stdout)['status'] == 'PREVIEW'


def test_source_has_no_process_network_service_or_private_adapters() -> None:
    source = Path(check.__file__).read_text(encoding='utf-8')
    assert 'import subprocess' not in source
    assert 'import socket' not in source
    assert 'import requests' not in source
    assert 'win32' not in source
    assert 'forward_windows_credentials' not in source
