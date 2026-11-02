"""Draft, bounded coverage-only viewer. No filesystem, network or trading access."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re
from typing import Any, Never as _Never

MAX_BYTES = 64 * 1024
PROVENANCE = "USER_SUPPLIED_NOT_AUTHENTICATED"
COHORT = ("RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "ITC", "LT",
          "SUNPHARMA", "BHARTIARTL", "NTPC", "TATASTEEL", "M&M")
ORIGINS = frozenset({"NATIVE_TLS_NOT_PROVIDER_SIGNATURE",
                     "INJECTED_SYNTHETIC_NOT_MARKET_EVIDENCE"})
FIXED: dict[str, str | int | bool] = {
    "status": "PRIVATE_COVERAGE_NOT_PERFORMANCE", "planned_windows": 36,
    "exchange_calendar_verified": False, "corporate_actions_verified": False,
    "price_adjustment_basis": "NOT_ESTABLISHED",
    "missing_exchange_sessions": "NOT_ESTABLISHED_WITHOUT_VERIFIED_CALENDAR",
    "baseline_evaluation": "INSUFFICIENT_COHORT_INPUTS_AND_SOURCE_RECONCILIATION",
    "training_eligible": False, "promotion_authorised": False,
    "performance_claim_verified": False, "custody_verified": False,
}
WINDOW_KEYS = frozenset({"ordinal", "rows", "first_date", "last_date", "symbol",
                         "requested_start", "requested_end", "original_sha256"})


class CoverageRejected(ValueError):
    """Only a fixed redacted message, never an input excerpt."""


def _reject() -> _Never:
    raise CoverageRejected("COVERAGE_REPORT_REJECTED")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


def _no_number(_value: str) -> _Never:
    _reject()


def _date(value: object) -> date:
    if type(value) is not str or not re.fullmatch(r"202[234]-[0-9]{2}-[0-9]{2}", value):
        _reject()
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        _reject()
    return parsed


@dataclass(frozen=True)
class WindowCoverage:
    ordinal: int
    symbol: str
    year: int
    rows: int
    first_date: str
    last_date: str


@dataclass(frozen=True)
class Coverage:
    windows: tuple[WindowCoverage, ...]
    rows: int
    input_origins: tuple[str, ...]
    provenance: str = PROVENANCE


def parse_coverage(raw: bytes) -> Coverage:
    """Validate campaign._coverage's exact shape, not authenticity or admission.

    Accept only explicit bytes, never paths or files. All failures are redacted.
    Hash syntax is checked; originals are never opened or authenticated.
    """
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
            _reject()
        value: Any = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                           parse_constant=_no_number, parse_float=_no_number)
        keys = set(FIXED) | {"retained_windows", "rows", "windows", "input_origins"}
        if type(value) is not dict or set(value) != keys:
            _reject()
        for key, expected in FIXED.items():
            if type(value[key]) is not type(expected) or value[key] != expected:
                _reject()
        windows = value["windows"]
        if type(windows) is not list or len(windows) > 36:
            _reject()
        if type(value["retained_windows"]) is not int or value["retained_windows"] != len(windows):
            _reject()
        if type(value["rows"]) is not int or not 0 <= value["rows"] <= 36 * 366:
            _reject()
        origins = value["input_origins"]
        if (type(origins) is not list or len(origins) > min(2, len(windows))
                or any(type(origin) is not str or origin not in ORIGINS for origin in origins)
                or origins != sorted(set(origins)) or bool(origins) != bool(windows)):
            _reject()
        seen: set[int] = set()
        accepted: list[WindowCoverage] = []
        for window in windows:
            if type(window) is not dict or set(window) != WINDOW_KEYS:
                _reject()
            ordinal = window["ordinal"]
            if type(ordinal) is not int or not 1 <= ordinal <= 36 or ordinal in seen:
                _reject()
            seen.add(ordinal)
            symbol, year = COHORT[(ordinal - 1) // 3], 2022 + (ordinal - 1) % 3
            if (window["symbol"] != symbol or window["requested_start"] != f"{year}-01-01"
                    or window["requested_end"] != f"{year}-12-31"):
                _reject()
            first, last = _date(window["first_date"]), _date(window["last_date"])
            rows = window["rows"]
            if (first.year != year or last.year != year or first > last
                    or type(rows) is not int or not 1 <= rows <= (last - first).days + 1
                    or (rows == 1 and first != last) or (rows > 1 and first == last)):
                _reject()
            digest = window["original_sha256"]
            if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
                _reject()
            accepted.append(WindowCoverage(ordinal, symbol, year, rows, first.isoformat(), last.isoformat()))
        if value["rows"] != sum(window.rows for window in accepted):
            _reject()
        return Coverage(tuple(accepted), value["rows"], tuple(origins))
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise CoverageRejected("COVERAGE_REPORT_REJECTED") from None


def render_coverage(st: Any) -> None:
    """Consent precedes upload; the host receives bytes before validation.

    Reject an oversized hosted buffer by size before seeking or reading it.
    Streamlit's transport buffering and retention are outside this leaf.
    """
    st.subheader("Equity coverage report (draft)")
    st.info("No measured edge or financial approval is available from this viewer.")
    st.caption("Coverage only. Calendar and corporate actions: unverified. Price adjustments: not established. "
               "Performance and custody: unverified. Training and promotion: not authorised. No-Trade policy unchanged.")
    st.warning("Selecting a file uploads it to the app host. Only upload coverage.json if you approve sending "
               "its symbols, dates, counts and original-file hashes to that host. Never upload prices, raw responses "
               "or credentials. This viewer never scans your PC. Validation is limited to 64 KiB after upload; "
               "host upload limits and retention require separate privacy review.")
    if not st.checkbox("I consent to sending my coverage report to this app host", value=False,
                       key="equity_coverage_host_consent"):
        st.caption("No report loaded.")
        return
    upload = st.file_uploader("Choose campaign coverage.json (maximum 64 KiB)", type=["json"],
                              accept_multiple_files=False, key="equity_coverage_upload")
    if upload is None:
        st.caption("No report loaded.")
        return
    try:
        # Check metadata BEFORE reading/copying the already-hosted buffer.
        if type(upload.size) is not int or not 0 < upload.size <= MAX_BYTES:
            _reject()
        upload.seek(0)
        report = parse_coverage(upload.read(MAX_BYTES + 1))
    except Exception:
        st.error("Coverage report rejected. Check its format and size locally; report contents are not displayed.")
        return
    st.caption(PROVENANCE + " - structure checked only; source and original hashes are not authenticated.")
    st.metric("Reported retained windows", f"{len(report.windows)} / 36")
    st.metric("Reported rows", report.rows)
    st.caption("Window coverage is not exchange-session completeness. No baseline or return calculation is performed.")
    if "INJECTED_SYNTHETIC_NOT_MARKET_EVIDENCE" in report.input_origins:
        st.warning("Report declares synthetic inputs; these are not market evidence.")
    if report.windows:
        st.dataframe([{"Symbol": window.symbol, "Year": window.year, "Reported rows": window.rows,
                       "First reported date": window.first_date, "Last reported date": window.last_date}
                      for window in report.windows], hide_index=True, use_container_width=True)
    else:
        st.caption("The supplied report declares zero retained windows.")
