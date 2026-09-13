"""Equity-only uncertainty, pre-trade checks and execution-evidence boundary.

No broker orders are sent here. User-entered order records and research price
touches are NOT runtime evidence. Runtime artifacts must be separately validated
against broker records; a content hash protects integrity, not authenticity.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from artifact_security import verify_equity_artifact_integrity
from continuous_evolution import _execution_outcome_ev
from live_evidence import aware_utc
from prediction_validation import wilson_score_interval
from quant_foundation import PRODUCTION_QUANT_CONFIG
from trade_contracts import EQUITY_MIN_NET_REWARD_RISK, calculate_trade_math


POLICY = "equity-conservative-execution-v1"
EVIDENCE_KIND = "EQUITY_EXECUTION_OUTCOMES"
MAXIMUM_CALIBRATION_WIDTH = .15  # Provisional, not a profitability validation.
CONTEXT_KEYS = ("strategy_id", "asset_class", "target_version", "horizon_sessions", "feature_schema_hash")


def _number(value, name, minimum=None, maximum=None):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric, not boolean")
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} is missing or invalid") from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum) or (
        maximum is not None and number > maximum
    ):
        raise ValueError(f"{name} is outside its valid range")
    return number


def _blocked(reason):
    return {"status": "ABSTAIN", "usable": False, "failures": [str(reason)]}


def calibration_uncertainty(package, calibration):
    """Check the selected group's actual Wilson interval, not return uncertainty."""
    try:
        if not calibration.get("usable") or calibration.get("status") != "PASS":
            raise ValueError("Validated calibration is required before uncertainty can pass")
        package = dict(package or {})
        probability = _number(package.get("probability"), "probability", 0, 1)
        # Match inference's first-inclusive-bin convention exactly.
        group = next((row for row in package.get("reliability", ())
                      if _number(row.get("lower_edge"), "lower_edge", 0, 1) <= probability
                      <= _number(row.get("upper_edge"), "upper_edge", 0, 1)), None)
        if not group:
            raise ValueError("Candidate probability group evidence is missing")
        count = _number(group.get("count"), "group count", 30)
        successes = _number(group.get("successes"), "group successes", 0, count)
        if count != int(count) or successes != int(successes):
            raise ValueError("Probability group counts must be integers")
        low, high = wilson_score_interval(int(successes), int(count))
        for supplied, expected in ((group.get("wilson_low"), low), (group.get("wilson_high"), high),
                                   (package.get("probability_interval_low"), low),
                                   (package.get("probability_interval_high"), high)):
            if not math.isclose(_number(supplied, "interval bound", 0, 1), expected, abs_tol=1e-12):
                raise ValueError("Calibration interval does not match its group observations")
        width = high - low
        failures = [] if width <= MAXIMUM_CALIBRATION_WIDTH + 1e-12 else [
            "Calibration group interval width exceeds provisional 0.15 policy"]
        return {"status": "ABSTAIN" if failures else "PASS", "usable": not failures,
                "method": "calibration-group-wilson", "return_conformal": "DEFERRED",
                "interval_low": low, "interval_high": high, "width": width,
                "maximum_width": MAXIMUM_CALIBRATION_WIDTH, "provisional": True,
                "group_samples": int(count), "failures": failures}
    except (ValueError, TypeError, AttributeError) as exc:
        return _blocked(exc)


