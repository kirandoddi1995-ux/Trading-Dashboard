"""Decimal-only obligations. No orders, guessed margins, or inferred closure."""
from decimal import Decimal
import re
from urllib.parse import urlparse

from derivative_contracts import FoundationError, number, stamp


def whole_units(value):
    value = number(value)
    if value != value.to_integral_value():
        raise FoundationError('Integral adjusted underlying units required')
    return int(value)


def obligation(contract, signed_units, *, final_price=None):
    """No final price means potential exercise, even for currently OTM options.

    Units come from reconciled broker positions, NOT units multiplied by lot size.
    Options settle at strike; futures delivery consideration uses final price.
    Premiums, MTM, margins, taxes and fees are separate from consideration.
    """
    units = whole_units(signed_units)
    if not units:
        raise FoundationError('Zero position is not settlement confirmation')
    if contract.kind not in {'CE', 'PE', 'FUT'} or contract.settlement not in {'CASH', 'PHYSICAL'}:
        raise FoundationError('Unsupported settlement contract')
    final = number(final_price, positive=True) if final_price is not None else None
    strike = number(contract.strike)
    if contract.kind != 'FUT' and strike <= 0:
        raise FoundationError('Invalid adjusted strike')
    intrinsic = None if final is None or contract.kind == 'FUT' else max(
        Decimal(0), final-strike if contract.kind == 'CE' else strike-final)
    exercises = contract.kind == 'FUT' or intrinsic is None or intrinsic > 0
    receives = units > 0 if contract.kind in {'CE', 'FUT'} else units < 0
    physical = contract.settlement == 'PHYSICAL' and exercises
    consideration = final if contract.kind == 'FUT' else strike
    amount = None if consideration is None else abs(units)*consideration
    return dict(
        basis='POTENTIAL' if final is None else 'OFFICIAL_PRICE_NOT_YET_RECONCILED',
        receive_units=abs(units) if physical and receives else 0,
        deliver_units=abs(units) if physical and not receives else 0,
        funding_required=amount if physical and receives else Decimal(0),
        sale_consideration=amount if physical and not receives else Decimal(0),
        cash_exercise_amount=(intrinsic*units if contract.settlement == 'CASH' and intrinsic is not None else None),
        margin_required=None, charges=None, settled=False)


def validate_policy(contract, policy, *, now):
    """Owner-reviewed expiry-specific Upstox instructions; never scrape-and-approve."""
    if not isinstance(policy, dict) or policy.get('reviewed') is not True:
        raise FoundationError('Expiry-specific broker policy unreviewed')
    url = urlparse(str(policy.get('source', '')))
    if url.scheme != 'https' or url.hostname not in {'upstox.com', 'www.upstox.com'}:
        raise FoundationError('Official broker notice required')
    if policy.get('contract_version') != contract.version or stamp(policy['expiry_at']) != contract.expiry:
        raise FoundationError('Broker policy contract/expiry mismatch')
    if not re.fullmatch('[a-f0-9]{64}', str(policy.get('source_sha256',''))):
        raise FoundationError('Retained broker notice hash required')
    now = stamp(now)
    if not stamp(policy['known_at']) <= now < stamp(policy['valid_until']):
        raise FoundationError('Broker policy unavailable or stale')
    cutoff, exit_by = stamp(policy['entry_cutoff']), stamp(policy['exit_by'])
    broker = stamp(policy['broker_deadline'])
    if not cutoff <= exit_by <= broker <= contract.expiry:
        raise FoundationError('Invalid reviewed broker deadlines')
    return cutoff, exit_by


def entry_check(contract, context, *, now):
    """Read-only monitor health is additive; it can never grant governance approval."""
    if not isinstance(context, dict) or context.get('status') != 'READY':
        raise FoundationError('Broker/settlement monitor is not ready')
    now = stamp(now)
    if not stamp(context['checked_at']) <= now < stamp(context['valid_until']):
        raise FoundationError('Broker/settlement monitor is stale')
    if context.get('unresolved_critical') is not False:
        raise FoundationError('Unresolved settlement or reconciliation problem')
    if contract.settlement == 'PHYSICAL':
        cutoff, _ = validate_policy(contract, context.get('broker_policy'), now=now)
        if now >= cutoff:
            raise FoundationError('No new physical-settlement exposure past reviewed cutoff')

