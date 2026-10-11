"""Offline transient-lock cleanup tests; source staging locally, root after upload."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def reviewed() -> ModuleType:
    """Load only the explicit reviewed source, never other local runtime drafts."""
    root = Path(__file__).resolve().parents[1]
    staged = root / 'staged_release_timeout_fix/release_verification.py'
    source = staged if staged.is_file() else root / 'release_verification.py'
    spec = importlib.util.spec_from_file_location('reviewed_timeout', source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_transient_cleanup_locks_do_not_mask_original_timeout(monkeypatch: Any) -> None:
    module = reviewed()
    calls: list[int] = []
    delays: list[float] = []

    class Temporary:
        name = 'synthetic-no-directory-created'

        def cleanup(self) -> None:
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError('synthetic transient lock')

    monkeypatch.setattr(module.tempfile, 'TemporaryDirectory', lambda **_kw: Temporary())
    monkeypatch.setattr(module.time, 'sleep', delays.append)
    with pytest.raises(RuntimeError, match='^original timeout$'):
        with module._verification_workspace():
            raise RuntimeError('original timeout')
    assert len(calls) == 3 and delays == [.05, .05]


def test_permanent_cleanup_failure_is_not_ignored(monkeypatch: Any) -> None:
    module = reviewed()
    calls: list[int] = []

    class Temporary:
        name = 'synthetic-no-directory-created'

        def cleanup(self) -> None:
            calls.append(1)
            raise PermissionError('synthetic permanent lock')

    monkeypatch.setattr(module.tempfile, 'TemporaryDirectory', lambda **_kw: Temporary())
    monkeypatch.setattr(module.time, 'sleep', lambda _seconds: None)
    with pytest.raises(PermissionError, match='permanent lock'):
        with module._verification_workspace():
            pass
    assert len(calls) == 20
