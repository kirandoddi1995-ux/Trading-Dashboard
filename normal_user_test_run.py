"""Explicit normal-user Windows test launcher; NOT filesystem/network isolation.

Preview performs no input IO. Confirmed execution preserves its new scratch root,
inherits test output for private owner logs, and never retries or repairs anything.
Invoke using the explicit Python executable also supplied through --python.
Requires a clean ordinary Git checkout; ignored files are rejected except the
SQL harness's installed node_modules. Clean status is not public provenance.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import NoReturn, Sequence


RUNTIME_ENV_NAMES = frozenset({
    'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'HOME',
    'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'COMSPEC', 'USERNAME', 'USERDOMAIN',
    'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'PROGRAMFILES',
    'PROGRAMFILES(X86)', 'PYTHONUTF8',
})


class Blocked(ValueError):
    """Fixed redacted reason code."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise Blocked('INVALID_ARGUMENTS')


def _normal_windows() -> None:
    if sys.platform != 'win32':
        raise Blocked('WINDOWS_REQUIRED')
    if tuple(sys.version_info[:3]) != (3, 13, 9):
        raise Blocked('PYTHON_3_13_9_REQUIRED')
    # This checks effective-token administrator membership, not account history.
    if ctypes.windll.shell32.IsUserAnAdmin() != 0:
        raise Blocked('NONADMIN_TOKEN_REQUIRED')


def _json(path: Path) -> dict[str, object]:
    if path.stat().st_size > 1048576:
        raise Blocked('PGLITE_METADATA_BOUND')
    value: object = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise Blocked('PGLITE_METADATA_INVALID')
    return value


