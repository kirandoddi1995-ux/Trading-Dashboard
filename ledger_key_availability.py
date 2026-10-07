"""Owner-only presence check of ONE private TOML backup; never prints values.

This is not historical-key verification, key rotation, secret discovery, or a
search tool. The owner supplies one explicit file at a hidden path prompt.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import getpass
import json
from pathlib import Path
import tomllib
from typing import Any, NoReturn

KEY_NAME = 'EVIDENCE_LEDGER_SIGNING_KEY'
MAX_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 16


class KeyCheckError(ValueError):
    """Only stable codes, never driver/parser/file/secret contents."""


class _PrivateParser(argparse.ArgumentParser):
    """Do not echo mistakenly supplied path/key arguments in usage errors."""

    def error(self, message: str) -> NoReturn:
        raise KeyCheckError('PRIVATE_KEY_CHECK_ARGUMENTS_INVALID')


def inspect_toml(raw: bytes) -> dict[str, object]:
    """Report exact-name presence only, not a key ID or proof of historical use."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise KeyCheckError('PRIVATE_BACKUP_SIZE_INVALID')
    try:
        document = tomllib.loads(raw.decode('utf-8-sig'))
        found: list[bool] = []
        def visit(node: Mapping[str, Any], depth: int) -> None:
            if depth > MAX_DEPTH:
                raise KeyCheckError('PRIVATE_BACKUP_NESTING_INVALID')
            for name, value in node.items():
                if name == KEY_NAME:
                    found.append(isinstance(value, str) and bool(value.strip()))
                elif isinstance(value, Mapping):
                    visit(value, depth + 1)
        visit(document, 0)
        return {'status': 'PRIVATE_KEY_NAME_CHECKED', 'key_name': KEY_NAME,
                'present': bool(found), 'nonempty_string_copies': sum(found),
                'entries_with_exact_name': len(found), 'historical_match_verified': False,
                'values_output': False, 'writes': 0, 'network_calls': 0}
    except KeyCheckError:
        raise
    except Exception:
        raise KeyCheckError('PRIVATE_BACKUP_FORMAT_UNSUPPORTED') from None


def check_file(path: Path, *, project_root: Path) -> dict[str, object]:
    """One explicitly named private non-link file, outside the project."""
    try:
        if not path.is_absolute():
            raise KeyCheckError('PRIVATE_BACKUP_PATH_INVALID')
        resolved = path.resolve(strict=True)
        if resolved.is_relative_to(project_root.resolve()):
            raise KeyCheckError('PRIVATE_BACKUP_MUST_STAY_OUTSIDE_PROJECT')
        for part in (path, *path.parents):
            if part.is_symlink() or part.is_junction():
                raise KeyCheckError('PRIVATE_BACKUP_LINK_REJECTED')
        if not resolved.is_file() or not 1 <= resolved.stat().st_size <= MAX_BYTES:
            raise KeyCheckError('PRIVATE_BACKUP_SIZE_INVALID')
        with resolved.open('rb') as handle:
            raw = handle.read(MAX_BYTES + 1)
        return inspect_toml(raw)
    except KeyCheckError:
        raise
    except Exception:
        raise KeyCheckError('PRIVATE_BACKUP_UNAVAILABLE') from None


def main(argv: list[str] | None = None) -> int:
    """No path/value arguments, environment reads, persistent receipts or writes."""
    parser = _PrivateParser(description=__doc__)
    parser.add_argument('--check-private-toml', action='store_true')
    try:
        args = parser.parse_args(argv)
        if not args.check_private_toml:
            print(json.dumps({'status': 'PREVIEW', 'reads': 0, 'writes': 0, 'network_calls': 0}))
            return 0
        path = Path(getpass.getpass('Private backup file path (hidden; not a key value): '))
        result = check_file(path, project_root=Path(__file__).resolve().parent)
        print(json.dumps(result, sort_keys=True))
        return 0
    except KeyCheckError as error:
        print(json.dumps({'status': 'BLOCKED', 'code': str(error), 'values_output': False}))
        return 2
    except Exception:
        print(json.dumps({'status': 'BLOCKED', 'code': 'PRIVATE_KEY_CHECK_UNAVAILABLE', 'values_output': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
