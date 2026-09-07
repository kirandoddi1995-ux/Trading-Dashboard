"""End-to-end smoke test for the deployed Streamlit entry point."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_app_imports_end_to_end() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, (
        "The deployed app entry point failed to import.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
