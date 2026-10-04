"""Decimal intraday research costs and broker margin parsing; no approval authority.

Tariffs are supplied as dated, reviewed records, never inferred from today's
rates for a historical trade. Slippage belongs in execution prices, not a
fabricated fill probability. Margin is collateral, NOT a maximum loss.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class CostEvidenceError(ValueError):
    pass


def amount(value):
    if value is None or isinstance(value, (bool, float)):
        raise CostEvidenceError('Exact decimal value required')
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise CostEvidenceError('Invalid decimal value') from None
    if not result.is_finite() or result < 0:
        raise CostEvidenceError('Nonnegative finite value required')
    return result


def margin_response(body):
    """Required funds before basket benefits and final collateral are distinct.

    Parsing alone does NOT establish freshness, request identity or permission
    to trade. Callers must retain those with the original basket response.
    JSON numeric fields are converted via their decimal string representation.
    """
    if not isinstance(body, dict) or body.get('status') != 'success':
        raise CostEvidenceError('BROKER_MARGIN_UNAVAILABLE')
    data = body.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('margins'), list) or not data['margins']:
        raise CostEvidenceError('BROKER_MARGIN_INCOMPLETE')
    def number(value):
        if value is None or isinstance(value, bool):
            raise CostEvidenceError('BROKER_MARGIN_INCOMPLETE')
        return amount(str(value))
    return {'required_margin': number(data.get('required_margin')),
            'final_margin': number(data.get('final_margin')),
            'legs': data['margins'], 'approval_authority': False}


def fresh_margin(body, *, requested_at, now, request_basket, response_basket, max_age_seconds=30):
    """The retained request must match exactly; no net-benefit funding shortcut."""
    if (requested_at.tzinfo is None or now.tzinfo is None or not request_basket
            or request_basket != response_basket or max_age_seconds <= 0):
        raise CostEvidenceError('MARGIN_REQUEST_UNVERIFIED')
    age = (now - requested_at).total_seconds()
    if not 0 <= age <= max_age_seconds:
        raise CostEvidenceError('MARGIN_STALE')
    return margin_response(body)


def round_trip(*, entry, exit, quantity, lot_size, kind, policy, entered_at, exited_at,
               exit_deadline, deadline_source, entry_orders=1, exit_orders=1, entry_side='BUY'):
    """Long-premium/futures scenario, same-day NSE; executed-order counts explicit.

    Supply prices including the intended spread/slippage scenario. Missing
    execution evidence remains missing. No policy defaults or historical rates
    are substituted. Components round per side to paise (policy convention).
    """
    if not isinstance(policy, dict) or kind not in ('OPTION', 'FUTURE') or policy.get('exchange') != 'NSE':
        raise CostEvidenceError('UNSUPPORTED_SEGMENT')
    if entry_side not in ('BUY', 'SELL') or (kind == 'OPTION' and entry_side != 'BUY'):
        raise CostEvidenceError('Unsupported entry side; short option obligations not modelled')
    for value in (quantity, lot_size, entry_orders, exit_orders):
        if type(value) is not int or value <= 0:
            raise CostEvidenceError('Positive integer quantities and order counts required')
    if quantity % lot_size:
        raise CostEvidenceError('Quantity must be whole lots')
    stamps = (entered_at, exited_at, exit_deadline)
    if any(not isinstance(t, datetime) or t.tzinfo is None for t in stamps):
        raise CostEvidenceError('Aware timestamps required')
    from zoneinfo import ZoneInfo
    local = [t.astimezone(ZoneInfo('Asia/Kolkata')) for t in stamps]
    day = local[0].date()
    if not (day == local[1].date() == local[2].date() and entered_at < exited_at <= exit_deadline):
        raise CostEvidenceError('INTRADAY_EXIT_DEADLINE_UNVERIFIED')
    if not deadline_source or not policy.get('reviewed') is True:
        raise CostEvidenceError('POLICY_UNREVIEWED')
    try:
        start = datetime.fromisoformat(policy['effective_from']).date()
        end = datetime.fromisoformat(policy['effective_to']).date()
        reviewed = datetime.fromisoformat(policy['reviewed_at'])
        if reviewed.tzinfo is None or reviewed.astimezone(timezone.utc) > entered_at:
            raise CostEvidenceError('Policy review unavailable at decision time')
        rates = policy['rates'][kind]
        sources = policy['sources']
    except (KeyError, TypeError, ValueError):
        raise CostEvidenceError('DATED_COST_POLICY_MISSING') from None
    if not start <= day <= end or not isinstance(sources, dict):
        raise CostEvidenceError('DATED_COST_POLICY_MISSING')
    names = ('brokerage_cap', 'brokerage_rate', 'stt_sell', 'stamp_buy', 'exchange', 'ipft', 'sebi', 'gst')
    if any(not str(sources.get(name, '')).startswith('https://') for name in names):
        raise CostEvidenceError('OFFICIAL_COST_SOURCES_MISSING')
    if policy.get('rounding') != 'PER_SIDE_PAISE_HALF_UP':
        raise CostEvidenceError('ROUNDING_CONVENTION_UNVERIFIED')
    values = {name: amount(rates.get(name)) for name in names}
    if policy.get('gst_components') != ['brokerage', 'exchange', 'ipft', 'sebi']:
        raise CostEvidenceError('GST_BASIS_UNVERIFIED')
    prices = (amount(entry), amount(exit))
    if not all(prices):
        raise CostEvidenceError('Positive prices required')
    def money(value):
        return value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    sides = []
    side_order = ('BUY', 'SELL') if entry_side == 'BUY' else ('SELL', 'BUY')
    for side, price, orders in zip(side_order, prices, (entry_orders, exit_orders)):
        turnover = price * quantity
        # Aggregate assumes equal turnover per distinct executed order. Unequal
        # capped futures orders must be supplied separately, not guessed here.
        if kind == 'FUTURE' and orders != 1:
            raise CostEvidenceError('Per-order futures turnover required')
        brokerage = (values['brokerage_cap'] * orders if kind == 'OPTION' else
                     min(values['brokerage_cap'], turnover * values['brokerage_rate']))
        fees = {'brokerage': money(brokerage),
                'stt': money(turnover * values['stt_sell']) if side == 'SELL' else Decimal('0'),
                'stamp': money(turnover * values['stamp_buy']) if side == 'BUY' else Decimal('0')}
        fees.update({key: money(turnover * values[key]) for key in ('exchange', 'ipft', 'sebi')})
        fees['gst'] = money(sum(fees[key] for key in policy['gst_components']) * values['gst'])
        sides.append(fees)
    total = sum(sum(side.values()) for side in sides)
    gross = (prices[1] - prices[0]) * quantity * (1 if entry_side == 'BUY' else -1)
    return {'gross_pnl': gross, 'charges': total, 'net_pnl': gross - total,
            'entry_charges': sides[0], 'exit_charges': sides[1],
            'premium_at_risk_plus_charges': prices[0] * quantity + total if kind == 'OPTION' else None,
            'basis': 'RESEARCH_PRICE_SCENARIO_NOT_FILL_EVIDENCE', 'approval_authority': False}