def _clean_checkout(root: Path, env: dict[str, str]) -> None:
    if not (root / '.git').is_dir() or (root / '.git').is_symlink():
        raise Blocked('ORDINARY_GIT_CHECKOUT_REQUIRED')
    git = shutil.which('git')
    if git is None:
        raise Blocked('GIT_REQUIRED')
    git_env = {key: value for key, value in env.items() if not key.upper().startswith('GIT_')}
    prefix = [git, '--no-optional-locks', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false']
    def query(arguments: list[str]) -> str:
        reply = subprocess.run(prefix + arguments, cwd=root, env=git_env,
                               capture_output=True, text=True, check=False, timeout=30)
        if reply.returncode != 0:
            raise Blocked('GIT_PREFLIGHT_FAILED')
        return reply.stdout.strip()
    top = query(['rev-parse', '--show-toplevel'])
    if Path(top).resolve(strict=True) != root:
        raise Blocked('EXACT_GIT_ROOT_REQUIRED')
    if query(['rev-parse', '--is-bare-repository']) != 'false':
        raise Blocked('NONBARE_CHECKOUT_REQUIRED')
    query(['rev-parse', '--verify', 'HEAD^{commit}'])
    status = query(['status', '--porcelain=v1', '--untracked-files=all', '--ignored=matching'])
    if any(line != '!! tests/sql-harness/node_modules/' for line in status.splitlines()):
        raise Blocked('CLEAN_CHECKOUT_REQUIRED')


def _pglite(root: Path, env: dict[str, str]) -> None:
    node = shutil.which('node')
    if node is None:
        raise Blocked('NODE_24_REQUIRED')
    probe = subprocess.run([node, '--version'], capture_output=True, text=True,
                           check=False, timeout=15, env=env)
    if probe.returncode != 0 or not probe.stdout.strip().startswith('v24.'):
        raise Blocked('NODE_24_REQUIRED')
    harness = root / 'tests/sql-harness'
    lock = _json(harness / 'package-lock.json')
    packages = lock.get('packages')
    if not isinstance(packages, dict):
        raise Blocked('PGLITE_LOCK_REQUIRED')
    pinned = packages.get('node_modules/@electric-sql/pglite')
    installed = harness / 'node_modules/@electric-sql/pglite'
    if (not isinstance(pinned, dict) or pinned.get('version') != '0.3.14'
            or _json(installed / 'package.json').get('version') != '0.3.14'):
        raise Blocked('PGLITE_LOCK_MISMATCH')
    env['EQUITY_TEST_PGLITE_MODULE'] = str(installed)
    env['PATH'] = str(Path(node).parent) + os.pathsep + env.get('PATH', '')
    script = ("const {PGlite}=require(process.argv[1]);"
              "(async()=>{const db=new PGlite();try{await db.waitReady;"
              "const r=await db.query('SELECT 1 AS ok');"
              "if(r.rows.length!==1||r.rows[0].ok!==1)throw Error();"
              "}finally{await db.close();}process.stdout.write('PGLITE_SELECT_1_OK');"
              "})().catch(()=>{process.exitCode=2;});")
    sql = subprocess.run([node, '-e', script, str(installed)], cwd=root, env=env,
                         capture_output=True, text=True, check=False, timeout=60)
    if sql.returncode != 0 or sql.stdout != 'PGLITE_SELECT_1_OK':
        raise Blocked('PGLITE_SELECT_1_FAILED')


def main(argv: Sequence[str] | None = None) -> int:
    phase = 'ARGUMENTS'
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('--run-confirmed', action='store_true')
        parser.add_argument('--python')
        parser.add_argument('--with-pglite', action='store_true')
        args = parser.parse_args(argv)
        if not args.run_confirmed:
            print(json.dumps(dict(phase='PREVIEW', input_reads=0, writes=0,
                                  filesystem_isolation=False, network_isolation=False)))
            return 0
        phase = 'PREFLIGHT'
        _normal_windows()
        if not args.python or not Path(args.python).is_absolute():
            raise Blocked('EXPLICIT_PYTHON_REQUIRED')
        python = Path(args.python).resolve(strict=True)
        if python != Path(sys.executable).resolve(strict=True):
            raise Blocked('PYTHON_MUST_MATCH_LAUNCHER')
        root = Path(__file__).resolve().parent
        parent = Path(tempfile.gettempdir()).resolve(strict=True)
        if parent == root or parent.is_relative_to(root):
            raise Blocked('TEMP_OUTSIDE_CHECKOUT_REQUIRED')
        # Do not propagate credentials, proxy configuration or runtime injection
        # variables into Git, Node or pytest. Windows environment keys ignore case.
        env = {key.upper(): value for key, value in os.environ.items()
               if key.upper() in RUNTIME_ENV_NAMES}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        _clean_checkout(root, env)
        phase = 'ALLOCATE'
        scratch = Path(tempfile.mkdtemp(prefix='normal-user-tests-', dir=parent))
        env['TEMP'] = env['TMP'] = env['TMPDIR'] = str(scratch)
        if args.with_pglite:
            phase = 'PGLITE'
            _pglite(root, env)
        # pytest gets a nonexistent child, never an existing owner directory.
        command = [str(python), '-B', '-m', 'pytest', '-p', 'no:cacheprovider',
                   '--basetemp', str(scratch / 'pytest'), 'tests']
        print(json.dumps(dict(phase='PYTEST', pglite_requested=args.with_pglite,
                              pglite_status='SELECT_1_PASSED' if args.with_pglite else 'NOT_REQUESTED_SQL_MAY_SKIP',
                              filesystem_isolation=False, network_isolation=False,
                              scratch_retained=True)), flush=True)
        phase = 'PYTEST'
        completed = subprocess.run(command, cwd=root, env=env, check=False)
        print(json.dumps(dict(phase='COMPLETE', pytest_exit=completed.returncode,
                              scratch_retained=True)), flush=True)
        return completed.returncode
    except Blocked as error:
        code = str(error)
    except Exception:
        code = 'LOCAL_OPERATION_UNAVAILABLE'
    print(json.dumps(dict(phase=phase, status='BLOCKED', code=code, raw_error_printed=False)))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
