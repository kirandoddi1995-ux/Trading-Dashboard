"""Inactive, credential-free tool discovery; never an operational GO report.

Preview is the default. Inspection reads executable locations and installed Python
distribution metadata only. No discovered executable, launcher or installer runs.
No capture/task/service/credential APIs or network requests are called. Filesystem
discovery can follow UNC/mapped PATH or interpreter locations; its locality is
not attested. This is not a zero-network-filesystem-access guarantee.
"""
from __future__ import annotations

import argparse
from importlib import metadata
import json
import re
import shutil
import sys
from typing import Callable

TOOLS = ('git', 'node', 'npm', 'docker', 'powershell', 'pwsh', 'py', '7z',
         'psql', 'pg_dump', 'pg_restore', 'uv')
PACKAGES = ('pytest', 'pyflakes', 'mypy', 'requests', 'google-auth', 'cryptography',
            'pandas', 'numpy', 'pyarrow')


def inventory(*, inspect: bool = False,
              locate: Callable[[str], str | None] = shutil.which,
              version: Callable[[str], str] = metadata.version,
              python_version: tuple[int, int, int] | None = None) -> dict[str, object]:
    """Dependency-injected reads; absence from PATH is not absence from the PC."""
    result: dict[str, object] = dict(
        status='PREVIEW', operational_go=False, capture_readiness='NOT_CHECKED',
        tools=[], python_packages=[], executable_location_reads=0,
        package_metadata_reads=0, executable_invocations=0,
        default_launcher_invocations=0, network_requests_issued=0, credential_api_calls=0,
        filesystem_network_access='NOT_REACHED',
        task_queries=0, service_queries=0, operational_writes=0, installs=0,
        settings_changes=0, approval_authority=False)
    if not inspect:
        return result
    actual = python_version if python_version is not None else tuple(sys.version_info[:3])
    tools: list[dict[str, str]] = []
    for name in TOOLS:
        try:
            location = locate(name)
            state = ('NOT_FOUND_ON_PATH_NOT_A_MACHINE_WIDE_SEARCH' if location is None else
                     'DISCOVERED_NOT_EXECUTED' if type(location) is str and location else
                     'NOT_VERIFIED')
        except Exception:
            state = 'NOT_VERIFIED'
        tools.append(dict(tool=name, observation=state))
    packages: list[dict[str, str]] = []
    for name in PACKAGES:
        try:
            installed = version(name)
            safe = (type(installed) is str and len(installed) <= 80 and re.fullmatch(
                r'[0-9]+(?:\.[0-9]+){1,3}(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?(?:\.dev[0-9]+)?',
                installed) is not None)
            entry = dict(package=name, observation='METADATA_ONLY_NOT_IMPORT_OR_API_PROOF' if safe else 'NOT_VERIFIED')
            if safe:
                entry['version'] = installed
        except metadata.PackageNotFoundError:
            entry = dict(package=name, observation='NOT_INSTALLED_IN_THIS_INTERPRETER')
        except Exception:
            entry = dict(package=name, observation='NOT_VERIFIED')
        packages.append(entry)
    result.update(status='TOOL_INVENTORY_NOT_CAPTURE_GO', tools=tools,
                  python_packages=packages, executable_location_reads=len(TOOLS),
                  package_metadata_reads=len(PACKAGES),
                  reviewed_python_3139=actual == (3, 13, 9),
                  python_version='.'.join(map(str, actual)),
                  filesystem_network_access='NOT_ATTESTED_PATH_AND_METADATA_MAY_BE_REMOTE',
                  path_and_distribution_metadata_not_operational_proof=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspect-tools', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(inventory(inspect=args.inspect_tools), sort_keys=True))
    return 0  # A tool inventory cannot admit or reject a live capture.


if __name__ == '__main__':
    raise SystemExit(main())
