"""Synthetic-only parser and consent tests. No credentials or market data."""
import io
import json
import socket
from typing import Any, Callable
from unittest.mock import patch

import pytest

from equity_coverage_view import (
    COHORT, FIXED, MAX_BYTES, PROVENANCE, CoverageRejected, parse_coverage, render_coverage,
)


def example(ordinals: tuple[int, ...] = (1,)) -> dict[str, Any]:
    windows = []
    for ordinal in ordinals:
        year = 2022 + (ordinal - 1) % 3
        windows.append({"ordinal": ordinal, "rows": 2,
                        "first_date": f"{year}-02-01", "last_date": f"{year}-02-02",
                        "symbol": COHORT[(ordinal - 1) // 3],
                        "requested_start": f"{year}-01-01", "requested_end": f"{year}-12-31",
                        "original_sha256": "a" * 64})
    return {**FIXED, "retained_windows": len(windows), "rows": 2 * len(windows),
            "windows": windows,
            "input_origins": ["INJECTED_SYNTHETIC_NOT_MARKET_EVIDENCE"] if windows else []}


def encode(value: object) -> bytes:
    return json.dumps(value).encode()


@pytest.mark.parametrize("ordinals", [(), (1,), (36,), tuple(range(1, 37)), (36, 1)])
def test_fixed_cohort_and_provenance(ordinals: tuple[int, ...]) -> None:
    report = parse_coverage(encode(example(ordinals)))
    assert report.rows == 2 * len(ordinals)
    assert report.provenance == PROVENANCE
    assert tuple(window.ordinal for window in report.windows) == ordinals


@pytest.mark.parametrize("raw", [b"", b" " * (MAX_BYTES + 1), b"\xff", b"{}", b"[]",
    b'{"status":NaN}', b'{"status":Infinity}', b'{"status":-Infinity}',
    b'{"status":1e999}', b'{"status":1.0}', b'{"status":0,"status":1}',
    b"[" * 2000 + b"]" * 2000, b'null', b'{"credential":"SECRET_SENTINEL"}',
    b'{"x":' + b"9" * 5000 + b'}', b'{} trailing'], ids=lambda raw: repr(raw)[:65])
def test_redacted_invalid_json(raw: bytes) -> None:
    with pytest.raises(CoverageRejected, match="^COVERAGE_REPORT_REJECTED$") as failure:
        parse_coverage(raw)
    assert failure.value.__suppress_context__
    assert "SECRET_SENTINEL" not in str(failure.value)


@pytest.mark.parametrize("raw", ["{}", bytearray(b"{}"), None, 42])
def test_explicit_bytes_only(raw: Any) -> None:
    with pytest.raises(CoverageRejected):
        parse_coverage(raw)


def test_exact_byte_limit() -> None:
    raw = encode(example())
    assert parse_coverage(raw + b" " * (MAX_BYTES - len(raw))).rows == 2
    with pytest.raises(CoverageRejected):
        parse_coverage(raw + b" " * (MAX_BYTES + 1 - len(raw)))


@pytest.mark.parametrize("key", list(FIXED))
def test_cannot_promote_or_change_fixed_status(key: str) -> None:
    value = example()
    value[key] = True if FIXED[key] is False else "FORGED"
    with pytest.raises(CoverageRejected):
        parse_coverage(encode(value))


@pytest.mark.parametrize("scope", ["root", "window"])
@pytest.mark.parametrize("action", ["extra", "missing", "duplicate"])
def test_exact_keys_and_nested_duplicates(scope: str, action: str) -> None:
    value = example()
    target = value if scope == "root" else value["windows"][0]
    key = "rows"
    if action == "extra":
        target["SECRET_SENTINEL"] = "<script>alert(1)</script>"
    elif action == "missing":
        del target[key]
    raw = encode(value)
    if action == "duplicate":
        # Duplicate keys are rejected at every nesting level, even with equal values.
        marker = b'"rows": 2'
        start = 0 if scope == "root" else raw.index(b'"windows"')
        position = raw.index(marker, start)
        raw = raw[:position] + marker + b", " + raw[position:]
    with pytest.raises(CoverageRejected):
        parse_coverage(raw)


@pytest.mark.parametrize("field,bad", [
    ("ordinal", True), ("ordinal", 0), ("ordinal", 37), ("ordinal", "1"),
    ("rows", True), ("rows", 0), ("rows", 3), ("rows", 1),
    ("symbol", "TCS"), ("symbol", "<img src=x>"),
    ("requested_start", "2022-01-02"), ("requested_end", "2023-12-31"),
    ("first_date", "2021-12-31"), ("last_date", "2025-01-01"),
    ("first_date", "2023-02-01"), ("first_date", "2022-02-30"),
    ("first_date", "2022-2-01"), ("first_date", "2022-02-01T00:00:00"),
    ("first_date", "2022-02-03"), ("last_date", None),
    ("original_sha256", "A" * 64), ("original_sha256", "a" * 63),
    ("original_sha256", "SECRET_SENTINEL"),
])
def test_invalid_window(field: str, bad: object) -> None:
    value = example()
    value["windows"][0][field] = bad
    with pytest.raises(CoverageRejected):
        parse_coverage(encode(value))


@pytest.mark.parametrize("field,bad", [
    ("rows", True), ("rows", 3), ("rows", -1), ("retained_windows", True),
    ("retained_windows", 2), ("windows", {}), ("input_origins", "native"),
    ("input_origins", []), ("input_origins", ["SECRET_SENTINEL"]),
    ("input_origins", ["NATIVE_TLS_NOT_PROVIDER_SIGNATURE"] * 2),
    ("input_origins", ["INJECTED_SYNTHETIC_NOT_MARKET_EVIDENCE", "NATIVE_TLS_NOT_PROVIDER_SIGNATURE"]),
    ("input_origins", ["NATIVE_TLS_NOT_PROVIDER_SIGNATURE", "INJECTED_SYNTHETIC_NOT_MARKET_EVIDENCE"]),
])
def test_invalid_aggregates(field: str, bad: object) -> None:
    value = example()
    value[field] = bad
    with pytest.raises(CoverageRejected):
        parse_coverage(encode(value))


def test_duplicate_window_and_overflow() -> None:
    for ordinals in [(1, 1), tuple(range(1, 37)) + (1,)]:
        with pytest.raises(CoverageRejected):
            parse_coverage(encode(example(ordinals)))


def test_leap_day_and_single_row() -> None:
    value = example((3,))
    window = value["windows"][0]
    window.update(rows=1, first_date="2024-02-29", last_date="2024-02-29")
    value["rows"] = 1
    assert parse_coverage(encode(value)).rows == 1
    window.update(first_date="2023-02-29", last_date="2023-02-29")
    with pytest.raises(CoverageRejected):
        parse_coverage(encode(value))


class Upload(io.BytesIO):
    def __init__(self, raw: bytes, *, size: int | None = None) -> None:
        super().__init__(raw)
        self.size = len(raw) if size is None else size
        self.read_sizes: list[int | None] = []

    def read(self, size: int | None = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)


class UI:
    def __init__(self, consent: bool = False, upload: Upload | None = None) -> None:
        self.consent, self.upload = consent, upload
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            assert name not in {"html", "markdown", "json", "write", "exception"}
            self.calls.append((name, args, kwargs))
            if name == "checkbox":
                assert kwargs["value"] is False
                return self.consent
            if name == "file_uploader":
                assert self.consent
                return self.upload
        return call


def test_consent_before_upload_and_empty_default() -> None:
    ui = UI()
    render_coverage(ui)
    assert not any(name in {"file_uploader", "metric", "dataframe"} for name, _, _ in ui.calls)
    ui = UI(consent=True)
    render_coverage(ui)
    names = [name for name, _, _ in ui.calls]
    assert names.index("warning") < names.index("checkbox") < names.index("file_uploader")
    assert "metric" not in names


def test_valid_upload_displays_only_safe_projection_without_network_or_files() -> None:
    upload = Upload(encode(example()))
    upload.seek(10)
    ui = UI(consent=True, upload=upload)
    with patch("builtins.open", side_effect=AssertionError("file read")), \
            patch.object(socket, "socket", side_effect=AssertionError("network")):
        render_coverage(ui)
    assert upload.read_sizes == [MAX_BYTES + 1]
    rendered = repr(ui.calls)
    assert PROVENANCE in rendered
    assert "a" * 64 not in rendered
    assert "Reported rows" in rendered
    assert any(name == "dataframe" for name, _, _ in ui.calls)


@pytest.mark.parametrize("oversize", [True, False])
def test_size_and_error_redaction(oversize: bool) -> None:
    upload = Upload(b'{"token":"SECRET_SENTINEL"}', size=MAX_BYTES + 1 if oversize else None)
    ui = UI(consent=True, upload=upload)
    render_coverage(ui)
    assert upload.read_sizes == ([] if oversize else [MAX_BYTES + 1])
    assert any(name == "error" for name, _, _ in ui.calls)
    assert "SECRET_SENTINEL" not in repr(ui.calls)
    assert not any(name in {"metric", "dataframe"} for name, _, _ in ui.calls)


def test_lying_upload_size_and_read_exception_are_redacted() -> None:
    upload = Upload(b" " * (MAX_BYTES + 2), size=1)
    ui = UI(consent=True, upload=upload)
    render_coverage(ui)
    assert any(name == "error" for name, _, _ in ui.calls)
    assert upload.read_sizes == [MAX_BYTES + 1]
    upload = Upload(b"{}")
    with patch.object(upload, "read", side_effect=OSError("SECRET_SENTINEL")):
        ui = UI(consent=True, upload=upload)
        render_coverage(ui)
    assert "SECRET_SENTINEL" not in repr(ui.calls)


def test_consent_revocation_does_not_read_previous_upload() -> None:
    upload = Upload(encode(example()))
    render_coverage(UI(consent=False, upload=upload))
    assert upload.read_sizes == []


def test_oversized_hosted_buffer_rejected_before_seek_read_or_getvalue() -> None:
    upload = Upload(b"", size=MAX_BYTES + 1)
    ui = UI(consent=True, upload=upload)
    with patch.object(upload, "seek") as seek, patch.object(upload, "read") as read, \
            patch.object(upload, "getvalue") as getvalue:
        render_coverage(ui)
    seek.assert_not_called()
    read.assert_not_called()
    getvalue.assert_not_called()
    assert any(name == "error" for name, _, _ in ui.calls)
    assert not any(name in {"metric", "dataframe"} for name, _, _ in ui.calls)
