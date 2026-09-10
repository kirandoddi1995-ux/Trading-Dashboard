"""Price touches only. No fills, returns, costs, production labels or approvals."""
from __future__ import annotations

import datetime as dt

from equity_research_observations import IST, POLICY, PURPOSE, aware, digest, number

MINUTE = dt.timedelta(minutes=1)


def sessions_for(observation, calendar):
    if not calendar.get('source') or not calendar.get('reviewed_at'):
        raise ValueError('Reviewed session calendar with provenance required')
    aware(calendar['reviewed_at'])
    rows = [(aware(s['open']), aware(s['close'])) for s in calendar['sessions']]
    if rows != sorted(rows) or len(set(rows)) != len(rows):
        raise ValueError('Calendar must be ordered and unique')
    for i, (opening, closing) in enumerate(rows):
        if opening >= closing or (i and rows[i - 1][1] >= opening):
            raise ValueError('Overlapping or invalid session')
        if opening.second or opening.microsecond or closing.second or closing.microsecond:
            raise ValueError('Session bounds must align to minutes')
        if opening.astimezone(IST).date() != closing.astimezone(IST).date():
            raise ValueError('Equity session must be within one exchange date')
    decision = aware(observation['decision_at'])
    if not rows or not rows[0][0] <= decision < rows[0][1]:
        raise ValueError('Calendar must start with the actual decision session')
    if len(rows) != observation['horizon_sessions']:
        raise ValueError('Exact recorded horizon sessions required; no weekday inference')
    return rows


def evaluate_touches(observation, candles, calendar, *, now, source, fetched_at, data_through=None):
    """Candle timestamps denote START; partial decision-minute data are excluded.

    None means unknown, never false-by-default. A touch is factual only for the
    raw provider series (corporate actions are not adjusted or execution-modeled).
    """
    now, fetched_at = aware(now), aware(fetched_at)
    coverage_end = aware(data_through) if data_through is not None else fetched_at
    decision = aware(observation['decision_at'])
    if now < decision or fetched_at > now or coverage_end > fetched_at or not source:
        raise ValueError('Invalid outcome provenance or chronology')
    if observation['policy'] != POLICY or observation['purpose'] != PURPOSE:
        raise ValueError('Not a research observation')
    sessions = sessions_for(observation, calendar)
    start = decision.replace(second=0, microsecond=0)
    if start < decision:
        start += MINUTE
    expected = set()
    for opening, closing in sessions:
        cursor = max(opening, start)
        while cursor + MINUTE <= min(closing, now, coverage_end):
            expected.add(cursor)
            cursor += MINUTE
    rows = {}
    conflicting = set()
    invalid = 0
    for candle in candles:
        try:
            stamp = aware(candle[0])
            if stamp not in expected:
                continue
            if stamp in conflicting:
                continue
            opening, high, low, close = [number(v) for v in candle[1:5]]
            if len(candle) < 5 or not 0 < low <= min(opening, close) <= max(opening, close) <= high:
                raise ValueError('Invalid OHLC')
            if stamp in rows and rows[stamp] != (high, low):
                del rows[stamp]
                conflicting.add(stamp)
                raise ValueError('Conflicting duplicate candle')
            rows[stamp] = (high, low)
        except (ValueError, TypeError, IndexError):
            invalid += 1
    missing = sorted(expected - rows.keys())
    targets = sorted(t for t, (high, low) in rows.items() if high >= observation['target'])
    stops = sorted(t for t, (high, low) in rows.items() if low <= observation['stop'])
    complete = bool(expected) and not missing and not invalid
    mature = now >= sessions[-1][1] and coverage_end >= sessions[-1][1]
    def touched(hits):
        return True if hits else (False if mature and complete else None)
    target, stop = touched(targets), touched(stops)
    first = None
    hits = sorted(set(targets + stops))
    if hits and not invalid and not any(t <= hits[0] for t in missing):
        first = ('AMBIGUOUS_SAME_BAR' if targets and stops and targets[0] == stops[0]
                 else 'TARGET' if hits[0] in targets else 'STOP')
    status = ('BOTH_TOUCHED' if targets and stops else 'TARGET_TOUCHED' if targets
              else 'STOP_TOUCHED' if stops else 'NEITHER_TOUCHED' if mature and complete
              else 'INSUFFICIENT_DATA' if missing or invalid else 'PENDING')
    return {
        'decision_id': observation['decision_id'], 'policy': POLICY, 'purpose': PURPOSE,
        'approved': False, 'status': status, 'target_touched': target, 'stop_touched': stop,
        'first_observed_touch': first,
        'target_bar_start': targets[0].isoformat() if targets else None,
        'stop_bar_start': stops[0].isoformat() if stops else None,
        'assessed_at': now.isoformat(), 'fetched_at': fetched_at.isoformat(),
        'requested_data_through': coverage_end.isoformat(),
        'horizon_complete': mature, 'coverage_complete': complete,
        'expected_minutes': len(expected), 'present_minutes': len(rows),
        'missing_minutes': [t.isoformat() for t in missing], 'invalid_candles': invalid,
        'tracking_start': start.isoformat(), 'horizon_close': sessions[-1][1].isoformat(),
        'excluded_initial_seconds': (start - decision).total_seconds(),
        'interpretation': 'RAW_PROVIDER_PRICE_TOUCH_NOT_FILL_OR_PROFIT',
        'corporate_action_status': 'NOT_VERIFIED_NO_PRICE_ADJUSTMENT',
        'source': source, 'source_sha256': digest(candles),
        'source_candles': candles, 'session_calendar': calendar,
    }
