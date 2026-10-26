"""Synthetic fixtures only: no captured alerts or credentials."""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
import socket
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import dependency_alert_review as review


def alert(number: int = 1, **changes: object) -> dict[str, Any]:
    result: dict[str, Any] = {
        "number": number, "state": "open",
        "dependency": {"manifest_path": "requirements.txt", "package": {
            "ecosystem": "pip", "name": "sample-package",
        }},
        "security_advisory": {"severity": "critical", "ghsa_id": "GHSA-2345-6789-cfgh"},
    }
    result.update(changes)
    return result


def test_grouping_and_open_counts_do_not_clear_closed_alerts() -> None:
    rows = [alert(3), alert(1, state="fixed"), alert(2, state="dismissed"),
            alert(4, state="auto_dismissed")]
    rows[2]["security_advisory"]["severity"] = "high"
    rows[3]["dependency"]["manifest_path"] = "archive/requirements.txt"
    rows[3]["dependency"]["package"]["ecosystem"] = "npm"
    before = json.dumps(rows)
    result = review.summarize_alerts(rows)
    assert json.dumps(rows) == before
    assert [item.number for item in review.normalize_alerts(rows)] == [1, 2, 3, 4]
    assert result["total_alerts"] == 4
    assert result["open_alerts"] == 1
    assert result["severity_counts"] == {"critical": 3, "high": 1, "moderate": 0, "low": 0}
    assert result["open_severity_counts"] == {"critical": 1, "high": 0, "moderate": 0, "low": 0}
    assert result["state_counts"] == dict.fromkeys(review.STATES, 1)
    assert result["ghsas"] == [{"ghsa": "GHSA-2345-6789-cfgh", "total": 4, "open": 1}]
    assert result["packages"] == [
        {"ecosystem": "npm", "package": "sample-package", "total": 1, "open": 0},
        {"ecosystem": "pip", "package": "sample-package", "total": 3, "open": 1},
    ]


@pytest.mark.parametrize("path", [
    "requirements.txt", "constraints.txt", "requirements-forward-operations.txt",
    "requirements-archive.txt", "nested/requirements.txt",
])
def test_manifest_labels_are_only_locations(path: str) -> None:
    row = alert()
    row["dependency"]["manifest_path"] = path
    result = review.summarize_alerts([row])
    manifests = result["manifests"]
    assert isinstance(manifests, list)
    assert manifests[0]["location_label"] == (
        "known_profile_declaration" if path in review.KNOWN_DECLARATIONS else "requires_own_audit"
    )
    assert result["installed_profile_exposure"] == "UNVERIFIED"
    assert result["manifest_labels_are_exposure_proof"] is False


@pytest.mark.parametrize("value", [None, {}, "secret", (), [None], [1], [True], [[]]])
def test_invalid_top_level_and_rows(value: object) -> None:
    with pytest.raises(ValueError, match=f"^{review.ERROR}$"):
        review.normalize_alerts(value)


@pytest.mark.parametrize("number", [True, False, 0, -1, 1.0, "1", None, review.MAX_ALERT_NUMBER + 1])
def test_alert_number_is_strict_positive_bounded_integer(number: object) -> None:
    with pytest.raises(ValueError, match=f"^{review.ERROR}$"):
        review.normalize_alerts([alert(number=number)])  # type: ignore[arg-type]


def test_duplicate_numbers_fail_atomically() -> None:
    with pytest.raises(ValueError, match=f"^{review.ERROR}$"):
        review.normalize_alerts([alert(), alert(state="fixed")])


@pytest.mark.parametrize("field", ["number", "state", "dependency", "security_advisory"])
def test_required_fields(field: str) -> None:
    row = alert()
    del row[field]
    with pytest.raises(ValueError, match=f"^{review.ERROR}$"):
        review.normalize_alerts([row])


@pytest.mark.parametrize("section,field,value", [
    ("dependency", "manifest_path", None),
    ("dependency", "package", []),
    ("security_advisory", "severity", "unknown"),
    ("security_advisory", "severity", "CRITICAL"),
    ("security_advisory", "ghsa_id", "GHSA-secret"),
    ("security_advisory", "ghsa_id", 9),
])
def test_nested_schema(section: str, field: str, value: object) -> None:
    row = alert()
    row[section][field] = value
    with pytest.raises(ValueError, match=f"^{review.ERROR}$"):
        review.normalize_alerts([row])


