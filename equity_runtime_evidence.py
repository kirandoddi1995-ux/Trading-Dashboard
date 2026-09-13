"""Assemble exact equity live evidence from signed production artifacts."""
from __future__ import annotations

from typing import Mapping
from artifact_security import verify_equity_artifact_integrity

from calibration_artifacts import infer_equity_probability
from continuous_evolution import evaluate_model_ensemble
from live_evidence import EvidenceTier, LiveEvidenceBundle, LiveEvidenceContext


def _latest_feature_at(lineage: Mapping):
    values = [row.get("available_at") for row in dict(lineage or {}).values() if row.get("available_at")]
    return max(values) if values else None


def build_equity_live_evidence(
    *, context: LiveEvidenceContext, score: float, feature_lineage: Mapping,
    quote_observed_at, quote_received_at, quote_source: str,
    universe_observed_at, universe_effective_at, registry, runtime_store,
    model_artifact_signer=None, runtime_evidence_signer=None,
    correctness_evidence=None, ledger_status=None,
) -> LiveEvidenceBundle:
    common = dict(
        context=context, quote_observed_at=quote_observed_at,
        quote_received_at=quote_received_at, quote_source=quote_source,
        feature_lineage=dict(feature_lineage or {}),
        universe_observed_at=universe_observed_at,
        universe_effective_at=universe_effective_at,
        correctness_evidence=correctness_evidence, ledger_status=ledger_status,
    )
    is_equity = context.asset_class == "equity"
    if model_artifact_signer is None and not is_equity:
        return LiveEvidenceBundle(tier=EvidenceTier.OBSERVATION, **common)
    active = registry.active_champion(
        regime="GLOBAL", strategy_id=context.strategy_id,
        target_version=context.target_version, horizon_sessions=context.horizon_sessions,
    )
    feature_at = _latest_feature_at(feature_lineage)
    if not active or feature_at is None:
        return LiveEvidenceBundle(tier=EvidenceTier.OBSERVATION, **common)
    inference = infer_equity_probability(
        active["artifact"], score=score, feature_at=feature_at,
        inference_at=context.decision_at, expected_context=context.compatibility_fields(),
        registry_record=active,
        verify_signature=(model_artifact_signer.verify if model_artifact_signer else None),
        require_signature=not is_equity,
    )
    if inference.get("status") != "PASS":
        return LiveEvidenceBundle(tier=EvidenceTier.OBSERVATION, **common)
    prediction = inference["model_prediction"]
    weights = {prediction["model_id"]: 1.0}
    model_result = evaluate_model_ensemble(
        [prediction], weights=weights, selected_regime="GLOBAL",
        expected_feature_schema_hash=context.feature_schema_hash,
        decision_at=context.decision_at,
        asset_class=context.asset_class,
    )
    calibration = dict(inference["calibration_evidence"])
    calibration["ensemble_hash"] = model_result["ensemble_hash"]
    exact = context.compatibility_fields()
    conformal = fill = portfolio = execution_outcomes = None
    verifier = (verify_equity_artifact_integrity if is_equity else
                runtime_evidence_signer.verify if runtime_evidence_signer else None)
    if verifier is not None:
        if is_equity:
            execution_outcomes = runtime_store.latest(
                "EQUITY_EXECUTION_OUTCOMES", {**exact, "instrument": context.instrument},
                verify_signature=verifier, now=context.decision_at,
            )
        else:
            conformal = runtime_store.latest(
            "CONFORMAL", exact, verify_signature=verifier,
            now=context.decision_at,
            )
            fill = runtime_store.latest(
            "FILL", exact, verify_signature=verifier,
            now=context.decision_at,
            )
        portfolio = runtime_store.portfolio(
            exact, verify_signature=verifier,
            now=context.decision_at,
        )
    return LiveEvidenceBundle(
        tier=EvidenceTier.VALIDATED,
        model_predictions=(prediction,), model_weights=weights,
        calibration_evidence=calibration, conformal_evidence=conformal,
        fill_evidence=fill,
        equity_execution_evidence=execution_outcomes,
        portfolio_returns=(portfolio or {}).get("returns"),
        portfolio_weights=(portfolio or {}).get("weights", {}),
        stress_scenarios=(portfolio or {}).get("stress_scenarios", {}),
        **common,
    )
