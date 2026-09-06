"""UI-independent live governance orchestration.

This module is the only place that converts a versioned LiveEvidenceBundle
into a trade/no-trade decision.  It has no Streamlit or provider imports and
all stateful services are injected, which makes every recommendation path
testable without starting the application.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import pandas as pd

from continuous_evolution import (
    ContinuousEvolutionPolicy,
    adaptive_conformal_interval,
    decision_evidence_bundle,
    evaluate_model_ensemble,
    executable_fill_adjusted_ev,
    predictive_correctness_claim,
    unified_control_findings,
    validate_calibration_package,
)
from evidence_tiers import evidence_tier_decision
from live_evidence import LiveEvidenceBundle
from quant_foundation import (
    PRODUCTION_QUANT_CONFIG,
    executable_expected_value,
    execution_quality_gate,
    fractional_kelly_weight,
    portfolio_risk_report,
    system_kill_switch,
    validate_point_in_time_features,
)
from production_readiness import runtime_readiness_findings
from resilience_control_plane import SafetyFinding, SafetyState


@dataclass(frozen=True)
class GovernanceServices:
    control_plane: Any
    evidence_ledger: Any
    observability: Any
    app_build: str
    evidence_recorder: Callable[..., Any] | None = None
    logger: logging.Logger = logging.getLogger("live_governance")
    readiness_environment: Mapping[str, str] | None = None
    decision_spine: Any | None = None
    code_hash: str = ""
    config_hash: str = ""


def _status(result: Mapping[str, Any] | None) -> str:
    return str((result or {}).get("status") or "UNAVAILABLE").upper()


def evaluate_live_governance(
    *,
    instrument: str,
    entry: float,
    stop: float,
    target: float,
    evidence: LiveEvidenceBundle,
    services: GovernanceServices,
    direction: str = "long",
    quantity: int = 1,
    cost_bps: float = 0.0,
    spread_bps: float | None = None,
    order_value: float | None = None,
    average_daily_value: float | None = None,
    provider_available: bool = True,
    exchange_open: bool = True,
    quote_snapshot: Mapping[str, Any] | None = None,
    cost_breakdown: Mapping[str, Any] | None = None,
    universe_lineage: Mapping[str, Any] | None = None,
    decision_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate all controls from genuine, context-bound evidence."""
    if str(instrument) != evidence.context.instrument:
        contract_failures = ["Evidence instrument does not match the candidate"]
    else:
        contract_failures = evidence.compatibility_failures()
    decision_at = evidence.context.decision_at
    quote_age = evidence.quote_age_seconds
    evolution_policy = ContinuousEvolutionPolicy(
        **dict(services.control_plane.policy.section("continuous_evolution"))
    )

    pit = validate_point_in_time_features(
        decision_at,
        evidence.feature_lineage,
        universe_observed_at=evidence.universe_observed_at,
        universe_effective_at=evidence.universe_effective_at,
        pit_coverage=(1.0 if evidence.feature_lineage else 0.0),
        policy=PRODUCTION_QUANT_CONFIG.evidence,
    )
    execution = execution_quality_gate(
        spread_bps=spread_bps,
        order_value=order_value,
        average_daily_value=average_daily_value,
        quote_age_seconds=quote_age,
        policy=PRODUCTION_QUANT_CONFIG.execution,
    )
    kill = system_kill_switch(
        feed_age_seconds=quote_age,
        provider_available=provider_available,
        exchange_open=exchange_open,
        policy=PRODUCTION_QUANT_CONFIG.portfolio,
        maximum_feed_age_seconds=PRODUCTION_QUANT_CONFIG.execution.maximum_quote_age_seconds,
    )
    model = evaluate_model_ensemble(
        evidence.model_predictions,
        weights=evidence.model_weights,
        selected_regime="UNKNOWN",
        expected_feature_schema_hash=evidence.context.feature_schema_hash,
        decision_at=decision_at,
        policy=evolution_policy,
    )
    calibration = validate_calibration_package(
        evidence.calibration_evidence,
        expected_ensemble_hash=model.get("ensemble_hash"),
        policy=evolution_policy,
    )
    expected_value = executable_expected_value(
        entry=entry,
        stop=stop,
        target=target,
        direction=direction,
        quantity=quantity,
        round_trip_cost_bps=cost_bps,
        calibration_evidence=evidence.calibration_evidence,
        config=PRODUCTION_QUANT_CONFIG,
    )
    if expected_value.get("trade_math") and calibration.get("usable"):
        allocation = fractional_kelly_weight(
            calibration.get("probability"),
            expected_value["trade_math"].get("net_ratio"),
            calibration_evidence=evidence.calibration_evidence,
            policy=PRODUCTION_QUANT_CONFIG.portfolio,
            evidence_policy=PRODUCTION_QUANT_CONFIG.evidence,
        )
    else:
        allocation = {
            "status": "UNAVAILABLE",
            "weight": 0.0,
            "reason": "Validated probability and payoff evidence are required",
        }

    conformal_package = dict(evidence.conformal_evidence or {})
    if conformal_package:
        conformal = adaptive_conformal_interval(
            conformal_package.get("point_estimate"),
            conformal_package.get("calibration_residuals", ()),
            training_end=conformal_package.get("training_end"),
            calibration_start=conformal_package.get("calibration_start"),
            calibration_end=conformal_package.get("calibration_end"),
            observed_coverage=conformal_package.get("observed_coverage"),
            alpha=conformal_package.get("alpha"),
            policy=evolution_policy,
        )
    else:
        conformal = {"status": "ABSTAIN", "failures": ["Conformal uncertainty evidence is unavailable"]}

    fill_package = dict(evidence.fill_evidence or {})
    if fill_package and calibration.get("usable"):
        target_probability = float(calibration["conservative_probability"])
        time_exit_probability = fill_package.get("time_exit_probability")
        try:
            stop_probability = 1.0 - target_probability - float(time_exit_probability)
        except (TypeError, ValueError):
            stop_probability = None
        fill_adjusted_ev = executable_fill_adjusted_ev(
            entry=entry,
            stop=stop,
            target=target,
            direction=direction,
            quantity=quantity,
            round_trip_cost_bps=cost_bps,
            target_probability=target_probability,
            stop_probability=stop_probability,
            time_exit_probability=time_exit_probability,
            time_exit_return_per_unit=fill_package.get("time_exit_return_per_unit"),
            fill_evidence=fill_package,
            adverse_selection_bps=fill_package.get("adverse_selection_bps", 0),
            policy=evolution_policy,
        )
    else:
        fill_adjusted_ev = {
            "status": "ABSTAIN",
            "failures": ["Validated calibration and fill-model evidence are required"],
        }

    portfolio = {"status": "UNAVAILABLE", "reason": "Current portfolio histories were not supplied"}
    if isinstance(evidence.portfolio_returns, pd.DataFrame) and evidence.portfolio_weights:
        portfolio = portfolio_risk_report(
            evidence.portfolio_returns,
            evidence.portfolio_weights,
            stress_scenarios=evidence.stress_scenarios,
            policy=PRODUCTION_QUANT_CONFIG.portfolio,
        )

    outbox_stats = None
    try:
        outbox_stats = services.evidence_ledger.outbox_stats()
    except Exception as exc:
        contract_failures.append(f"Evidence outbox telemetry failed: {type(exc).__name__}")

    advanced_findings = unified_control_findings(
        pit=pit,
        model=model,
        calibration=calibration,
        conformal=conformal,
        execution=execution,
        expected_value=fill_adjusted_ev,
        portfolio=portfolio,
        allocation=allocation,
        kill_switch=kill,
        ledger_status=evidence.ledger_status,
    )
    advanced_findings.extend(
        SafetyFinding("evidence_contract", "EVIDENCE_CONTEXT_MISMATCH", reason, SafetyState.NO_TRADE)
        for reason in contract_failures
    )
    readiness_findings = runtime_readiness_findings(services.readiness_environment)
    advanced_findings.extend(readiness_findings)
    resilience = services.control_plane.evaluate_recommendation(
        price=entry,
        quote_at=evidence.quote_observed_at or decision_at,
        received_at=evidence.quote_received_at or decision_at,
        quote_age_seconds=quote_age,
        provider_available=provider_available,
        exchange_open=exchange_open,
        calibration_evidence=evidence.calibration_evidence,
        outbox_stats=outbox_stats,
        runtime_expected={
            "build": os.environ.get("EXPECTED_APP_BUILD", services.app_build),
            "policy_hash": os.environ.get(
                "RESILIENCE_POLICY_SHA256", services.control_plane.policy.digest
            ),
        },
        runtime_actual={
            "build": services.app_build,
            "policy_hash": services.control_plane.policy.digest,
        },
        control_findings=advanced_findings,
    )
    resilience_public = resilience.public_dict()

    controls = {
        "pit": pit,
        "model": model,
        "calibration": calibration,
        "conformal": conformal,
        "execution": execution,
        "expected_value": fill_adjusted_ev,
        "portfolio": portfolio,
        "allocation": allocation,
        "kill_switch": kill,
        "production_readiness": {
            "status": "PASS" if not readiness_findings else "ABSTAIN",
            "failures": [finding.detail for finding in readiness_findings],
        },
    }
    for control_name, control_result in controls.items():
        control_status = _status(control_result)
        services.observability.record(
            "quant_control",
            control_name,
            0.0,
            ok=control_status == "PASS",
            status=control_status,
            correlation_id=resilience_public["correlation_id"],
        )
    services.observability.record(
        "safety_state",
        resilience_public["state"],
        0.0,
        ok=resilience.allow_new_trades,
        status=resilience_public["state"],
        correlation_id=resilience_public["correlation_id"],
    )
    services.logger.info(
        "resilience_decision instrument=%s state=%s correlation_id=%s",
        instrument,
        resilience_public["state"],
        resilience_public["correlation_id"],
    )

    correctness = predictive_correctness_claim(evidence.correctness_evidence, evolution_policy)
    evidence_bundle = decision_evidence_bundle(
        instrument=instrument,
        decision_at=decision_at,
        model=model,
        pit=pit,
        calibration=calibration,
        conformal=conformal,
        execution=execution,
        expected_value=fill_adjusted_ev,
        portfolio=portfolio,
        allocation=allocation,
        kill_switch=kill,
        safety=resilience_public,
        claim=correctness,
    )
    recorder_failures: list[str] = []
    if callable(services.evidence_recorder):
        for aggregate_id, event_type, payload, key_suffix, source in (
            (
                f"safety:{resilience_public['correlation_id']}",
                "RISK_DECISION",
                resilience_public,
                f"safety:{resilience_public['correlation_id']}",
                "resilience-control-plane",
            ),
            (
                f"decision:{evidence_bundle['decision_hash']}",
                "CONTINUOUS_DECISION",
                evidence_bundle,
                f"decision:{evidence_bundle['decision_hash']}",
                "continuous-evolution",
            ),
        ):
            try:
                event = services.evidence_recorder(
                    aggregate_id=aggregate_id,
                    event_type=event_type,
                    payload=payload,
                    effective_at=decision_at,
                    idempotency_key=f"{services.app_build}:{key_suffix}",
                    source=source,
                )
                if event is None:
                    recorder_failures.append(f"{event_type} evidence append failed")
            except Exception as exc:
                recorder_failures.append(f"{event_type} evidence append failed: {type(exc).__name__}")

    blocking = list(contract_failures)
    blocking.extend(item.detail for item in resilience.findings if item.state >= SafetyState.NO_TRADE)
    blocking.extend(recorder_failures)
    blocking = list(dict.fromkeys(str(reason) for reason in blocking if reason))
    allow_trade = not blocking and resilience.allow_new_trades
    decision = {
        "status": "PASS" if allow_trade else "NO_TRADE",
        "allow_trade": allow_trade,
        "instrument": str(instrument),
        "decision_at": decision_at.isoformat(),
        "blocking_reasons": blocking,
        "evidence_contract": evidence.public_summary(),
        "pit": pit,
        "execution": execution,
        "kill_switch": kill,
        "expected_value": expected_value,
        "portfolio": portfolio,
        "model": model,
        "calibration": calibration,
        "conformal": conformal,
        "fill_adjusted_expected_value": fill_adjusted_ev,
        "allocation": allocation,
        "predictive_correctness": correctness,
        "evidence_bundle": evidence_bundle,
        "resilience": resilience_public,
    }
    decision["presentation"] = evidence_tier_decision(decision)
    if services.decision_spine is not None:
        costs = dict(cost_breakdown or {})
        costs.setdefault("round_trip_bps", cost_bps)
        costs.setdefault("spread_bps", spread_bps)
        for name in ("slippage_bps", "impact_bps", "statutory_bps", "brokerage_bps"):
            costs.setdefault(name, None)
        costs.setdefault("breakdown_complete", False)
        costs.setdefault(
            "assumptions",
            "Only aggregate round-trip cost was supplied; unavailable components remain explicit.",
        )
        universe = dict(universe_lineage or {})
        universe.setdefault("observed_at", evidence.universe_observed_at)
        universe.setdefault("effective_at", evidence.universe_effective_at)
        try:
            captured = services.decision_spine.capture(
                evidence=evidence,
                action=decision["presentation"]["action"],
                direction=direction,
                entry=entry,
                stop=stop,
                target=target,
                quantity=quantity,
                governance={
                    "status": decision["status"],
                    "blocking_reasons": decision["blocking_reasons"],
                    "evidence_tier": decision["presentation"]["tier"],
                    "gates": controls,
                    "safety": resilience_public,
                    "presentation": decision["presentation"],
                },
                quote=dict(quote_snapshot or {}),
                universe=universe,
                costs=costs,
                code_version=services.app_build,
                code_hash=services.code_hash,
                config_hash=services.config_hash,
                policy_hash=services.control_plane.policy.digest,
                correlation_id=resilience_public["correlation_id"],
                decision_id=decision_id,
            )
            decision["decision_evidence"] = {
                "decision_id": captured["decision_id"],
                "event_hash": captured["event"].get("event_hash"),
                "durable": True,
            }
        except Exception as exc:
            reason = f"Decision evidence append failed: {type(exc).__name__}"
            services.logger.error("%s instrument=%s", reason, instrument)
            services.observability.record(
                "decision_evidence", str(evidence.context.asset_class), 0.0,
                ok=False, status=type(exc).__name__,
                correlation_id=resilience_public["correlation_id"],
            )
            decision["blocking_reasons"] = list(dict.fromkeys(
                [*decision["blocking_reasons"], reason]
            ))
            decision["status"] = "NO_TRADE"
            decision["allow_trade"] = False
            decision["decision_evidence"] = {
                "decision_id": None, "event_hash": None, "durable": False,
                "failure": reason,
            }
            decision["presentation"] = evidence_tier_decision(decision)
    return decision