def pretrade_execution(*, plan, stop, target, decision_at, quote_observed_at,
                       quote_received_at, costs):
    """Use measured depth, a limit price and explicitly estimated exit stress.

    Existing execution participation/spread/freshness limits are retained. The
    same participation cap also limits quantity versus displayed bid AND ask
    depth. A missing depth value is not inferred from volume or last price.
    """
    try:
        plan, costs = dict(plan or {}), dict(costs or {})
        policy = PRODUCTION_QUANT_CONFIG.execution
        current = aware_utc(decision_at, name="decision_at")
        observed = aware_utc(quote_observed_at, name="quote_observed_at")
        received = aware_utc(quote_received_at, name="quote_received_at")
        if not observed <= received <= current or not 0 <= (current-observed).total_seconds() <= policy.maximum_quote_age_seconds:
            raise ValueError("Fresh, ordered source and receipt timestamps are required")
        ask = _number(plan.get("ask"), "ask", 1e-12)
        bid = _number(plan.get("bid"), "bid", 1e-12, ask)
        maximum = _number(plan.get("limit_price"), "limit price", ask)
        quantity = _number(plan.get("quantity"), "quantity", 1)
        if quantity != int(quantity) or plan.get("order_type") != "LIMIT":
            raise ValueError("A whole-share limit order is required")
        ask_qty = _number(plan.get("ask_quantity"), "ask depth", 1)
        bid_qty = _number(plan.get("bid_quantity"), "bid depth", 1)
        adv = _number(plan.get("average_daily_value"), "average daily value", 1e-12)
        spread = (ask-bid) / ((ask+bid)/2) * 10000
        cap = policy.maximum_participation_rate
        if spread > policy.maximum_spread_bps:
            raise ValueError("Measured spread exceeds policy")
        if quantity > min(ask_qty, bid_qty) * cap or maximum*quantity > adv*cap:
            raise ValueError("Order exceeds displayed depth or liquidity participation limits")
        components = {key: _number(costs.get(key), key, 0) for key in (
            "slippage_bps", "impact_bps", "statutory_bps", "brokerage_bps")}
        # Entry is the limit price (not last). Stress the EXIT only by a full
        # spread or twice estimated slippage; do not add entry spread twice.
        exit_stress_bps = max(spread, 2*components["slippage_bps"])
        fees_bps = components["impact_bps"] + components["statutory_bps"] + components["brokerage_bps"]
        stress = maximum*exit_stress_bps/10000
        trade = calculate_trade_math(maximum, float(stop)-stress, float(target)-stress,
                                    round_trip_cost_bps=fees_bps,
                                    minimum_ratio=EQUITY_MIN_NET_REWARD_RISK)
        if not trade["passes_gate"]:
            raise ValueError("Exit-cost-stressed net reward/risk is below 1.30")
        return {"status": "PASS", "policy": POLICY, "failures": [], "plan": plan,
                "entry": maximum, "stop": float(stop)-stress, "target": float(target)-stress,
                "cost_bps": fees_bps, "trade_math": trade, "spread_bps": spread,
                "exit_stress_bps": exit_stress_bps, "cost_input_kind": "ESTIMATED_STRESS",
                "fill_probability": None, "actual_fill_required_after_order": True,
                "quote_observed_at": observed.isoformat(), "quote_received_at": received.isoformat()}
    except (ValueError, TypeError, AttributeError) as exc:
        return _blocked(exc)


