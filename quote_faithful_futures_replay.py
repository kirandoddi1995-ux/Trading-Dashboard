"""Pure two-leg PAPER preflight/accounting, never executable fill/PnL evidence.

Both legs must be supportable before either is committed to this atomic paper
result. This is not a simulation of recovery after an actual filled entry.
All metadata, rights and timestamps are unauthenticated caller claims.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Context, Decimal, InvalidOperation, localcontext
import hashlib
import json
import re

MAX_QUOTES = 4096
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class Contract:
    contract_id: str
    metadata_sha256: str
    known_at: str
    effective_from: str
    effective_until: str
    expiry: str
    tick_size: str
    lot_size: int
    currency: str
    point_value: str


@dataclass(frozen=True)
class DatedCosts:
    evidence_sha256: str
    known_at: str
    effective_from: str
    effective_until: str
    buy_rate: str
    sell_rate: str
    fee_per_order: str
    adverse_ticks_per_side: int
    currency: str


@dataclass(frozen=True)
class ReplayPlan:
    study_sha256: str
    decision_input_sha256: str
    frozen_at: str
    session_open: str
    session_close: str
    entry_decision_at: str
    exit_decision_at: str
    direction: int
    lots: int
    latency_ms: int
    max_staleness_ms: int
    input_kind: str


@dataclass(frozen=True)
class Quote:
    quote_id: str
    version: int
    contract_id: str
    quoted_at: str
    available_at: str
    bid: str | None
    ask: str | None
    bid_units: int
    ask_units: int
    payload_sha256: str


@dataclass(frozen=True)
class PaperFill:
    side: str
    quote_id: str
    version: int
    quote_sha256: str
    filled_at: str
    touch_price: str
    adverse_slippage: str
    price: str
    units: int
    fee: str


@dataclass(frozen=True)
class ReplayResult:
    status: str
    reason: str
    fills: tuple[PaperFill, ...]
    gross_reference_amount: str | None
    total_fees: str | None
    net_reference_amount: str | None
    paper_flat: bool
    plan_sha256: str
    manifest: bytes
    manifest_sha256: str
    training_eligible: bool = False
    promotable: bool = False
    approval_authority: bool = False
    fill_evidence: bool = False
    executable_pnl_verified: bool = False


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _id(value: str) -> None:
    if type(value) is not str or re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', value) is None:
        raise ValueError('INVALID_IDENTITY')


def _pin(value: str) -> None:
    if type(value) is not str or re.fullmatch('[a-f0-9]{64}', value) is None:
        raise ValueError('INVALID_SHA256')


def _at(value: str) -> datetime:
    if type(value) is not str or not 1 <= len(value) <= 40:
        raise ValueError('AWARE_TIME_REQUIRED')
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('AWARE_TIME_REQUIRED') from None
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError('AWARE_TIME_REQUIRED')
    return moment.astimezone(timezone.utc)


def _day(value: str) -> date:
    if type(value) is not str or re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) is None:
        raise ValueError('EXACT_DAY_REQUIRED')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError('EXACT_DAY_REQUIRED') from None


def _amount(value: str, *, positive: bool = False) -> Decimal:
    # Decimal strings avoid binary-float prices, bool coercion and ambient rounding.
    if type(value) is not str or not 1 <= len(value) <= 32:
        raise ValueError('BOUNDED_DECIMAL_STRING_REQUIRED')
    if re.fullmatch(r'(?:0|[1-9]\d{0,12})(?:\.\d{1,8})?', value) is None:
        raise ValueError('FINITE_NONNEGATIVE_DECIMAL_REQUIRED')
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError('FINITE_NONNEGATIVE_DECIMAL_REQUIRED') from None
    if result > Decimal('1e12') or (positive and result <= 0):
        raise ValueError('AMOUNT_BOUND')
    return result


def _integer(value: int, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError('EXACT_INTEGER_BOUND')


def replay(plan: ReplayPlan, contract: Contract, costs: DatedCosts,
           quotes: tuple[Quote, ...]) -> ReplayResult:
    """One contract, one directional round trip, supplied same-day session.

    Select first quote availability at/after each decision+latency, requiring
    quote event time at/after that threshold too. No skip-to-better-quote fallback:
    a stale/missing/shallow first eligible quote withholds the entire paper pair.
    """
    with localcontext(Context(prec=64)):
        return _replay(plan, contract, costs, quotes)


def _replay(plan: ReplayPlan, contract: Contract, costs: DatedCosts,
            quotes: tuple[Quote, ...]) -> ReplayResult:
    if type(quotes) is not tuple or len(quotes) > MAX_QUOTES:
        raise ValueError('QUOTE_BOUND')
    _id(contract.contract_id)
    for pin in (plan.study_sha256, plan.decision_input_sha256,
                contract.metadata_sha256, costs.evidence_sha256):
        _pin(pin)
    if plan.input_kind not in ('SYNTHETIC', 'CALLER_UNAUTHENTICATED'):
        raise ValueError('UNAUTHENTICATED_INPUT_KIND_REQUIRED')
    _integer(plan.direction, -1, 1)
    if plan.direction == 0:
        raise ValueError('DIRECTION_REQUIRED')
    _integer(plan.lots, 1, 10000)
    _integer(contract.lot_size, 1, 100000)
    _integer(plan.latency_ms, 0, 60000)
    _integer(plan.max_staleness_ms, 0, 60000)
    _integer(costs.adverse_ticks_per_side, 0, 100)
    tick = _amount(contract.tick_size, positive=True)
    point_value = _amount(contract.point_value, positive=True)
    if (type(contract.currency) is not str or re.fullmatch('[A-Z]{3}', contract.currency) is None
            or costs.currency != contract.currency):
        raise ValueError('EXPLICIT_MATCHING_CURRENCY_REQUIRED')
    buy_rate, sell_rate = _amount(costs.buy_rate), _amount(costs.sell_rate)
    if max(buy_rate, sell_rate) > 1:
        raise ValueError('FEE_RATE_BOUND')
    fixed_fee = _amount(costs.fee_per_order)
    opening, closing, entry_at, exit_at, frozen = map(_at, (plan.session_open,
        plan.session_close, plan.entry_decision_at, plan.exit_decision_at, plan.frozen_at))
    day = opening.astimezone(IST).date()
    if (closing.astimezone(IST).date() != day or not opening <= entry_at < exit_at < closing
            or frozen > entry_at):
        raise ValueError('INTRADAY_PLAN_TIME_ORDER_REQUIRED')
    if _at(contract.known_at) > entry_at or _at(costs.known_at) > entry_at:
        raise ValueError('METADATA_OR_COSTS_NOT_KNOWN_AT_DECISION')
    if not _day(contract.effective_from) <= day <= _day(contract.effective_until) <= _day(contract.expiry):
        raise ValueError('CONTRACT_EFFECTIVE_DATES_REQUIRED')
    if day >= _day(contract.expiry):
        raise ValueError('EXPIRY_DAY_OR_EXPIRED_ENTRY_FORBIDDEN')
    if not _day(costs.effective_from) <= day <= _day(costs.effective_until):
        raise ValueError('DATED_COSTS_REQUIRED')

    by_id: dict[str, list[Quote]] = {}
    arrivals: set[datetime] = set()
    normalized_quotes: list[dict[str, object]] = []
    for q in quotes:
        _id(q.quote_id)
        _pin(q.payload_sha256)
        _integer(q.version, 1, MAX_QUOTES)
        _integer(q.bid_units, 0, 1_000_000_000)
        _integer(q.ask_units, 0, 1_000_000_000)
        if q.contract_id != contract.contract_id:
            raise ValueError('QUOTE_CONTRACT_MISMATCH')
        event, available = _at(q.quoted_at), _at(q.available_at)
        if available < event:
            raise ValueError('QUOTE_AVAILABLE_BEFORE_EVENT')
        if any(t.astimezone(IST).date() != day for t in (event, available)):
            raise ValueError('CROSS_SESSION_QUOTE_FORBIDDEN')
        if available in arrivals:
            raise ValueError('AMBIGUOUS_QUOTE_ARRIVAL')
        arrivals.add(available)
        bid = None if q.bid is None else _amount(q.bid, positive=True)
        ask = None if q.ask is None else _amount(q.ask, positive=True)
        if any(value is not None and value % tick != 0 for value in (bid, ask)):
            raise ValueError('QUOTE_OFF_TICK')
        if bid is not None and ask is not None and bid > ask:
            raise ValueError('CROSSED_QUOTE')
        by_id.setdefault(q.quote_id, []).append(q)
        normalized_quotes.append({**asdict(q), 'quoted_at': event.isoformat(), 'available_at': available.isoformat()})
    for group in by_id.values():
        group.sort(key=lambda q: q.version)
        for prior, later in zip(group, group[1:]):
            if (later.version <= prior.version or _at(later.available_at) <= _at(prior.available_at)
                    or _at(later.quoted_at) != _at(prior.quoted_at)):
                raise ValueError('AMBIGUOUS_OR_NONMONOTONIC_REVISION')
    stream = sorted(quotes, key=lambda q: _at(q.available_at))
    units = plan.lots*contract.lot_size
    slippage = tick*costs.adverse_ticks_per_side

    def leg(at: datetime, buy: bool) -> tuple[PaperFill | None, str]:
        ready = at+timedelta(milliseconds=plan.latency_ms)
        eligible = [q for q in stream if ready <= _at(q.quoted_at)
                    and ready <= _at(q.available_at) <= closing]
        if not eligible:
            return None, 'NO_POST_LATENCY_QUOTE'
        q = eligible[0]
        event, available = _at(q.quoted_at), _at(q.available_at)
        if available-event > timedelta(milliseconds=plan.max_staleness_ms):
            return None, 'STALE_QUOTE'
        if q.bid is None or q.ask is None:
            return None, 'MISSING_TWO_SIDED_QUOTE'
        if (q.ask_units if buy else q.bid_units) < units:
            return None, 'INSUFFICIENT_DISPLAYED_DEPTH'
        touch = _amount(q.ask if buy else q.bid, positive=True)
        price = touch+slippage if buy else touch-slippage
        if price <= 0:
            return None, 'NONPOSITIVE_ADVERSE_PRICE'
        fee = fixed_fee+price*units*point_value*(buy_rate if buy else sell_rate)
        normalized = {**asdict(q), 'quoted_at': event.isoformat(), 'available_at': available.isoformat()}
        return PaperFill('BUY' if buy else 'SELL', q.quote_id, q.version, _sha(normalized),
                         available.isoformat(), str(touch), str(slippage), str(price), units, str(fee)), 'SUPPORTED'

    entry, reason = leg(entry_at, plan.direction == 1)
    exit_fill: PaperFill | None = None
    if entry is not None:
        if _at(entry.filled_at) >= exit_at:
            reason = 'ENTRY_NOT_FILLED_BEFORE_EXIT_DECISION'
        else:
            exit_fill, reason = leg(exit_at, plan.direction == -1)
    fills: tuple[PaperFill, ...] = ()
    gross: str | None = None
    fees: str | None = None
    net: str | None = None
    if entry is not None and exit_fill is not None:
        fills = (entry, exit_fill)
        gross_amount = (Decimal(exit_fill.price)-Decimal(entry.price))*units*point_value*plan.direction
        fee_amount = Decimal(entry.fee)+Decimal(exit_fill.fee)
        gross, fees, net = str(gross_amount), str(fee_amount), str(gross_amount-fee_amount)
    status = 'PAPER_ROUND_TRIP_UNADMITTED' if fills else 'WITHHELD_NO_PAPER_LEGS_COMMITTED'
    normalized_plan = {**asdict(plan), **{name: _at(value).isoformat() for name, value in (
        ('frozen_at', plan.frozen_at), ('session_open', plan.session_open), ('session_close', plan.session_close),
        ('entry_decision_at', plan.entry_decision_at), ('exit_decision_at', plan.exit_decision_at))}}
    plan_hash = _sha(dict(plan=normalized_plan, contract=asdict(contract), costs=asdict(costs)))
    manifest = _canonical(dict(format='quote-faithful-futures-paper-v1', plan=normalized_plan,
        contract=asdict(contract), costs=asdict(costs), plan_sha256=plan_hash,
        quotes=sorted(normalized_quotes, key=lambda q: str(q['available_at'])),
        status=status, reason=reason, fills=[asdict(fill) for fill in fills],
        gross_reference_amount=gross, total_fees=fees, net_reference_amount=net,
        paper_flat=True, accounting='ATOMIC_TWO_LEG_PREFLIGHT_NOT_LIVE_RECOVERY',
        training_eligible=False, promotable=False, approval_authority=False,
        fill_evidence=False, executable_pnl_verified=False,
        authentication='CALLER_INPUTS_NOT_AUTHENTICATED', contract_calendar_verified=False,
        decision_prefix_completeness_verified=False, licence_verified=False))
    if len(manifest) > MAX_MANIFEST_BYTES:
        raise ValueError('MANIFEST_SIZE_BOUND')
    return ReplayResult(status, reason, fills, gross, fees, net, True, plan_hash,
                        manifest, hashlib.sha256(manifest).hexdigest())
