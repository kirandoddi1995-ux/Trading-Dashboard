"""Bounded research capture policy and V3 snapshot quality. No I/O or approval API."""
from datetime import datetime, timezone
import json
import math
from zoneinfo import ZoneInfo

from derivative_contracts import digest, stamp
from derivative_quotes import decode_v3

VERSION = 'option-capture-v1'
IST = ZoneInfo('Asia/Kolkata')
SLOTS = {'1015': (10, 15), '1145': (11, 45), '1345': (13, 45), '1500': (15, 0)}
MAX_KEYS = 150
MAX_BYTES = 2 * 1024 * 1024


class CaptureError(ValueError):
    """Safe fixed error codes only; never interpolate provider/credential content."""


def policy(underlyings):
    if (not isinstance(underlyings, list) or not 1 <= len(underlyings) <= 3
            or any(not isinstance(k, str) or not (k == 'NSE_INDEX|Nifty 50' or
                   (k.startswith('NSE_EQ|') and k[7:].isalnum())) for k in underlyings)
            or len(set(underlyings)) != len(underlyings)):
        raise CaptureError('INVALID_RESEARCH_UNIVERSE')
    return dict(version=VERSION, underlyings=sorted(underlyings), expiries=2,
                strikes_each_side=5, max_keys=MAX_KEYS, max_age_seconds=5,
                max_skew_seconds=2, collection_seconds=60, max_archive_bytes=MAX_BYTES,
                slot_lateness_seconds=600, mode='RESEARCH_ONLY')


def timing_evidence(report, day, slot):
    """One-minute research stratum, NOT proof of market timestamp accuracy.

    Ten minutes remains the maximum collection window; only observations within
    60 seconds of the target are eligible for *same-time research comparisons*.
    Existing files without these fields must not be assumed aligned.
    """
    target = datetime.combine(day, datetime.min.time(), IST).replace(
        hour=SLOTS[slot][0], minute=SLOTS[slot][1])
    captured = stamp(report['captured_at'])
    deviation = (captured-target).total_seconds()
    times = [stamp(row['source_at']) for row in report['rows'] if row.get('source_at')]
    max_offset = max([abs(deviation), *[abs((t-target).total_seconds()) for t in times]])
    quality = 'ON_TIME' if 0 <= deviation <= 60 and max_offset <= 60 else 'DELAYED'
    if not 0 <= deviation <= 600:
        quality = 'OUTSIDE_WINDOW'
    if report['status'] == 'SKIPPED_CLOSED':
        quality = 'NOT_APPLICABLE'
    return dict(scheduled_at=target.isoformat(), capture_delay_seconds=deviation,
                timing_quality=quality, comparison_tolerance_seconds=60,
                same_time_comparison_eligible=report['status'] == 'CAPTURED' and quality == 'ON_TIME')


def sample_identity(config, day, slot):
    if slot not in SLOTS:
        raise CaptureError('UNKNOWN_SLOT')
    return digest(dict(policy=config, trading_date=str(day), slot=slot))


def check_slot(now, slot):
    now = stamp(now).astimezone(IST)
    if slot not in SLOTS:
        raise CaptureError('UNKNOWN_SLOT')
    target = now.replace(hour=SLOTS[slot][0], minute=SLOTS[slot][1], second=0, microsecond=0)
    if now.weekday() >= 5 or not 0 <= (now-target).total_seconds() <= 600:
        raise CaptureError('MISSED_SLOT')
    return now.date()


def positive(value):
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError, OverflowError):
        return False


