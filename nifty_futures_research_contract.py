"""Fixed research roll/execution contract. Never a broker order or fill claim."""
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from zoneinfo import ZoneInfo

from intraday_fo_costs import CostEvidenceError, amount

POLICY = {'version': 'nifty-futures-research-v1', 'roll_sessions_before_expiry': 2,
          'expiry_day_entries': False, 'positions_carried_between_sessions': False,
          'entry': 'NEXT_COMPLETED_SIGNAL_BAR_OPEN_REFERENCE',
          'exit': 'NEXT_OPEN_AFTER_COMPLETED_REVERSAL_OR_REVIEWED_DEADLINE',
          'same_bar_reentry': False, 'intrabar_stop_fills': 'UNSUPPORTED_WITH_OHLC',
          'spread_slippage_ticks_per_side': [0, 1, 2, 4],
          'zero_tick_case': 'REFERENCE_ONLY_NOT_EXECUTABLE',
          'approval_authority': False, 'fill_evidence': False}


def select_contract(day, contracts, trading_dates, *, decision_at):
    """Roll at session open two reviewed trading sessions before expiry.

    Use ONLY contracts documented as listed by decision_at. The caller must
    supply an independently reviewed trading calendar including each expiry;
    no weekday/holiday guesses, volume look-ahead, continuous-price adjustment,
    mid-session roll, or nearest-available fallback after selection.
    """
    if (type(day) is not date or not isinstance(decision_at, datetime)
            or decision_at.tzinfo is None or
            decision_at.astimezone(ZoneInfo('Asia/Kolkata')).date() != day):
        raise CostEvidenceError('DECISION_TIME_UNVERIFIED')
    if not isinstance(contracts, list) or any(not isinstance(c, dict) for c in contracts):
        raise CostEvidenceError('CONTRACT_INVENTORY_REQUIRED')
    try:
        if not isinstance(trading_dates, list):
            raise ValueError()
        dates = [date.fromisoformat(v) for v in trading_dates]
    except (TypeError, ValueError):
        raise CostEvidenceError('REVIEWED_SESSION_CALENDAR_REQUIRED') from None
    if dates != sorted(set(dates)) or day not in dates:
        raise CostEvidenceError('REVIEWED_SESSION_CALENDAR_REQUIRED')
    candidates, seen = [], set()
    for contract in contracts:
        try:
            listed = datetime.fromisoformat(contract['listed_at'])
            expiry = date.fromisoformat(contract['expiry'])
            key = contract['contract_key']
            if listed.tzinfo is None or not isinstance(key, str) or not key:
                raise ValueError()
            if key in seen:
                raise ValueError()
            seen.add(key)
            if listed > decision_at or expiry < day:
                continue
            if expiry not in dates or dates.index(expiry) < 2:
                raise ValueError()
            cutoff = dates[dates.index(expiry) - POLICY['roll_sessions_before_expiry']]
            if day < cutoff:
                candidates.append((expiry, key, contract))
        except (KeyError, TypeError, ValueError):
            raise CostEvidenceError('CONTRACT_LISTING_OR_EXPIRY_CALENDAR_UNVERIFIED') from None
    if not candidates:
        raise CostEvidenceError('SELECTED_CONTRACT_UNAVAILABLE_NO_FALLBACK')
    candidates.sort(key=lambda item: (item[0], item[1]))
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        raise CostEvidenceError('AMBIGUOUS_CONTRACT_EXPIRY')
    return dict(candidates[0][2])


def adverse_reference_price(price, tick_size, *, side, ticks):
    """A deterministic adverse price stress, not estimated spread or fill evidence."""
    if side not in ('BUY', 'SELL') or type(ticks) is not int or ticks not in POLICY['spread_slippage_ticks_per_side']:
        raise CostEvidenceError('UNREGISTERED_EXECUTION_SCENARIO')
    price, tick = amount(price), amount(tick_size)
    if not price or not tick:
        raise CostEvidenceError('POSITIVE_PRICE_AND_TICK_REQUIRED')
    stressed = price + tick * ticks * (1 if side == 'BUY' else -1)
    result = (stressed / tick).to_integral_value(
        rounding=ROUND_CEILING if side == 'BUY' else ROUND_FLOOR) * tick
    if result <= Decimal('0'):
        raise CostEvidenceError('NONPOSITIVE_STRESSED_PRICE')
    return result
