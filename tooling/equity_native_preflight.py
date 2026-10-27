"""File-based native-temp preflight; no shell text or private-state access.

The owner wrapper invokes the default temp preflight only after confirmation.
Use --mode version for a read-only interpreter check without any temp probe.
The temp preflight binds --root to this helper's own ordinary clone before
creating, reading and removing one synthetic temporary file. This is a source
location check, not authentication or deployment approval.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat
import sys
import tempfile
from typing import Never, Sequence

PYTHON_VERSION = (3, 13, 9)
ERROR = "EQUITY_NATIVE_PREFLIGHT_FAILED"


def reject_links(path: Path) -> None:
    """Reject symlinks, Windows junctions and other reparse points in ancestry."""
    for entry in (path, *path.parents):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError(ERROR)


def source_root(value: str) -> Path:
    root = Path(value)
    helper = Path(__file__).absolute()
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError(ERROR)
    reject_links(root)
    reject_links(helper)
    if root.resolve(strict=True) != helper.parent.parent.resolve(strict=True):
        raise ValueError(ERROR)
    # Deliberately ordinary clones only, not redirected worktree .git files.
    for name, directory in ((".git", True), (".git/HEAD", False),
                            ("requirements.txt", False), ("tests", True)):
        entry = root / name
        reject_links(entry)
        if not (entry.is_dir() if directory else entry.is_file()):
            raise ValueError(ERROR)
    return root


def verify_python() -> None:
    if sys.version_info[:3] != PYTHON_VERSION:
        raise ValueError(ERROR)


def version_only() -> dict[str, object]:
    """Read only the running interpreter version; no path or temp operations."""
    verify_python()
    return {
        "status": "PYTHON_VERSION_VERIFIED",
        "python_version": "3.13.9",
        "source_binding_verified": False,
        "temp_probe_performed": False,
        "approval_authority": False,
    }


def _temp_probe() -> dict[str, object]:
    # Cleanup is confined to this newly created synthetic TemporaryDirectory.
    # A cleanup failure propagates; success is emitted only after context exit.
    with tempfile.TemporaryDirectory(prefix="equity-native-preflight-") as directory:
        temporary = Path(directory)
        reject_links(temporary)
        path = temporary / "synthetic.txt"
        with path.open("xb") as stream:
            stream.write(b"equity synthetic native temp probe\n")
        if path.read_bytes() != b"equity synthetic native temp probe\n":
            raise ValueError(ERROR)
    if temporary.exists():
        raise ValueError(ERROR)
    return {
        "status": "NATIVE_PREFLIGHT_VERIFIED",
        "python_version": "3.13.9",
        "source_binding_verified": True,
        "synthetic_temp_write_read_cleanup": True,
        "approval_authority": False,
    }


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise ValueError(ERROR)


def main(argv: Sequence[str] | None = None) -> int:
    stage = "python"
    try:
        parser = _Parser(add_help=False, allow_abbrev=False)
        parser.add_argument("--mode", choices=("preflight", "version"), default="preflight")
        parser.add_argument("--root")
        args = parser.parse_args(argv)
        if args.mode == "version" and args.root is None:
            result = version_only()
        elif args.mode == "preflight":
            verify_python()
            stage = "source"
            if args.root is None:
                raise ValueError(ERROR)
            source_root(args.root)
            stage = "temp"
            result = _temp_probe()
        else:
            raise ValueError(ERROR)
    except Exception:
        # Paths, interpreter errors, metadata and OS messages never reach output.
        print(json.dumps({"status": "BLOCKED", "code": ERROR, "stage": stage, "approval_authority": False}))
        return 2
    result["stage"] = stage
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
