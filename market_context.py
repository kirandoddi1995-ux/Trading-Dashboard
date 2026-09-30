"""Level-one market context. No order, sizing, scoring or governance interface."""
from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

VERSION = 'market-context-v1'
MAX_BYTES = 1024 * 1024
MAX_RECORDS = 1500
KINDS = {'GIFT', 'VIX', 'VIX_CLOSE', 'GSEC10Y', 'USDINR', 'PARTICIPANT_OI', 'EVENT', 'REBALANCE'}
DOMAINS = {
    'GIFT': ('upstox.com', 'nseix.com'), 'VIX': ('upstox.com', 'nseindia.com', 'niftyindices.com'),
    'VIX_CLOSE': ('upstox.com', 'nseindia.com', 'niftyindices.com'),
    'GSEC10Y': ('rbi.org.in', 'fbil.org.in', 'ccilindia.com'),
    'USDINR': ('upstox.com', 'fbil.org.in', 'rbi.org.in'),
    'PARTICIPANT_OI': ('nseindia.com',),
    'EVENT': ('rbi.org.in', 'indiabudget.gov.in', 'eci.gov.in'),
    'REBALANCE': ('msci.com', 'niftyindices.com', 'nseindia.com'),
}
UNITS = {'GIFT': 'POINTS', 'VIX': 'VIX_POINTS', 'VIX_CLOSE': 'VIX_POINTS',
         'GSEC10Y': 'PERCENT', 'USDINR': 'INR_PER_USD', 'PARTICIPANT_OI': 'CONTRACTS'}
# Display freshness only: not exchange calendars and not approval policies.
AGES = {'GIFT': 1200, 'VIX': 120, 'VIX_CLOSE': 4*86400, 'GSEC10Y': 4*86400,
        'USDINR': 86400, 'PARTICIPANT_OI': 4*86400}
SECTOR_TAGS = {
    'IT': ['USD/INR', 'US technology demand'],
    'Banks': ['RBI policy/liquidity', 'G-Sec curve', 'domestic credit'],
    'Metals': ['China activity', 'global metals prices', 'USD/INR'],
    'Aviation': ['Brent fuel costs', 'USD/INR', 'domestic demand'],
    'FMCG': ['rural demand/monsoon', 'input costs', 'domestic consumption'],
    'Other / unknown': ['No reviewed exposure tags'],
}


class ContextError(ValueError):
    """Fixed safe codes only."""