def validate_execution_outcomes(package, *, context, decision_at):
    """Validate a separately reviewed broker-outcome artifact, never a UI record.

    Numerical intervals remain externally validated evidence, not invented here.
    Recompute point estimates from reconciled broker orders, check interval
    ordering and explicit validation provenance. No importer/promotion of manual
    or research records is provided. Hash verification is integrity, not proof
    that a broker or reviewer is honest.
    """
    try:
        row = dict(package or {})
        if (row.get("kind") != EVIDENCE_KIND or row.get("status") != "VALIDATED"
                or row.get("source_kind") != "BROKER_RECONCILED_EXECUTION_OUTCOMES"
                or row.get("purpose") != "VALIDATED_EXECUTION_EVIDENCE"):
            raise ValueError("Validated broker execution/outcome evidence is unavailable")
        if not verify_equity_artifact_integrity(row):
            raise ValueError("Execution evidence content integrity failed")
        for key in (*CONTEXT_KEYS, "instrument"):
            if context.get(key) in (None, "") or str(row.get(key)) != str(context[key]):
                raise ValueError(f"Execution evidence context mismatch: {key}")
        current = aware_utc(decision_at, name="decision_at")
        created = aware_utc(row.get("created_at"), name="created_at")
        until = aware_utc(row.get("valid_until"), name="valid_until")
        if not created <= current <= until:
            raise ValueError("Execution evidence is not current")
        validation = dict(row.get("validation") or {})
        for key in ("chronological_oos", "partial_fills_accounted", "broker_records_reconciled",
                    "costs_measured", "dependence_accounted"):
            if validation.get(key) is not True:
                raise ValueError(f"Execution evidence validation missing: {key}")
        if not validation.get("report_sha256") or not validation.get("interval_method"):
            raise ValueError("Execution evidence validation report/interval method is missing")
        if len(str(validation["report_sha256"])) != 64:
            raise ValueError("Execution validation report fingerprint is invalid")
        confidence = _number(validation.get("confidence_level"), "confidence level", .95, 1)
        records = row.get("records")
        if not isinstance(records, list) or len(records) < PRODUCTION_QUANT_CONFIG.evidence.minimum_oos_samples:
            raise ValueError("Insufficient real execution/outcome observations")
        ids, dates, fractions, filled_outcomes, time_returns = set(), set(), [], [], []
        for record in records:
            if not isinstance(record, Mapping) or record.get("source_kind") != "BROKER_EXECUTION":
                raise ValueError("Research/manual records cannot supply execution evidence")
            if record.get("purpose") != "RECONCILED_BROKER_OUTCOME" or record.get("simulated") is not False:
                raise ValueError("Only non-simulated reconciled broker outcomes are eligible")
            if any(str(record.get(key)) != str(context[key]) for key in (*CONTEXT_KEYS, "instrument")):
                raise ValueError("Broker outcome context does not match the candidate")
            identity = record.get("broker_order_id")
            if not identity or identity in ids or len(str(record.get("broker_record_sha256", ""))) != 64:
                raise ValueError("Unique broker order and source-document fingerprints are required")
            ids.add(identity)
            opened = aware_utc(record.get("submitted_at"), name="submitted_at")
            completed = aware_utc(record.get("completed_at"), name="completed_at")
            if not opened <= completed <= created:
                raise ValueError("Execution outcome was not available at artifact creation")
            dates.add(opened.date())
            requested = _number(record.get("requested_quantity"), "requested quantity", 1)
            filled = _number(record.get("filled_quantity"), "filled quantity", 0, requested)
            if requested != int(requested) or filled != int(filled):
                raise ValueError("Execution share counts must be integers")
            fractions.append(filled/requested)
            if filled == 0:
                if record.get("outcome") != "UNFILLED":
                    raise ValueError("Zero fill must have a confirmed UNFILLED outcome")
                # Existing shared arithmetic models non-fill payoff as zero.
                # Refuse evidence that violates that assumption, never erase it.
                if _number(record.get("non_fill_cost"), "non-fill cost", 0) != 0:
                    raise ValueError("Non-zero non-fill costs need a different EV contract")
                continue
            outcome = record.get("outcome")
            if outcome not in ("TARGET", "STOP", "TIME_EXIT"):
                raise ValueError("Filled order lacks a matured target/stop/time-exit outcome")
            fill_price = _number(record.get("fill_price"), "actual fill price", 1e-12)
            exit_price = _number(record.get("exit_price"), "actual exit price", 1e-12)
            costs = _number(record.get("cost_per_filled_share"), "actual costs", 0)
            filled_outcomes.append((outcome, filled/requested))
            if outcome == "TIME_EXIT":
                time_returns.append(((exit_price-fill_price-costs)/fill_price, filled/requested))
        if len(dates) < PRODUCTION_QUANT_CONFIG.evidence.minimum_observation_days:
            raise ValueError("Insufficient distinct execution observation days")
        if not time_returns or not filled_outcomes:
            raise ValueError("Real time-exit return evidence is missing")
        point = sum(fractions)/len(fractions)
        supplied = _number(row.get("fill_fraction_mean"), "fill fraction mean", 0, 1)
        if not math.isclose(point, supplied, abs_tol=1e-12):
            raise ValueError("Fill estimate does not match broker quantities")
        low = _number(row.get("fill_fraction_lower"), "fill fraction lower bound", 0, point)
        weight = sum(x[1] for x in filled_outcomes)
        time_probability = sum(w for outcome, w in filled_outcomes if outcome == "TIME_EXIT")/weight
        mean_return = sum(r*w for r, w in time_returns)/sum(w for _, w in time_returns)
        time_lower = _number(row.get("time_exit_net_return_lower"), "time-exit lower bound", maximum=mean_return)
        adverse = _number(row.get("adverse_selection_bps"), "measured adverse selection", 0)
        return {"status": "PASS", "usable": True, "failures": [],
                "conservative_fill_probability": low, "fill_fraction_mean": point,
                "time_exit_probability": time_probability,
                "time_exit_net_return_lower": time_lower, "adverse_selection_bps": adverse,
                "artifact_hash": row["artifact_hash"], "samples": len(records),
                "confidence_level": confidence, "source_kind": row["source_kind"]}
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        return _blocked(exc)


def equity_execution_ev(*, evidence, context, decision_at, calibration, execution,
                        minimum_ratio=EQUITY_MIN_NET_REWARD_RISK):
    validated = validate_execution_outcomes(evidence, context=context, decision_at=decision_at)
    failures = list(validated.get("failures", []))
    if calibration.get("usable") is not True or calibration.get("status") != "PASS":
        failures.append("Validated calibration is required for equity EV")
    if execution.get("status") != "PASS":
        failures.append("Conservative execution checks must pass before equity EV")
    if failures:
        return {"status": "ABSTAIN", "expected_value_per_order": None, "failures": failures}
    try:
        target_probability = _number(calibration.get("conservative_probability"), "calibrated probability", 0, 1)
        time_probability = validated["time_exit_probability"]
        return _execution_outcome_ev(
            entry=execution["entry"], stop=execution["stop"], target=execution["target"],
            direction="long", quantity=execution["plan"]["quantity"],
            round_trip_cost_bps=execution["cost_bps"],
            target_probability=target_probability,
            stop_probability=1-target_probability-time_probability,
            time_exit_probability=time_probability,
            time_exit_return_per_unit=validated["time_exit_net_return_lower"]*execution["entry"],
            fill=validated, adverse_selection_bps=validated["adverse_selection_bps"],
            minimum_ratio=minimum_ratio,
        )
    except (ValueError, TypeError, KeyError) as exc:
        return {"status": "ABSTAIN", "expected_value_per_order": None, "failures": [str(exc)]}