def select_contracts(master, references, config, day):
    """REST spot is only a strike-selection reference, never the captured spot.

    Dates/lot/tick/weekly flags come from the current master. Expiry milliseconds
    are retained as raw metadata; never interpreted as actual settlement cutoff.
    """
    selected, inventory = {}, []
    for underlying in config['underlyings']:
        spot = references.get(underlying)
        if not positive(spot):
            raise CaptureError('SELECTION_REFERENCE_UNAVAILABLE')
        candidates = []
        for row in master:
            if row.get('segment') != 'NSE_FO' or row.get('underlying_key') != underlying:
                continue
            if row.get('instrument_type') not in {'CE', 'PE', 'FUT'}:
                continue
            if row.get('exchange') != 'NSE' or not str(row.get('instrument_key', '')).startswith('NSE_FO|'):
                raise CaptureError('MASTER_VENUE_MISMATCH')
            try:
                expiry = datetime.fromtimestamp(float(row['expiry'])/1000, timezone.utc).astimezone(IST).date()
            except (ValueError, TypeError, KeyError, OverflowError):
                raise CaptureError('MASTER_EXPIRY_INVALID') from None
            if expiry >= day:
                candidates.append((expiry, row))
        option_dates = sorted({d for d, r in candidates if r['instrument_type'] in {'CE', 'PE'}})[:2]
        future_dates = sorted({d for d, r in candidates if r['instrument_type'] == 'FUT'})[:2]
        if not option_dates or not future_dates:
            raise CaptureError('CONTRACT_COVERAGE_UNAVAILABLE')
        selected[underlying] = dict(instrument_key=underlying, role='SPOT', underlying_key=underlying)
        for expiry in option_dates:
            options = [r for d, r in candidates if d == expiry and r['instrument_type'] in {'CE', 'PE'}]
            if any(not positive(r.get('strike_price')) for r in options):
                raise CaptureError('MASTER_STRIKE_INVALID')
            strikes = sorted({float(r['strike_price']) for r in options})
            center = min(range(len(strikes)), key=lambda i: abs(strikes[i]-float(spot)))
            chosen = strikes[max(0, center-5):center+6]
            for strike in chosen:
                for kind in ('CE', 'PE'):
                    matches = [r for r in options if float(r['strike_price']) == strike and r['instrument_type'] == kind]
                    if len(matches) != 1:
                        raise CaptureError('MASTER_PAIR_MISSING_OR_DUPLICATE')
                    row = matches[0]
                    if not positive(row.get('lot_size')) or not positive(row.get('tick_size')):
                        raise CaptureError('MASTER_TERMS_INVALID')
                    if row['instrument_key'] in selected:
                        raise CaptureError('MASTER_DUPLICATE_KEY')
                    selected[row['instrument_key']] = dict(row, role='OPTION', expiry_date=expiry.isoformat())
        for expiry in future_dates:
            matches = [r for d, r in candidates if d == expiry and r['instrument_type'] == 'FUT']
            if len(matches) != 1:
                raise CaptureError('FUTURE_MISSING_OR_DUPLICATE')
            row = matches[0]
            if not positive(row.get('lot_size')) or not positive(row.get('tick_size')):
                raise CaptureError('MASTER_TERMS_INVALID')
            if row['instrument_key'] in selected:
                raise CaptureError('MASTER_DUPLICATE_KEY')
            selected[row['instrument_key']] = dict(row, role='FUTURE', expiry_date=expiry.isoformat())
        inventory.append(dict(underlying=underlying, selection_spot=spot,
                              option_expiries=[d.isoformat() for d in option_dates],
                              futures_expiries=[d.isoformat() for d in future_dates]))
    if len(selected) > MAX_KEYS:
        raise CaptureError('INSTRUMENT_BUDGET_EXCEEDED')
    return selected, inventory


