"""Inactive bid/ask scenarios with explicit contracts. Never produces fills."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, Callable, Mapping, Sequence, cast

from overnight_research_dataset import DataScope, ResearchError, instant, scoped_time, fingerprint, sha


def decimal(value: str) -> Decimal:
    if type(value) is not str:
        raise ResearchError('EXACT_DECIMAL_STRING_REQUIRED')
    try:
        result = Decimal(value)
    except ArithmeticError:
        raise ResearchError('DECIMAL_INVALID') from None
    if not result.is_finite() or result < 0:
        raise ResearchError('NONNEGATIVE_FINITE_DECIMAL_REQUIRED')
    return result


@dataclass(frozen=True)
class InstrumentContract:
    contract_key: str
    kind: str
    lot_size: int
    tick_size: str
    listed_at: str
    expires_at: str
    known_at: str
    session_open: str
    exit_deadline: str
    deadline_source: str
    reference_sha256: str
    strike: str | None = None
    option_right: str | None = None
    data_scope: DataScope = 'DEVELOPMENT_ONLY'

    def validate(self, decision_at: str) -> None:
        from zoneinfo import ZoneInfo
        decision = scoped_time(decision_at, self.data_scope)
        # Listing and metadata may predate a prospective session; they are not historical price observations.
        listed, known = map(instant, (self.listed_at, self.known_at))
        expiry, opening, deadline = (scoped_time(v, self.data_scope) for v in (
            self.expires_at, self.session_open, self.exit_deadline))
        sha(self.reference_sha256)
        if (not self.contract_key or self.contract_key.startswith('NSE_INDEX|')
                or self.kind not in ('FUTURE', 'OPTION') or type(self.lot_size) is not int
                or self.lot_size <= 0 or decimal(self.tick_size) <= 0
                or not listed <= known <= decision or not opening <= decision < deadline < expiry
                or not self.deadline_source.startswith('https://')):
            raise ResearchError('CONTRACT_UNVERIFIED')
        if self.kind == 'OPTION':
            if self.strike is None or decimal(self.strike) <= 0 or self.option_right not in ('CE', 'PE'):
                raise ResearchError('OPTION_IDENTITY_REQUIRED')
        elif self.strike is not None or self.option_right is not None:
            raise ResearchError('FUTURE_OPTION_FIELDS_CONFLICT')
        if decision.astimezone(ZoneInfo('Asia/Kolkata')).date() == expiry.astimezone(ZoneInfo('Asia/Kolkata')).date():
            raise ResearchError('EXPIRY_DAY_ENTRY_UNSUPPORTED')


@dataclass(frozen=True)
class Quote:
    contract_key: str
    exchange_at: str
    received_at: str
    bid: str
    ask: str
    bid_quantity: int
    ask_quantity: int
    evidence_sha256: str

    def validate(self, contract: InstrumentContract, at: str, max_age: int) -> None:
        exchange, receipt, cutoff = (scoped_time(v, contract.data_scope) for v in (self.exchange_at, self.received_at, at))
        sha(self.evidence_sha256)
        bid, ask = decimal(self.bid), decimal(self.ask)
        tick = decimal(contract.tick_size)
        if (self.contract_key != contract.contract_key or not exchange <= receipt <= cutoff
                or cutoff - exchange > timedelta(seconds=max_age) or bid <= 0 or ask < bid
                or bid % tick or ask % tick or any(type(q) is not int or q < 0
                    for q in (self.bid_quantity, self.ask_quantity))):
            raise ResearchError('EXECUTABLE_QUOTE_UNVERIFIED')


def round_trip_scenario(*, contract: InstrumentContract | None, decision_at: str,
                        entered_at: str, exited_at: str, entry: Quote | None,
                        exit: Quote | None, quantity: int, side: str,
                        cost_policy: Mapping[str, Any] | None, adverse_ticks: int,
                        max_quote_age_seconds: int) -> dict[str, Any]:
    """Fully observed quotes permit only a price scenario, not a fill assertion.

    Full top-level depth is required; partial fills, queue priority, intrabar stops,
    expiry exercise, rolls, short options and multi-order futures are unsupported.
    """
    result: dict[str, Any] = {'status': 'INSUFFICIENT_DATA', 'reasons': [],
        'gross_pnl': None, 'net_pnl': None, 'charges': None,
        'risk_status': 'INSUFFICIENT_DATA', 'risk_blockers': ['PIT_MARGIN_AND_RISK_EVIDENCE_MISSING'],
        'margin_is_maximum_loss': False, 'full_execution_engine': False,
        'approval_authority': False, 'fill_evidence': False, 'training_eligible': False}
    missing = [name for name, value in (('contract', contract), ('entry_quote', entry),
        ('exit_quote', exit), ('dated_cost_policy', cost_policy)) if value is None]
    if missing:
        return {**result, 'reasons': missing}
    assert contract is not None and entry is not None and exit is not None and cost_policy is not None
    try:
        decision, entered, exited = (scoped_time(v, contract.data_scope) for v in (decision_at, entered_at, exited_at))
        contract.validate(decision_at)
        try:
            reviewed = instant(cost_policy['reviewed_at'])
        except (KeyError, ResearchError):
            raise ResearchError('COST_POLICY_NOT_AVAILABLE_AT_DECISION') from None
        if reviewed > decision:
            raise ResearchError('COST_POLICY_NOT_AVAILABLE_AT_DECISION')
        if (not decision < entered < exited <= scoped_time(contract.exit_deadline, contract.data_scope)
                or side not in ('BUY', 'SELL') or (contract.kind == 'OPTION' and side != 'BUY')
                or type(quantity) is not int or quantity <= 0 or quantity % contract.lot_size
                or type(adverse_ticks) is not int or adverse_ticks < 0
                or type(max_quote_age_seconds) is not int or max_quote_age_seconds <= 0):
            raise ResearchError('EXECUTION_CONTRACT_INVALID')
        entry.validate(contract, entered_at, max_quote_age_seconds)
        exit.validate(contract, exited_at, max_quote_age_seconds)
        if (scoped_time(entry.exchange_at, contract.data_scope) <= decision
                or scoped_time(exit.exchange_at, contract.data_scope) <= entered):
            raise ResearchError('POST_DECISION_QUOTES_REQUIRED')
        depth_entry = entry.ask_quantity if side == 'BUY' else entry.bid_quantity
        depth_exit = exit.bid_quantity if side == 'BUY' else exit.ask_quantity
        if min(depth_entry, depth_exit) < quantity:
            raise ResearchError('INSUFFICIENT_VISIBLE_DEPTH')
        stress = decimal(contract.tick_size) * adverse_ticks
        entry_price = decimal(entry.ask if side == 'BUY' else entry.bid) + (stress if side == 'BUY' else -stress)
        exit_price = decimal(exit.bid if side == 'BUY' else exit.ask) + (-stress if side == 'BUY' else stress)
        from intraday_fo_costs import CostEvidenceError, round_trip
        try:
            costs = cast(Callable[..., dict[str, Any]], round_trip)(entry=str(entry_price), exit=str(exit_price), quantity=quantity,
                lot_size=contract.lot_size, kind=contract.kind, policy=dict(cost_policy),
                entered_at=entered, exited_at=exited,
                exit_deadline=scoped_time(contract.exit_deadline, contract.data_scope),
                deadline_source=contract.deadline_source, entry_side=side)
        except CostEvidenceError as exc:
            raise ResearchError('COST_EVIDENCE_INVALID') from exc
    except ResearchError as exc:
        return {**result, 'reasons': [str(exc)]}
    return {**result, 'status': 'RESEARCH_QUOTE_SCENARIO', 'reasons': [],
        'entry_price': str(entry_price), 'exit_price': str(exit_price),
        'gross_pnl': str(costs['gross_pnl']), 'net_pnl': str(costs['net_pnl']),
        'charges': str(costs['charges']), 'cost_details': {
            name: {key: str(value) for key, value in costs[name].items()}
            for name in ('entry_charges', 'exit_charges')},
        'contract_sha256': fingerprint(asdict(contract)),
        'cost_policy_sha256': fingerprint(dict(cost_policy)),
        'entry_quote_sha256': fingerprint(asdict(entry)), 'exit_quote_sha256': fingerprint(asdict(exit)),
        'basis': 'BID_ASK_PLUS_DECLARED_ADVERSE_TICKS_NOT_FILL_EVIDENCE',
        'adverse_ticks': adverse_ticks, 'quantity': quantity, 'side': side}


def summarize_scenarios(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep skipped opportunities in the denominator; never count unknowns as losses."""
    usable = [r for r in results if r.get('status') == 'RESEARCH_QUOTE_SCENARIO']
    if any(r.get('status') not in ('RESEARCH_QUOTE_SCENARIO', 'INSUFFICIENT_DATA') for r in results):
        raise ResearchError('SCENARIO_STATUS_INVALID')
    return {'opportunities': len(results), 'priced_scenarios': len(usable),
        'insufficient_data': len(results) - len(usable),
        'scenario_net_pnl': str(sum((Decimal(str(r['net_pnl'])) for r in usable), Decimal(0))) if usable else None,
        'status': 'SCENARIO_SUMMARY' if usable else 'INSUFFICIENT_DATA',
        'approval_authority': False, 'fill_evidence': False, 'training_eligible': False}


