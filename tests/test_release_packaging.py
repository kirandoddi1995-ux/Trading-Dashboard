"""Actual extracted-artifact probes plus deterministic dependency closure tests."""
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

import package_release
from release_verification import MANIFEST, release_members, verify_archive


def source(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def archive(root, entries):
    target = root / "fixture.zip"
    with zipfile.ZipFile(target, "w") as bundle:
        manifest = {}
        for name, text in entries.items():
            data = text.encode()
            bundle.writestr(name, data)
            manifest[name] = hashlib.sha256(data).hexdigest()
        bundle.writestr(MANIFEST, json.dumps(manifest))
    return target


def test_transitive_lazy_relative_and_literal_dynamic_imports(tmp_path):
    source(tmp_path, "app.py", "import first\ndef later():\n import plugin\n")
    source(tmp_path, "first.py", "from pkg import child\n")
    source(tmp_path, "pkg/__init__.py", "from . import child\n")
    source(tmp_path, "pkg/child.py", "from .nested import value\n")
    source(tmp_path, "pkg/nested.py", "value = 1\n")
    source(tmp_path, "plugin.py", "import importlib\ndef load():\n return importlib.import_module('future_module')\n")
    source(tmp_path, "future_module.py", "value = 2\n")
    source(tmp_path, "unrelated.py", "raise RuntimeError('never include')\n")
    source(tmp_path, "token.json", '{"secret":"fixture"}')
    source(tmp_path, ".streamlit/secrets.toml", 'password="fixture"')
    assert release_members(tmp_path, ["app.py"]) == sorted([
        "app.py", "first.py", "pkg/__init__.py", "pkg/child.py",
        "pkg/nested.py", "plugin.py", "future_module.py",
    ])


def test_current_application_missing_modules_are_discovered():
    root = Path(__file__).resolve().parents[1]
    members = release_members(root, ["app.py"])
    assert set([
        "equity_scan_repository.py", "equity_positions.py", "equity_runtime_health.py",
        "equity_scan_profiling.py", "equity_evidence_delivery.py", "equity_manual_review.py",
        "equity_observation_capture.py", "equity_checkpoint_delivery.py",
    ]).issubset(members)
    assert "get_drive_token.py" not in members


def test_extracted_import_succeeds_without_source_tree(tmp_path):
    target = archive(tmp_path, {"app.py": "import sibling\nassert sibling.VALUE == 42\n",
                                "sibling.py": "VALUE = 42\n"})
    assert verify_archive(target)["import_verified"]


def test_missing_dependency_cannot_leak_from_pythonpath(tmp_path, monkeypatch):
    source(tmp_path, "missing_release_dependency.py", "VALUE = 42\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    target = archive(tmp_path, {"app.py": "import missing_release_dependency\n"})
    with pytest.raises(RuntimeError, match="Extracted release import failed"):
        verify_archive(target)


def test_probe_has_no_credentials_or_network(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "never-inherit-this-fixture")
    target = archive(tmp_path, {"app.py": "import os, socket\nassert 'DATABASE_URL' not in os.environ\n"
                               "try:\n socket.getaddrinfo('example.com', 443)\n"
                               "except RuntimeError:\n pass\nelse:\n raise AssertionError('network allowed')\n"})
    assert verify_archive(target)["import_verified"]


def test_exit_zero_without_import_completion_is_failure(tmp_path):
    with pytest.raises(RuntimeError, match="Extracted release import failed"):
        verify_archive(archive(tmp_path, {"app.py": "raise SystemExit(0)\n"}))


def test_hash_tampering_and_traversal_rejected(tmp_path):
    target = archive(tmp_path, {"../escape.py": "pass\n", "app.py": "pass\n"})
    with pytest.raises(ValueError, match="Unsafe archive member"):
        verify_archive(target)
    with zipfile.ZipFile(target, "w") as bundle:
        bundle.writestr("app.py", "pass\n")
        bundle.writestr(MANIFEST, json.dumps({"app.py": "0" * 64}))
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_archive(target)


def test_timeout_is_hard_failure(tmp_path):
    target = archive(tmp_path, {"app.py": "import time\ntime.sleep(10)\n"})
    with pytest.raises(RuntimeError, match="timed out"):
        verify_archive(target, timeout=.1)


def test_failed_build_preserves_previous_artifacts(tmp_path, monkeypatch):
    source(tmp_path, "app.py", "import absent_dependency\n")
    old_zip = tmp_path / "release-v22.5.7-futures-history-hotfix.zip"
    old_zip.write_bytes(b"previous-good-artifact")
    sidecar = tmp_path / MANIFEST
    sidecar.write_bytes(b"previous-manifest")
    monkeypatch.setattr(package_release, "FILES", ["app.py"])
    monkeypatch.setattr(package_release, "run_canaries", lambda root: {"ok": True})
    with pytest.raises(RuntimeError, match="Extracted release import failed"):
        package_release.package(tmp_path)
    assert old_zip.read_bytes() == b"previous-good-artifact"
    assert sidecar.read_bytes() == b"previous-manifest"
    assert not list(tmp_path.glob(".release-stage-*"))


def test_successful_build_publishes_only_verified_bundle(tmp_path, monkeypatch):
    source(tmp_path, "app.py", "import new_module\n")
    source(tmp_path, "new_module.py", "VALUE = 1\n")
    monkeypatch.setattr(package_release, "FILES", ["app.py"])
    monkeypatch.setattr(package_release, "run_canaries", lambda root: {"ok": True})
    target = package_release.package(tmp_path)
    with zipfile.ZipFile(target) as bundle:
        assert set(bundle.namelist()) == {"app.py", "new_module.py", MANIFEST}
        assert bundle.read(MANIFEST) == (tmp_path / MANIFEST).read_bytes()
