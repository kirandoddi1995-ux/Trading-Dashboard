"""Inactive forward quote observation diagnostics, never retrospective labels/fills."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from overnight_research_dataset import ResearchError, fingerprint, instant, sha
from overnight_research_execution import InstrumentContract, Quote, round_trip_scenario


@dataclass(frozen=True)
class PaperIntent:
    decision_row_sha256: str
    model_sha256: str
    protocol_sha256: str
    protocol_frozen_at: str
    emitted_at: str
    intended_exit_at: str
    contract_sha256: str
    quantity: int
    side: str
    adverse_ticks: int
    max_quote_age_seconds: int


def observe_forward_quotes(*, intent: PaperIntent, contract: InstrumentContract,
                           entry: Quote | None, exit: Quote | None,
                           cost_policy: Mapping[str, Any] | None, observed_at: str) -> dict[str, Any]:
    """Frozen intent precedes both observations. No TARGET/STOP or winning label.

    This function checks chronology of caller-retained evidence, not authenticity
    of a real forward collector. Commissioning and adequate/licensed data remain
    required; a retrospective fabricated intent cannot become approved evidence.
    """
    for value in (intent.decision_row_sha256, intent.model_sha256, intent.protocol_sha256, intent.contract_sha256):
        sha(value)
    emitted, deadline, observed, frozen = map(instant, (
        intent.emitted_at, intent.intended_exit_at, observed_at, intent.protocol_frozen_at))
    if (not frozen <= emitted < deadline <= observed
            or intent.contract_sha256 != fingerprint(asdict(contract))):
        raise ResearchError('FORWARD_INTENT_BINDING_INVALID')
    contract.validate(intent.emitted_at)
    result: dict[str, Any] = {'status': 'INSUFFICIENT_FORWARD_OBSERVATIONS',
        'intent_sha256': fingerprint(asdict(intent)), 'observed_at': observed.isoformat(),
        'label': None, 'target_before_stop': None, 'actual_forward_return': None,
        'training_eligible': False, 'approval_authority': False, 'fill_evidence': False,
        'authenticity_verified': False, 'paper_run_authorized': False}
    if entry is None or exit is None:
        return {**result, 'missing': [name for name, value in (('entry_quote', entry), ('exit_quote', exit)) if value is None]}
    if (not emitted < instant(entry.exchange_at) <= instant(entry.received_at) < deadline
            or not deadline <= instant(exit.exchange_at) <= instant(exit.received_at) <= observed):
        raise ResearchError('FORWARD_OBSERVATION_CHRONOLOGY_INVALID')
    scenario = round_trip_scenario(contract=contract, decision_at=intent.emitted_at,
        entered_at=entry.received_at, exited_at=exit.received_at, entry=entry, exit=exit,
        quantity=intent.quantity, side=intent.side, cost_policy=cost_policy,
        adverse_ticks=intent.adverse_ticks, max_quote_age_seconds=intent.max_quote_age_seconds)
    return {**result, 'status': 'FORWARD_QUOTE_OUTCOME_CANDIDATE' if scenario['status'] == 'RESEARCH_QUOTE_SCENARIO'
            else 'INSUFFICIENT_FORWARD_OBSERVATIONS', 'scenario': scenario,
            'basis': 'RETAINED_FORWARD_QUOTE_OBSERVATIONS_NOT_FILLED_TRADES',
            'known_at': observed.isoformat(), 'label_end': instant(exit.received_at).isoformat()}
