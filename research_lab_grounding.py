"""LLM selects vetted fact IDs, never writes numerical or actionable prose."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable, Sequence

from overnight_research_dataset import ResearchError, fingerprint, unique_pairs


@dataclass(frozen=True)
class EvidenceFact:
    """Application-authored text, not market input or a user-supplied claim."""

    identity: str
    text: str
    source: str


FACTS = (
    EvidenceFact('missing_admission', 'Real model evaluation is blocked until source rights, point-in-time inputs and labels are independently admitted.', 'overnight_research_runner.run_offline'),
    EvidenceFact('missing_execution', 'Index candles are not executable futures or option quotes. Costs, contracts, spread and depth evidence are still required.', 'overnight_research_execution.round_trip_scenario'),
    EvidenceFact('small_sample', 'Intraday rows are correlated. A few captured sessions do not establish predictive skill or a calibrated win probability.', 'research_lab_statistics.calibration_diagnostics'),
    EvidenceFact('protected_periods', 'Historical validation and holdout periods remain sealed. No automatic tuning or promotion is authorized.', 'overnight_research_dataset.scoped_time'),
    EvidenceFact('synthetic_only', 'The plumbing demonstration uses generated fixtures. Its scores are not market performance or training evidence.', 'overnight_research_runner.synthetic_self_check'),
    EvidenceFact('no_authority', 'This Research Lab never approves or places orders and cannot change the live safety gates.', 'research_lab_ui.render_research_lab'),
)
SELECTOR_FORMAT = 'research-fact-selection-v1'


def grounded_explanation(*, selector: Callable[[str], str] | None = None,
                         commissioned: bool = False) -> dict[str, object]:
    """Optional explicitly commissioned local LLM adapter; no credentials/network here.

    Untrusted model output can select only fixed facts, with exact catalogue binding.
    No prompt from private data or arbitrary user instructions is accepted. Model
    failure yields a stable code, never exception text. No live backend is supplied.
    """
    if type(commissioned) is not bool:
        raise ResearchError('EXPLICIT_LLM_COMMISSION_REQUIRED')
    catalog = [{'id': f.identity, 'text': f.text, 'source': f.source} for f in FACTS]
    digest = fingerprint(catalog)
    chosen: Sequence[str] = tuple(f.identity for f in FACTS)
    mode = 'DETERMINISTIC_EVIDENCE_SUMMARY_LLM_DISABLED'
    if selector is not None and commissioned is True:
        prompt = json.dumps({'task': 'Select relevant fact IDs only; add no prose or numbers.',
            'format': SELECTOR_FORMAT, 'catalog_sha256': digest, 'facts': catalog}, sort_keys=True)
        try:
            response = selector(prompt)
            if type(response) is not str or len(response.encode()) > 4096:
                raise ValueError()
            raw = json.loads(response, object_pairs_hook=unique_pairs)
            if (not isinstance(raw, dict) or set(raw) != {'format', 'catalog_sha256', 'fact_ids'}
                    or raw['format'] != SELECTOR_FORMAT or raw['catalog_sha256'] != digest
                    or not isinstance(raw['fact_ids'], list) or not raw['fact_ids']
                    or len(raw['fact_ids']) > len(FACTS)
                    or any(type(v) is not str or v not in chosen for v in raw['fact_ids'])
                    or len(set(raw['fact_ids'])) != len(raw['fact_ids'])
                    or 'no_authority' not in raw['fact_ids']):
                raise ValueError()
            chosen = tuple(raw['fact_ids'])
            mode = 'LOCAL_LLM_FACT_SELECTION_VALIDATED'
        except Exception:
            return {'status': 'BLOCKED', 'code': 'LLM_GROUNDING_FAILED',
                'facts': [], 'approval_authority': False, 'training_eligible': False}
    elif commissioned is True:
        raise ResearchError('LOCAL_LLM_BACKEND_NOT_CONFIGURED')
    return {'status': mode, 'catalog_sha256': digest,
        'facts': [{'id': f.identity, 'text': f.text, 'source': f.source} for f in FACTS if f.identity in chosen],
        'approval_authority': False, 'training_eligible': False, 'numeric_generation': False,
        'order_tools': False}