class SnapshotBuffer:
    """Replace a key's full message atomically; never merge missing fields.

    The collector does not reconnect. A new connection starts a new buffer.
    Unknown field-level Greek timestamps stay unknown despite packet freshness.
    """
    def __init__(self, selected, config):
        self.selected, self.config = selected, config
        self.quotes, self.raw, self.phases = {}, {}, {}

    def ingest(self, message, received_at):
        info = message.get('marketInfo') or {}
        states = info.get('segmentStatus') or {}
        self.phases.update(states)
        for key, quote in decode_v3(message, received_at=received_at, generation=1).items():
            if key not in self.selected:
                continue
            self.quotes[key] = quote
            self.raw[key] = dict(currentTs=message.get('currentTs'), feed=message['feeds'][key])

    def snapshot(self, now):
        now = stamp(now)
        rows, times = [], []
        for key, contract in sorted(self.selected.items()):
            q, reasons = self.quotes.get(key, {}), []
            required_phase = 'NSE_FO' if contract['role'] != 'SPOT' else ('NSE_INDEX' if key.startswith('NSE_INDEX|') else 'NSE_EQ')
            # Index stream may only publish the cash-market phase.
            phase = self.phases.get(required_phase, self.phases.get('NSE_EQ') if required_phase == 'NSE_INDEX' else None)
            if phase != 'NORMAL_OPEN':
                reasons.append('SESSION_UNVERIFIED')
            try:
                source, received = stamp(q.get('source_at')), stamp(q.get('received_at'))
                if not source <= received <= now or not 0 <= (now-source).total_seconds() <= self.config['max_age_seconds']:
                    reasons.append('STALE_OR_FUTURE_PACKET')
                else:
                    times.append(source)
            except ValueError:
                source, received = None, None
                reasons.append('MISSING_PACKET')
            if contract['role'] == 'SPOT' and key.startswith('NSE_INDEX|'):
                if not positive(q.get('reference')):
                    reasons.append('REFERENCE_MISSING')
                try:
                    ltt = datetime.fromtimestamp(float(q['last_trade_at'])/1000, timezone.utc)
                    if not 0 <= (now-ltt).total_seconds() <= self.config['max_age_seconds']:
                        reasons.append('STALE_INDEX_VALUE')
                    times.append(ltt)
                except (ValueError, TypeError, KeyError, OverflowError):
                    reasons.append('INDEX_TIME_MISSING')
            elif not all(positive(q.get(f)) for f in ('bid', 'ask', 'bid_size', 'ask_size')):
                reasons.append('BOOK_INCOMPLETE')
            elif float(q['bid']) > float(q['ask']):
                reasons.append('CROSSED_BOOK')
            if contract['role'] == 'OPTION':
                for f in ('iv', 'oi'):
                    value = q.get(f)
                    try:
                        ok = value is not None and math.isfinite(float(value)) and float(value) >= 0
                    except (ValueError, TypeError):
                        ok = False
                    if not ok or (f == 'iv' and not positive(value)):
                        reasons.append('MISSING_' + f.upper())
                for f in ('delta', 'gamma', 'theta', 'vega'):
                    try:
                        if not math.isfinite(float((q.get('greeks') or {})[f])):
                            raise ValueError
                    except (ValueError, TypeError, KeyError):
                        reasons.append('MISSING_' + f.upper())
            rows.append(dict(instrument_key=key, underlying=contract['underlying_key'], role=contract['role'],
                source_at=source.isoformat() if source else None,
                received_at=received.isoformat() if received else None,
                bid=q.get('bid'), ask=q.get('ask'), bid_size=q.get('bid_size'), ask_size=q.get('ask_size'),
                packet_age_seconds=(now-source).total_seconds() if source else None,
                spread=(float(q['ask'])-float(q['bid'])) if positive(q.get('bid')) and positive(q.get('ask')) else None,
                reference=q.get('reference'), last_trade_at=q.get('last_trade_at'),
                iv_raw=q.get('iv'), oi=q.get('oi'), volume=q.get('volume'),
                greeks_raw=q.get('greeks'), exchange_at=None, greek_calculated_at=None,
                contract=contract, provider=self.raw.get(key), reasons=reasons))
        aligned = bool(times) and (max(times)-min(times)).total_seconds() <= self.config['max_skew_seconds']
        if not aligned:
            for row in rows:
                row['reasons'].append('CROSS_INSTRUMENT_SKEW')
        return dict(status='CAPTURED' if aligned and all(not r['reasons'] for r in rows) else 'PARTIAL',
                    captured_at=now.isoformat(), rows=rows,
                    segment_status=dict(self.phases), mode='RESEARCH_ONLY', approval_eligible=False,
                    convention_status='UNVERIFIED', rate=None, dividend_yield=None)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError):
        raise CaptureError('INVALID_CAPTURE_PAYLOAD') from None