@dataclass(frozen=True)
class RiskReference:
    contract_sha256: str
    basket_sha256: str
    reference_sha256: str
    known_at: str
    effective_from: str
    effective_to: str
    margin_for_quantity: str
    quantity: int
    stress_loss_for_quantity: str
    source: str
    independently_verified: bool = False


@dataclass(frozen=True)
class RiskBudget:
    available_cash: str
    cash_buffer: str
    daily_max_loss: str
    realized_loss_today: str
    reserved_loss_other_positions: str
    maximum_trade_stress_loss: str
    frozen_at: str
    reference_sha256: str


def margin_risk_gate(*, contract: InstrumentContract | None, quote: Quote | None,
                     reference: RiskReference | None, budget: RiskBudget | None,
                     decision_at: str, quantity: int, basket_sha256: str,
                     planned_roll_at: str | None = None) -> dict[str, Any]:
    """Pure dated-reference risk gate, not a margin API or maximum-loss guarantee.

    Stress loss is an independently reviewed input, never inferred from collateral.
    Long/short futures losses are not bounded by their margin. No intraday roll or
    expiry-day entry is supported. Passing this check grants no trading authority.
    """
    result: dict[str, Any] = {'status': 'BLOCKED', 'reasons': [], 'risk_capacity_verified': False,
        'margin_is_maximum_loss': False, 'approval_authority': False, 'training_eligible': False}
    missing = [name for name, value in (('contract', contract), ('quote', quote),
        ('dated_margin_stress_reference', reference), ('frozen_risk_budget', budget)) if value is None]
    if missing:
        return {**result, 'reasons': missing}
    assert contract is not None and quote is not None and reference is not None and budget is not None
    try:
        decision = scoped_time(decision_at, contract.data_scope)
        contract.validate(decision_at)
        sha(basket_sha256)
        sha(reference.reference_sha256)
        sha(budget.reference_sha256)
        if (type(quantity) is not int or quantity <= 0 or quantity % contract.lot_size
                or type(reference.quantity) is not int or reference.quantity != quantity
                or reference.contract_sha256 != fingerprint(asdict(contract))
                or reference.basket_sha256 != basket_sha256 or reference.independently_verified is not True
                or not reference.source.startswith('https://')
                or not instant(reference.known_at) <= decision
                or not instant(reference.effective_from) <= decision <= instant(reference.effective_to)
                or instant(budget.frozen_at) > decision):
            raise ResearchError('DATED_RISK_REFERENCE_UNVERIFIED')
        # Only a causal quote is accepted; the age limit is supplied by the dated reference interval.
        quote.validate(contract, decision_at, max_age=5)
        if planned_roll_at is not None:
            raise ResearchError('INTRADAY_ROLL_UNSUPPORTED')
        from datetime import timezone, timedelta
        ist = timezone(timedelta(hours=5, minutes=30))
        if decision.astimezone(ist).date() == instant(contract.expires_at).astimezone(ist).date():
            raise ResearchError('EXPIRY_DAY_ENTRY_UNSUPPORTED')
        cash, buffer, daily, loss, reserved, trade_max = (decimal(v) for v in (
            budget.available_cash, budget.cash_buffer, budget.daily_max_loss, budget.realized_loss_today,
            budget.reserved_loss_other_positions, budget.maximum_trade_stress_loss))
        margin, stress = decimal(reference.margin_for_quantity), decimal(reference.stress_loss_for_quantity)
        if daily <= 0 or trade_max <= 0 or margin <= 0 or stress <= 0:
            raise ResearchError('NONZERO_RISK_INPUTS_REQUIRED')
        if cash < margin + buffer:
            raise ResearchError('INSUFFICIENT_CASH_AFTER_BUFFER')
        if stress > trade_max or loss + reserved + stress > daily:
            raise ResearchError('DAILY_OR_TRADE_RISK_LIMIT_EXCEEDED')
    except ResearchError as exc:
        return {**result, 'reasons': [str(exc)]}
    return {**result, 'status': 'DECLARED_RISK_REFERENCE_CHECK_PASSED',
        'declared_capacity_satisfies_inputs': True,
        'risk_capacity_verified': False, 'risk_reference_sha256': fingerprint(asdict(reference)),
        'budget_sha256': fingerprint(asdict(budget)), 'stress_loss': str(stress),
        'cash_after_margin_and_buffer': str(cash-margin-buffer),
        'daily_loss_capacity_after_stress': str(daily-loss-reserved-stress),
        'basis': 'INDEPENDENTLY_REVIEWED_REFERENCE_REQUIRED_NOT_A_LOSS_BOUND'}
