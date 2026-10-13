"""Offline source-specific timing analysis; never establishes an open session."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from research_integrity import hash_value

Kind = Literal['CASH_INDEX', 'CAS_EQUITY', 'EQUITY_DERIVATIVES']

UPSTOX_CAS = 'https://upstox.com/developer/api-documentation/announcements/closing-auction-session/'
NSE_FO = 'https://nsearchives.nseindia.com/content/circulars/FAOP74467.pdf'
NSE_POLICY = 'https://www.nseindia.com/static/market-data/nse-data-policy'
NSE_EOD = 'https://archives.nseindia.com/content/press/EOD_CM_n_FAO.pdf'
NSE_CAS = 'https://www.nseindia.com/static/products-services/closing-auction-session'
UPSTOX_TIMINGS = 'https://upstox.com/developer/api-documentation/get-market-timings/'


@dataclass(frozen=True)
class CalendarEvidence:
    session_date: date
    kind: Kind
    opening: datetime
    closing: datetime
    source_url: str
    evidence_sha256: str
    reviewed: bool = False
    special_session: bool = False


@dataclass(frozen=True)
class SourcePreparationDiagnostic:
    conclusion: str
    automated_route_status: str
    blockers: tuple[str, ...]
    owner_file_route: str = 'EXISTING_REVIEWED_EXPLICIT_OWNER_FILE_ONLY'
    network_calls: int = 0
    writes: int = 0
    session_prepared: bool = False
    approval_authority: bool = False


def diagnose_nse_source(*, browser_download_observed: bool | None,
                        python_transport_status: str | None) -> SourcePreparationDiagnostic:
    """Interpret supplied redacted observations; neither probe nor bypass a provider."""
    statuses = {'TRANSPORT_CHECK_COMPLETE', 'NSE_CLOSE_PROXY_ERROR', 'NSE_CLOSE_TLS_ERROR',
                'NSE_CLOSE_CONNECT_TIMEOUT', 'NSE_CLOSE_READ_TIMEOUT', 'NSE_CLOSE_TIMEOUT',
                'NSE_CLOSE_CONNECTION_ERROR', 'NSE_CLOSE_REQUEST_ERROR', 'NSE_CLOSE_HTTP_NON_200',
                'NSE_CLOSE_SIZE_LIMIT_EXCEEDED', 'NSE_CLOSE_EMPTY_BODY',
                'NSE_CLOSE_TRANSPORT_UNAVAILABLE', 'TRANSPORT_DIAGNOSTIC_UNAVAILABLE'}
    if ((browser_download_observed is not None and type(browser_download_observed) is not bool)
            or (python_transport_status is not None and python_transport_status not in statuses)):
        raise ValueError('OVERNIGHT_SOURCE_DIAGNOSTIC_INVALID')
    successful = python_transport_status == 'TRANSPORT_CHECK_COMPLETE'
    if python_transport_status is None:
        conclusion = 'PYTHON_TRANSPORT_UNOBSERVED'
    elif successful:
        conclusion = 'PYTHON_HTTP_BYTES_RECEIVED_NOT_CSV_OR_SOURCE_VALIDATION'
    elif browser_download_observed is True:
        conclusion = 'BROWSER_PYTHON_CLIENT_OR_ROUTE_DIFFERENCE_CAUSE_UNPROVEN'
    elif browser_download_observed is False:
        conclusion = 'BOTH_TRANSPORTS_UNAVAILABLE_CAUSE_UNPROVEN'
    else:
        conclusion = 'PYTHON_TRANSPORT_FAILED_BROWSER_UNOBSERVED_CAUSE_UNPROVEN'
    return SourcePreparationDiagnostic(conclusion, 'BLOCKED', (
        'SOURCE_SPECIFIC_ZERO_COST_USAGE_TERMS_UNVERIFIED',
        'UNATTENDED_SOURCE_TRANSPORT_NOT_COMMISSIONED',
        'DATED_INDEX_CSV_AND_RETRIEVAL_PROVENANCE_REQUIRE_REVIEW') +
        (() if successful else ('PYTHON_NETWORK_ROUTE_UNAVAILABLE_OR_UNOBSERVED',)))


@dataclass(frozen=True)
class CloseAnalysis:
    status: str
    blockers: tuple[str, ...]
    regular_reference_close: str
    full_five_minute_windows: int | None
    verification_not_before: datetime | None
    original_capture_slots: int = 75
    approval_authority: bool = False
    owner_index_audit_at: datetime | None = None


def upstox_timing(payload: dict[str, Any], day: date, kind: Kind,
                  *, reviewed: bool = False, special_session: bool = False) -> CalendarEvidence:
    """Parse caller-supplied timing JSON only; no market request or holiday inference."""
    if kind not in ('CASH_INDEX', 'CAS_EQUITY', 'EQUITY_DERIVATIVES'):
        raise ValueError('OVERNIGHT_SOURCE_KIND_INVALID')
    code = 'NFO' if kind == 'EQUITY_DERIVATIVES' else 'NSE'
    rows = payload.get('data')
    if payload.get('status') != 'success' or not isinstance(rows, list) or len(rows) > 32:
        raise ValueError('OVERNIGHT_TIMINGS_INVALID')
    matches = [row for row in rows if isinstance(row, dict) and row.get('exchange') == code]
    if len(matches) != 1:
        raise ValueError('OVERNIGHT_SOURCE_TIMING_MISSING_OR_AMBIGUOUS')
    row = matches[0]
    if any(type(row.get(k)) is not int for k in ('start_time', 'end_time')):
        raise ValueError('OVERNIGHT_TIMING_TIMESTAMP_INVALID')
    ist = timezone(timedelta(hours=5, minutes=30))
    try:
        opening = datetime.fromtimestamp(row['start_time'] / 1000, ist)
        closing = datetime.fromtimestamp(row['end_time'] / 1000, ist)
    except (ValueError, OverflowError, OSError):
        raise ValueError('OVERNIGHT_TIMING_TIMESTAMP_INVALID') from None
    if opening.date() != day or closing.date() != day or closing <= opening:
        raise ValueError('OVERNIGHT_TIMING_DATE_MISMATCH')
    return CalendarEvidence(day, kind, opening, closing, UPSTOX_TIMINGS,
                            hash_value(payload), reviewed, special_session)


def analyze_close(day: date, kind: Kind, evidence: CalendarEvidence | None = None) -> CloseAnalysis:
    """Reference hours are diagnostics, not a substitute for a dated calendar."""
    import re

    if kind not in ('CASH_INDEX', 'CAS_EQUITY', 'EQUITY_DERIVATIVES'):
        raise ValueError('OVERNIGHT_SOURCE_KIND_INVALID')
    reference = '15:40' if kind == 'EQUITY_DERIVATIVES' and day >= date(2026, 8, 3) else '15:30'
    if kind == 'CAS_EQUITY':
        reference = '15:15 continuous; 15:35 NSE auction confirmation; separate post-close session'
    blockers = []
    if evidence is None:
        return CloseAnalysis('BLOCKED', ('DATED_SOURCE_CALENDAR_MISSING',), reference, None, None)
    if (evidence.session_date != day or evidence.kind != kind or evidence.reviewed is not True
            or not evidence.source_url.startswith('https://')
            or re.fullmatch(r'[0-9a-f]{64}', evidence.evidence_sha256) is None):
        blockers.append('DATED_SOURCE_CALENDAR_UNVERIFIED')
    opening, closing = evidence.opening, evidence.closing
    if (opening.utcoffset() != timedelta(hours=5, minutes=30)
            or closing.utcoffset() != timedelta(hours=5, minutes=30)
            or opening.date() != day or closing.date() != day or closing <= opening):
        blockers.append('SESSION_WINDOW_INVALID')
    if evidence.special_session:
        blockers.append('SPECIAL_SESSION_REQUIRES_SEPARATE_POLICY')
    if kind == 'CAS_EQUITY':
        blockers.append('AUCTION_AND_CONTINUOUS_BARS_REQUIRE_SEPARATE_POLICY')
    if not blockers and (opening.strftime('%H:%M:%S') != '09:15:00'
                         or closing.strftime('%H:%M:%S') != reference + ':00'
                         or opening.microsecond or closing.microsecond):
        blockers.append('REFERENCE_TIMING_CONFLICT_REQUIRES_REVIEW')
    if blockers:
        return CloseAnalysis('BLOCKED', tuple(blockers), reference, None, None)
    slots = int((closing - opening).total_seconds() // 300)
    return CloseAnalysis('SOURCE_WINDOW_REVIEWED', (), reference, slots, closing + timedelta(minutes=5),
                         owner_index_audit_at=closing.replace(hour=15, minute=40)
                         if kind == 'CASH_INDEX' else None)