@pytest.mark.parametrize("value", [None, 12, True, [], "", " ", " padded", "bad\nname", "bad\x00name", "x" * 201])
@pytest.mark.parametrize("field", ["name", "ecosystem"])
def test_package_names_are_bounded_strings(field: str, value: object) -> None:
    row = alert()
    row["dependency"]["package"][field] = value
    with pytest.raises(ValueError, match=f"^{review.ERROR}$"):
        review.normalize_alerts([row])


@pytest.mark.parametrize("path", [
    "../secret", "a/../secret", "./requirements.txt", "/etc/secret", "//server/share",
    "C:/secret", "C:secret", "a\\..\\secret", "a//b", "a/", "a/./b",
    "a/%2e%2e/b", "a\n/b", "x" * 513,
])
def test_invalid_manifest_paths(path: str) -> None:
    row = alert()
    row["dependency"]["manifest_path"] = path
    with pytest.raises(ValueError, match=f"^{review.ERROR}$"):
        review.normalize_alerts([row])


def test_bounds_and_boundary_values() -> None:
    row = alert(review.MAX_ALERT_NUMBER)
    row["dependency"]["manifest_path"] = "x" * review.MAX_PATH_LENGTH
    row["dependency"]["package"]["name"] = "x" * review.MAX_NAME_LENGTH
    assert len(review.normalize_alerts([row])) == 1
    rows = [alert(i + 1) for i in range(review.MAX_ALERTS)]
    assert len(review.normalize_alerts(rows)) == review.MAX_ALERTS
    with pytest.raises(ValueError, match=f"^{review.ERROR}$"):
        review.normalize_alerts(rows + [alert(review.MAX_ALERTS + 1)])
    raw = b"[]" + b" " * (review.MAX_INPUT_BYTES - 2)
    assert review.review_json(raw)["total_alerts"] == 0
    with pytest.raises(ValueError, match=f"^{review.ERROR}$"):
        review.review_json(raw + b" ")


@pytest.mark.parametrize("raw", [
    b"secret", b"\xff", b"{}", b"null", b"[NaN]", b"[Infinity]",
    b'[{"number":1,"number":2}]', b"[" * 2000 + b"]" * 2000,
])
def test_json_failure_is_fixed_and_redacted(raw: bytes) -> None:
    with pytest.raises(ValueError) as caught:
        review.review_json(raw)
    assert str(caught.value) == review.ERROR
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("attested", [False, True])
def test_empty_export_never_approves_even_if_attested(attested: bool) -> None:
    result = review.review_json(b"[]", complete_export_owner_attested=attested)
    assert result["input_sha256"] == hashlib.sha256(b"[]").hexdigest()
    assert result["complete_export_owner_attested"] is attested
    assert result["attestation_is_authentication"] is False
    assert result["completeness_independently_verified"] is False
    assert result["approval_authority"] is False
    assert result["status"] == review.STATUS
    assert result["total_alerts"] == result["open_alerts"] == 0
    assert result["independently_verified"] is False
    assert result["profile_audits_clear_repository_alerts"] is False
    assert "owner_reported_context" not in result
    assert "dependabot_total" not in result
    assert "clean_profile_pip_audits" not in result
    assert result["severity_counts"] == dict.fromkeys(review.SEVERITIES, 0)


def test_attestation_must_be_bool() -> None:
    with pytest.raises(ValueError, match=f"^{review.ERROR}$"):
        review.summarize_alerts([], complete_export_owner_attested=1)  # type: ignore[arg-type]


def test_unknown_metadata_is_discarded() -> None:
    result = review.summarize_alerts([alert(secret="PRIVATE_SENTINEL", html_url="PRIVATE_SENTINEL")])
    assert "PRIVATE_SENTINEL" not in json.dumps(result)