def stamp(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise ContextError('INVALID_CONTEXT_TIME') from None


def number(value):
    try:
        if value is None or isinstance(value, bool):
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ContextError('INVALID_CONTEXT_NUMBER') from None


def canonical(value):
    try:
        data = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if len(data) > MAX_BYTES:
            raise ValueError
        return data
    except (TypeError, ValueError):
        raise ContextError('CONTEXT_PAYLOAD_LIMIT_OR_SCHEMA') from None


def source_allowed(kind, url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        return (parsed.scheme == 'https' and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and any(host == d or host.endswith('.'+d) for d in DOMAINS[kind]))
    except (TypeError, ValueError, KeyError):
        return False


def record(raw, *, received_at, origin='MANUAL_SOURCE_ENTRY'):
    """Stamp first-known time at ingestion, never trust an uploaded available_at."""
    row = dict(raw)
    kind = row.get('kind')
    if kind not in KINDS or not row.get('series') or not source_allowed(kind, row.get('source_url', '')):
        raise ContextError('CONTEXT_IDENTITY_OR_SOURCE_INVALID')
    receipt = stamp(received_at)
    effective = stamp(row['source_at'])
    published = stamp(row['published_at']) if row.get('published_at') else None
    if effective > receipt or (published and published > receipt):
        raise ContextError('FUTURE_CONTEXT_OBSERVATION')
    payload = dict(row.get('payload') or {})
    if kind in UNITS:
        if row.get('unit') != UNITS[kind]:
            raise ContextError('CONTEXT_UNIT_MISMATCH')
        if kind != 'PARTICIPANT_OI':
            value = number(payload.get('value'))
            if kind != 'GSEC10Y' and value <= 0:
                raise ContextError('CONTEXT_VALUE_OUT_OF_RANGE')
            payload['value'] = str(value)
    if kind == 'EVENT':
        choices = {'RBI': {'REPO', 'STANCE', 'LIQUIDITY', 'PRESS_CONFERENCE'},
                   'BUDGET': {'SPEECH', 'DETAILS'}, 'ELECTION': {'COUNTING', 'RESULTS'}}
        if payload.get('component') not in choices.get(payload.get('category'), set()) or not published:
            raise ContextError('EVENT_COMPONENT_OR_PUBLICATION_MISSING')
        expected = {'RBI': 'rbi.org.in', 'BUDGET': 'indiabudget.gov.in', 'ELECTION': 'eci.gov.in'}[payload['category']]
        host = urlsplit(row['source_url']).hostname
        if host != expected and not host.endswith('.'+expected):
            raise ContextError('EVENT_SOURCE_CATEGORY_MISMATCH')
        start = stamp(payload['window_start'])
        if payload.get('window_end') and stamp(payload['window_end']) < start:
            raise ContextError('EVENT_WINDOW_INVALID')
        if payload.get('review_completed_at') and not start <= stamp(payload['review_completed_at']) <= receipt:
            raise ContextError('EVENT_REVIEW_TIME_INVALID')
    if kind == 'REBALANCE':
        if not published or stamp(payload['effective_at']) < published:
            raise ContextError('REBALANCE_DATES_INVALID')
    if kind == 'PARTICIPANT_OI':
        if payload.get('participant') not in {'Client', 'DII', 'FII', 'Pro'}:
            raise ContextError('PARTICIPANT_INVALID')
        date.fromisoformat(payload['report_date'])
        counts = payload.get('counts') or {}
        if not counts or any(number(v) < 0 or number(v) != number(v).to_integral_value() for v in counts.values()):
            raise ContextError('OI_COUNTS_INVALID')
    result = dict(kind=kind, series=str(row['series']), source_url=row['source_url'],
        source_at=effective.isoformat(), published_at=published.isoformat() if published else None,
        available_at=receipt.isoformat(), received_at=receipt.isoformat(), origin=origin,
        unit=row.get('unit'), payload=payload, source_sha256=row.get('source_sha256'),
        mode='CONTEXT_ONLY', approval_eligible=False)
    result['record_id'] = hashlib.sha256(canonical(result)).hexdigest()
    return result


def known(rows, at):
    at = stamp(at)
    return [r for r in rows if stamp(r['available_at']) <= at and stamp(r['source_at']) <= at
            and (not r.get('published_at') or stamp(r['published_at']) <= at)]


def freshness(row, at):
    if not known([row], at):
        return 'NOT_YET_AVAILABLE'
    if row['kind'] not in AGES:
        return 'DATED_RECORD'
    return 'STALE' if (stamp(at)-stamp(row['source_at'])).total_seconds() > AGES[row['kind']] else 'WITHIN_DISPLAY_AGE'


def latest(rows, kind, at):
    eligible = [r for r in known(rows, at) if r['kind'] == kind]
    return max(eligible, key=lambda r: (stamp(r['source_at']), stamp(r['available_at']))) if eligible else None


def gift_overnight(current, baseline, at):
    if not current or not baseline or len(known([current, baseline], at)) != 2:
        return None
    a, b = current['payload'], baseline['payload']
    if (current['kind'] != 'GIFT' or baseline['kind'] != 'GIFT'
            or not a.get('contract_id') or a.get('contract_id') != b.get('contract_id')
            or not a.get('contract_source_url') or not b.get('contract_source_url')
            or not source_allowed('GIFT', a['contract_source_url']) or not source_allowed('GIFT', b['contract_source_url'])
            or a.get('anchor') != 'PREOPEN' or b.get('anchor') != 'INDIA_CLOSE'
            or a.get('previous_session_date') != b.get('session_date')
            or not a.get('previous_session_date') or stamp(current['source_at']) <= stamp(baseline['source_at'])
            or freshness(current, at) == 'STALE'):
        return None
    return (number(a['value'])/number(b['value'])-1)*100


def vix_percentile(current, rows, at):
    """Trailing 252 distinct prior completed sessions; no short-history annual label."""
    if not current or not known([current], at):
        return None
    history = {}
    for r in sorted(known(rows, at), key=lambda r: stamp(r['available_at'])):
        if r['kind'] == 'VIX_CLOSE' and r['payload'].get('session_date'):
            day = date.fromisoformat(r['payload']['session_date'])
            if day < stamp(current['source_at']).astimezone(ZoneInfo('Asia/Kolkata')).date():
                history[day] = number(r['payload']['value'])
    values = [history[d] for d in sorted(history)[-252:]]
    if len(values) < 252:
        return None
    return Decimal(sum(v <= number(current['payload']['value']) for v in values))*100/Decimal(252)


def yield_change_bp(current, previous, at):
    if not current or not previous or len(known([current, previous], at)) != 2:
        return None
    if (current['kind'] != 'GSEC10Y' or previous['kind'] != 'GSEC10Y'
            or not current['payload'].get('benchmark_id')
            or current['payload']['benchmark_id'] != previous['payload'].get('benchmark_id')
            or stamp(current['source_at']) <= stamp(previous['source_at'])):
        return None  # A benchmark switch is not a yield move.
    return (number(current['payload']['value'])-number(previous['payload']['value']))*100


def event_state(row, at):
    if not known([row], at):
        return 'NOT_YET_AVAILABLE'
    p = row['payload']
    if stamp(at) < stamp(p['window_start']):
        return 'UPCOMING'
    if p.get('review_completed_at') and stamp(p['review_completed_at']) <= stamp(at):
        return 'REVIEW_RECORDED_NOT_AUTHORIZATION'
    return 'UNRESOLVED_REVIEW_REQUIRED'  # Never clear automatically after window_end.


def bundle(rows, created_at, issues=()):
    if len(rows) > MAX_RECORDS:
        raise ContextError('CONTEXT_RECORD_LIMIT')
    result = dict(format=VERSION, created_at=stamp(created_at).isoformat(), mode='CONTEXT_ONLY',
                  approval_eligible=False, records=rows, issues=list(issues))
    canonical(result)
    return result