def test_preview_has_zero_file_and_network_io(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError("unexpected I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(os, "stat", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    assert review.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["source"] == "PREVIEW_NO_EXPORT_READ"
    assert "owner_reported_context" not in result
    assert "dependabot_total" not in result
    assert "clean_profile_pip_audits" not in result
    assert "severity_counts" not in result
    assert result["independently_verified"] is False
    assert result["profile_audits_clear_repository_alerts"] is False
    assert "total_alerts" not in result
    assert "input_sha256" not in result
    assert result["approval_authority"] is False


def mock_export(monkeypatch: pytest.MonkeyPatch, raw: bytes, *, size: int | None = None) -> list[int]:
    reads: list[int] = []

    class Export(io.BytesIO):
        def fileno(self) -> int:
            return 123

        def read(self, size: int | None = -1) -> bytes:
            assert size == review.MAX_INPUT_BYTES
            reads.append(size)
            return super().read(size)

    def open_export(self: Path, mode: str) -> Export:
        assert self.is_absolute()
        assert mode == "rb"
        return Export(raw)

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "open", open_export)
    monkeypatch.setattr(os, "fstat", lambda fd: SimpleNamespace(
        st_mode=stat.S_IFREG, st_size=len(raw) if size is None else size,
    ))
    return reads


def test_explicit_check_hashes_exact_bytes_without_writes(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    path = Path(__file__).absolute().with_name("PRIVATE_SENTINEL.json")
    raw = json.dumps([alert()]).encode() + b"\n"
    reads = mock_export(monkeypatch, raw)
    assert review.main(["--input", str(path), "--check", "--complete-export-owner-attested"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["total_alerts"] == 1
    assert result["complete_export_owner_attested"] is True
    assert result["approval_authority"] is False
    assert reads == [review.MAX_INPUT_BYTES]


@pytest.mark.parametrize("size", [0, 3, review.MAX_INPUT_BYTES + 1])
def test_cli_rejects_size_change_during_read(size: int, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    mock_export(monkeypatch, b"[]")
    stats = iter([2, size])
    monkeypatch.setattr(os, "fstat", lambda fd: SimpleNamespace(
        st_mode=stat.S_IFREG, st_size=next(stats),
    ))
    path = Path(__file__).absolute().with_name("PRIVATE_SENTINEL.json")
    assert review.main(["--input", str(path), "--check"]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == review.ERROR


def test_mapping_field_bound() -> None:
    row = alert()
    row.update({f"unused-{index}": None for index in range(review.MAX_OBJECT_FIELDS)})
    with pytest.raises(ValueError, match=f"^{review.ERROR}$"):
        review.normalize_alerts([row])


@pytest.mark.parametrize("state", ["closed", "OPEN", True, 1, None])
def test_invalid_states(state: object) -> None:
    with pytest.raises(ValueError, match=f"^{review.ERROR}$"):
        review.normalize_alerts([alert(state=state)])


@pytest.mark.parametrize("args", [
    ["--check"], ["--input", "PRIVATE_SENTINEL"],
    ["--input", "PRIVATE_SENTINEL", "--check"], ["--PRIVATE_SENTINEL"],
    ["--input", "", "--check"], ["--input", ""], ["--inp", "PRIVATE_SENTINEL"],
])
def test_cli_invalid_arguments_are_redacted(args: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert review.main(args) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": review.ERROR, "status": review.STATUS, "approval_authority": False,
    }
    assert "PRIVATE_SENTINEL" not in captured.out


@pytest.mark.parametrize("kind", ["missing", "directory", "oversize", "malformed", "read_error", "nonregular", "growing"])
def test_cli_input_errors_are_redacted(kind: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    path = Path(__file__).absolute().with_name("PRIVATE_SENTINEL.json")
    raw = b"PRIVATE_SENTINEL" if kind == "malformed" else b"[]"
    if kind == "growing":
        raw = b" " * (review.MAX_INPUT_BYTES + 1)
    reads = mock_export(monkeypatch, raw, size=2 if kind == "growing" else None)
    if kind in ("missing", "directory"):
        monkeypatch.setattr(Path, "is_file", lambda self: False)
    elif kind == "oversize":
        monkeypatch.setattr(os, "fstat", lambda fd: SimpleNamespace(
            st_mode=stat.S_IFREG, st_size=review.MAX_INPUT_BYTES + 1,
        ))
    elif kind == "nonregular":
        monkeypatch.setattr(os, "fstat", lambda fd: SimpleNamespace(
            st_mode=stat.S_IFIFO, st_size=0,
        ))
    elif kind == "read_error":
        def fail_open(self: Path, mode: str) -> io.BytesIO:
            raise OSError("PRIVATE_SENTINEL")
        monkeypatch.setattr(Path, "open", fail_open)
    assert review.main(["--input", str(path), "--check"]) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "PRIVATE_SENTINEL" not in captured.out
    assert json.loads(captured.out)["error"] == review.ERROR
    if kind in ("missing", "directory", "oversize", "nonregular"):
        assert reads == []
