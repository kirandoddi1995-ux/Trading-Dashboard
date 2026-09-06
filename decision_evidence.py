"""Immutable decision/outcome evidence, feature registry, and experiment journal.

This module deliberately uses the existing evidence ledger as its only source
of audit truth.  It does not reconstruct historical decisions and it never
manufactures outcomes before observed market sessions prove that a horizon has
elapsed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import math
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from evidence_ledger import canonical_json


UTC = dt.timezone.utc
DECISION_EVIDENCE_VERSION = "decision-evidence-v1"
FEATURE_REGISTRY_VERSION = "feature-registry-v1"
EXPERIMENT_CONTRACT_VERSION = "experiment-tracking-v1"
DECISION_ACTIONS = {"Buy", "Watch", "No Trade"}
OUTCOMES = {"TARGET", "STOP", "TIMEOUT", "HORIZON", "EXPIRED", "UNRESOLVED"}


class EvidenceContractError(ValueError):
    """Raised when an incomplete record attempts to enter the audit ledger."""


def _aware(value: Any, name: str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise EvidenceContractError(f"{name} must be a timezone-aware datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceContractError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise EvidenceContractError(f"{name} is required")
    return text


def _finite(value: Any, name: str, *, minimum: float | None = None,
            maximum: float | None = None, optional: bool = False) -> float | None:
    if value is None and optional:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise EvidenceContractError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise EvidenceContractError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise EvidenceContractError(f"{name} is below its minimum")
    if maximum is not None and result > maximum:
        raise EvidenceContractError(f"{name} is above its maximum")
    return result


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _copy(value: Any) -> Any:
    """Detach caller-owned objects and reject NaN/infinity before persistence."""
    return json.loads(json.dumps(value, sort_keys=True, default=str, allow_nan=False))


def _audit_copy(value: Any) -> Any:
    """Preserve invalid numerics as explicit sentinels for quality evidence."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"invalid_numeric": str(value)}
    if isinstance(value, Mapping):
        return {str(key): _audit_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_audit_copy(item) for item in value]
    return _copy(value)


def _record(recorder: Callable[..., Mapping[str, Any] | None], *, aggregate_id: str,
            event_type: str, payload: Mapping[str, Any], effective_at: dt.datetime,
            idempotency_key: str, source: str) -> Mapping[str, Any]:
    event = recorder(
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=_copy(payload),
        effective_at=effective_at,
        idempotency_key=idempotency_key,
        source=source,
    )
    if event is None:
        raise RuntimeError(f"{event_type} evidence append failed")
    return event


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    version: str
    dtype: str
    source: str
    computation_logic: str
    availability_rule: str
    maximum_age_seconds: float
    nullable: bool = False
    minimum: float | None = None
    maximum: float | None = None

    def normalized(self) -> dict[str, Any]:
        name = _required_text(self.name, "feature name")
        version = _required_text(self.version, "feature version")
        maximum_age = _finite(
            self.maximum_age_seconds, "maximum_age_seconds", minimum=0,
        )
        minimum = _finite(self.minimum, "minimum", optional=True)
        maximum = _finite(self.maximum, "maximum", optional=True)
        if minimum is not None and maximum is not None and minimum > maximum:
            raise EvidenceContractError("feature minimum exceeds maximum")
        return {
            "contract_version": FEATURE_REGISTRY_VERSION,
            "name": name,
            "version": version,
            "dtype": _required_text(self.dtype, "feature dtype"),
            "source": _required_text(self.source, "feature source"),
            "computation_logic": _required_text(
                self.computation_logic, "feature computation_logic",
            ),
            "availability_rule": _required_text(
                self.availability_rule, "feature availability_rule",
            ),
            "maximum_age_seconds": maximum_age,
            "nullable": bool(self.nullable),
            "minimum": minimum,
            "maximum": maximum,
        }


class FeatureRegistry:
    """Versioned feature definitions persisted as immutable ledger events."""

    def __init__(self, recorder: Callable[..., Mapping[str, Any] | None], ledger,
                 *, source: str = "feature-registry"):
        self._recorder = recorder
        self._ledger = ledger
        self._source = source

    def register(self, definition: FeatureDefinition, *, registered_at=None) -> dict[str, Any]:
        payload = definition.normalized()
        payload["definition_hash"] = _hash(payload)
        effective = _aware(registered_at or dt.datetime.now(UTC), "registered_at")
        aggregate = f"feature:{payload['name']}:{payload['version']}"
        existing = [event["payload"] for event in self._ledger.events(aggregate)
                    if event["event_type"] == "FEATURE_DEFINITION_REGISTERED"]
        if existing and existing[-1].get("definition_hash") != payload["definition_hash"]:
            raise EvidenceContractError(
                "Feature version is already registered with a different definition; bump its version"
            )
        event = _record(
            self._recorder,
            aggregate_id=aggregate,
            event_type="FEATURE_DEFINITION_REGISTERED",
            payload=payload,
            effective_at=effective,
            idempotency_key=f"feature-definition:{payload['definition_hash']}",
            source=self._source,
        )
        return {**payload, "duplicate": bool(event.get("duplicate"))}

    def definition(self, name: str, version: str) -> dict[str, Any] | None:
        aggregate = f"feature:{str(name)}:{str(version)}"
        events = self._ledger.events(aggregate)
        definitions = [event["payload"] for event in events
                       if event["event_type"] == "FEATURE_DEFINITION_REGISTERED"]
        return _copy(definitions[-1]) if definitions else None

    def definitions(self) -> list[dict[str, Any]]:
        result = []
        for aggregate in self._ledger.aggregate_ids(prefix="feature:"):
            events = self._ledger.events(aggregate)
            result.extend(event["payload"] for event in events
                          if event["event_type"] == "FEATURE_DEFINITION_REGISTERED")
        return _copy(result)


class FeatureQualityMonitor:
    """Validate feature lineage continuously and persist every quality result."""

    def __init__(self, registry: FeatureRegistry, recorder, metrics=None,
                 logger: logging.Logger | None = None):
        self._registry = registry
        self._recorder = recorder
        self._metrics = metrics
        self._logger = logger or logging.getLogger("feature-quality")

    def observe(self, *, source_id: str, feature_lineage: Mapping[str, Mapping[str, Any]],
                decision_at: Any, required_features: Iterable[str] = ()) -> dict[str, Any]:
        observed_at = _aware(decision_at, "decision_at")
        raw_lineage = dict(feature_lineage or {})
        lineage = _audit_copy(raw_lineage)
        required = sorted({_required_text(name, "required feature") for name in required_features})
        failures: list[dict[str, str]] = []
        for name in required:
            if name not in lineage:
                failures.append({"feature": name, "code": "MISSING"})
        checked = 0
        for name, row in sorted(raw_lineage.items()):
            checked += 1
            if not isinstance(row, Mapping):
                failures.append({"feature": name, "code": "SCHEMA_DRIFT"})
                continue
            version = str(row.get("definition_version") or "").strip()
            definition = self._registry.definition(name, version) if version else None
            if definition is None:
                failures.append({"feature": name, "code": "UNREGISTERED_VERSION"})
            try:
                effective = _aware(row.get("effective_at"), f"{name}.effective_at")
                available = _aware(row.get("available_at"), f"{name}.available_at")
                if effective > available or available > observed_at:
                    failures.append({"feature": name, "code": "FUTURE_OR_REVERSED_TIME"})
                maximum_age = _finite(
                    row.get("maximum_age_seconds"), f"{name}.maximum_age_seconds", minimum=0,
                )
                if (observed_at - available).total_seconds() > maximum_age:
                    failures.append({"feature": name, "code": "STALE"})
            except EvidenceContractError:
                failures.append({"feature": name, "code": "TIMESTAMP_INVALID"})
            value = row.get("value")
            if value is None:
                if not definition or not definition.get("nullable"):
                    failures.append({"feature": name, "code": "MISSING_VALUE"})
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                try:
                    numeric = _finite(value, f"{name}.value")
                    if definition and definition.get("minimum") is not None and numeric < definition["minimum"]:
                        failures.append({"feature": name, "code": "RANGE_LOW"})
                    if definition and definition.get("maximum") is not None and numeric > definition["maximum"]:
                        failures.append({"feature": name, "code": "RANGE_HIGH"})
                except EvidenceContractError:
                    failures.append({"feature": name, "code": "NON_FINITE"})
        payload = {
            "contract_version": FEATURE_REGISTRY_VERSION,
            "source_id": _required_text(source_id, "source_id"),
            "observed_at": observed_at.isoformat(),
            "feature_count": checked,
            "required_features": required,
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
            "lineage_hash": _hash({"lineage": lineage}),
        }
        digest = _hash(payload)
        _record(
            self._recorder,
            aggregate_id=f"feature-quality:{payload['source_id']}",
            event_type="FEATURE_QUALITY_OBSERVED",
            payload=payload,
            effective_at=observed_at,
            idempotency_key=f"feature-quality:{digest}",
            source="feature-quality-monitor",
        )
        if self._metrics is not None:
            self._metrics.record(
                "feature_quality", payload["source_id"], 0.0,
                ok=not failures, status=payload["status"], count=max(checked, 1),
            )
        if failures:
            self._logger.warning(
                "feature_quality_failed source=%s failure_count=%d",
                payload["source_id"], len(failures),
            )
        return payload


class ExperimentTracker:
    """Append-only trial history, including repeats and negative results."""

    FINAL_STATUSES = {"VALIDATED", "NEGATIVE", "FAILED", "INCONCLUSIVE", "ABSTAIN"}

    def __init__(self, recorder, ledger, *, source="experiment-tracker"):
        self._recorder = recorder
        self._ledger = ledger
        self._source = source

    @staticmethod
    def fingerprint(*, hypothesis: str, data_window: Mapping[str, Any],
                    config_hash: str, feature_versions: Mapping[str, str]) -> str:
        payload = {
            "hypothesis": _required_text(hypothesis, "hypothesis"),
            "data_window": _copy(dict(data_window or {})),
            "config_hash": _required_text(config_hash, "config_hash"),
            "feature_versions": _copy(dict(feature_versions or {})),
        }
        if not payload["data_window"] or not payload["feature_versions"]:
            raise EvidenceContractError("data_window and feature_versions are required")
        return _hash(payload)

    def start(self, *, hypothesis: str, data_window: Mapping[str, Any], config_hash: str,
              feature_versions: Mapping[str, str], code_hash: str, trial_id: str | None = None,
              started_at=None) -> dict[str, Any]:
        effective = _aware(started_at or dt.datetime.now(UTC), "started_at")
        fingerprint = self.fingerprint(
            hypothesis=hypothesis, data_window=data_window, config_hash=config_hash,
            feature_versions=feature_versions,
        )
        aggregate = f"experiment:{fingerprint}"
        prior = [event for event in self._ledger.events(aggregate)
                 if event["event_type"] in {"EXPERIMENT_REGISTERED", "EXPERIMENT_RETRIED"}]
        attempt = len(prior) + 1
        trial = str(trial_id or uuid.uuid4())
        payload = {
            "contract_version": EXPERIMENT_CONTRACT_VERSION,
            "trial_id": trial,
            "fingerprint": fingerprint,
            "attempt": attempt,
            "hypothesis": _required_text(hypothesis, "hypothesis"),
            "data_window": _copy(dict(data_window)),
            "config_hash": _required_text(config_hash, "config_hash"),
            "code_hash": _required_text(code_hash, "code_hash"),
            "feature_versions": _copy(dict(feature_versions)),
            "started_at": effective.isoformat(),
        }
        event_type = "EXPERIMENT_RETRIED" if prior else "EXPERIMENT_REGISTERED"
        _record(
            self._recorder, aggregate_id=aggregate, event_type=event_type,
            payload=payload, effective_at=effective,
            idempotency_key=f"experiment-start:{trial}", source=self._source,
        )
        return payload

    def finish(self, trial: Mapping[str, Any], *, status: str, metrics: Mapping[str, Any],
               result_summary: str, finished_at=None) -> dict[str, Any]:
        state = str(status or "").upper()
        if state not in self.FINAL_STATUSES:
            raise EvidenceContractError(f"Unsupported experiment result status: {state}")
        trial_id = _required_text(trial.get("trial_id"), "trial_id")
        fingerprint = _required_text(trial.get("fingerprint"), "fingerprint")
        effective = _aware(finished_at or dt.datetime.now(UTC), "finished_at")
        if effective < _aware(trial.get("started_at"), "started_at"):
            raise EvidenceContractError("finished_at precedes started_at")
        payload = {
            "contract_version": EXPERIMENT_CONTRACT_VERSION,
            "trial_id": trial_id,
            "fingerprint": fingerprint,
            "attempt": int(trial.get("attempt") or 0),
            "status": state,
            "metrics": _copy(dict(metrics or {})),
            "result_summary": _required_text(result_summary, "result_summary"),
            "finished_at": effective.isoformat(),
        }
        _record(
            self._recorder, aggregate_id=f"experiment:{fingerprint}",
            event_type="EXPERIMENT_RESULT_RECORDED", payload=payload,
            effective_at=effective, idempotency_key=f"experiment-result:{trial_id}",
            source=self._source,
        )
        return payload


class DecisionEvidenceSpine:
    """Strict adapter from live governance evidence to immutable ledger events."""

    def __init__(self, recorder, ledger, *, feature_quality: FeatureQualityMonitor | None = None,
                 source="decision-evidence-spine"):
        self._recorder = recorder
        self._ledger = ledger
        self._feature_quality = feature_quality
        self._source = source

    @staticmethod
    def _quote_snapshot(evidence, supplied: Mapping[str, Any]) -> dict[str, Any]:
        quote = dict(supplied or {})
        source = str(quote.get("source") or getattr(evidence, "quote_source", "")).strip()
        observed = getattr(evidence, "quote_observed_at", None)
        received = getattr(evidence, "quote_received_at", None)
        bid = _finite(quote.get("bid"), "quote.bid", minimum=0, optional=True)
        ask = _finite(quote.get("ask"), "quote.ask", minimum=0, optional=True)
        last = _finite(quote.get("last"), "quote.last", minimum=0, optional=True)
        available = bool(source and observed is not None and received is not None and bid is not None and ask is not None)
        if bid is not None and ask is not None and bid > ask:
            raise EvidenceContractError("quote bid exceeds ask")
        return {
            "status": "AVAILABLE" if available else "UNAVAILABLE",
            "source": source or None,
            "bid": bid,
            "ask": ask,
            "last": last,
            "observed_at": _aware(observed, "quote_observed_at").isoformat() if observed is not None else None,
            "received_at": _aware(received, "quote_received_at").isoformat() if received is not None else None,
            "quote_age_seconds": getattr(evidence, "quote_age_seconds", None),
            "unavailable_reason": None if available else _required_text(
                quote.get("unavailable_reason") or "Executable bid/ask evidence is incomplete",
                "quote unavailable_reason",
            ),
        }

    @staticmethod
    def _universe_snapshot(evidence, supplied: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(supplied or {})
        observed = row.get("observed_at", getattr(evidence, "universe_observed_at", None))
        effective = row.get("effective_at", getattr(evidence, "universe_effective_at", None))
        verified = bool(
            row.get("snapshot_id") and row.get("payload_hash") and row.get("source")
            and row.get("member") is True and observed and effective
        )
        return {
            "status": "VERIFIED" if verified else "UNAVAILABLE",
            "snapshot_id": row.get("snapshot_id"),
            "payload_hash": row.get("payload_hash"),
            "source": row.get("source"),
            "member": row.get("member") if row.get("member") is not None else None,
            "observed_at": _aware(observed, "universe.observed_at").isoformat() if observed else None,
            "effective_at": _aware(effective, "universe.effective_at").isoformat() if effective else None,
            "unavailable_reason": None if verified else _required_text(
                row.get("unavailable_reason") or "PIT universe membership evidence is incomplete",
                "universe unavailable_reason",
            ),
        }

    @staticmethod
    def _costs(costs: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(costs or {})
        required = {"round_trip_bps", "spread_bps", "slippage_bps", "impact_bps",
                    "statutory_bps", "brokerage_bps", "breakdown_complete", "assumptions"}
        missing = sorted(required - set(row))
        if missing:
            raise EvidenceContractError(f"cost context is missing: {', '.join(missing)}")
        return {
            "round_trip_bps": _finite(row["round_trip_bps"], "round_trip_bps", minimum=0),
            "spread_bps": _finite(row["spread_bps"], "spread_bps", minimum=0, optional=True),
            "slippage_bps": _finite(row["slippage_bps"], "slippage_bps", minimum=0, optional=True),
            "impact_bps": _finite(row["impact_bps"], "impact_bps", minimum=0, optional=True),
            "statutory_bps": _finite(row["statutory_bps"], "statutory_bps", minimum=0, optional=True),
            "brokerage_bps": _finite(row["brokerage_bps"], "brokerage_bps", minimum=0, optional=True),
            "breakdown_complete": bool(row["breakdown_complete"]),
            "assumptions": _required_text(row["assumptions"], "cost assumptions"),
        }

    def capture(self, *, evidence, action: str, direction: str, entry: Any, stop: Any,
                target: Any, quantity: Any, governance: Mapping[str, Any],
                quote: Mapping[str, Any], universe: Mapping[str, Any], costs: Mapping[str, Any],
                code_version: str, code_hash: str, config_hash: str, policy_hash: str,
                correlation_id: str, decision_id: str | None = None,
                input_values: Mapping[str, Any] | None = None) -> dict[str, Any]:
        label = str(action or "").strip().title()
        if label not in DECISION_ACTIONS:
            raise EvidenceContractError("action must be Buy, Watch, or No Trade")
        context = evidence.context
        decision_at = _aware(context.decision_at, "decision_at")
        raw_features = dict(evidence.feature_lineage or {})
        quality = None
        if self._feature_quality is not None:
            quality = self._feature_quality.observe(
                source_id=f"{context.asset_class}:{context.strategy_id}",
                feature_lineage=raw_features, decision_at=decision_at,
                required_features=raw_features.keys(),
            )
        features = _copy(raw_features)
        raw_values = _copy(dict(input_values or {
            name: row.get("value") for name, row in features.items()
            if isinstance(row, Mapping)
        }))
        feature_state = "AVAILABLE" if features else "UNAVAILABLE"
        quote_snapshot = self._quote_snapshot(evidence, quote)
        universe_snapshot = self._universe_snapshot(evidence, universe)
        cost_snapshot = self._costs(costs)
        governance_snapshot = _copy(dict(governance or {}))
        if not governance_snapshot:
            raise EvidenceContractError("governance context is required")
        if label == "Buy":
            failures = []
            if quote_snapshot["status"] != "AVAILABLE": failures.append("executable quote")
            if universe_snapshot["status"] != "VERIFIED": failures.append("PIT universe")
            if feature_state != "AVAILABLE": failures.append("PIT features")
            if not cost_snapshot["breakdown_complete"]: failures.append("complete transaction costs")
            if failures:
                raise EvidenceContractError(
                    "Buy decision lacks " + ", ".join(failures)
                )
        levels = {
            "entry": _finite(entry, "entry", minimum=0, optional=True),
            "stop": _finite(stop, "stop", minimum=0, optional=True),
            "target": _finite(target, "target", minimum=0, optional=True),
            "quantity": int(_finite(quantity, "quantity", minimum=0)),
            "direction": _required_text(direction, "direction"),
        }
        identifiers = {
            "strategy_id": _required_text(context.strategy_id, "strategy_id"),
            "asset_class": _required_text(context.asset_class, "asset_class"),
            "target_version": _required_text(context.target_version, "target_version"),
            "horizon_sessions": int(context.horizon_sessions),
            "instrument": _required_text(context.instrument, "instrument"),
            "feature_schema_hash": _required_text(context.feature_schema_hash, "feature_schema_hash"),
            "code_version": _required_text(code_version, "code_version"),
            "code_hash": _required_text(code_hash, "code_hash"),
            "config_hash": _required_text(config_hash, "config_hash"),
            "policy_hash": _required_text(policy_hash, "policy_hash"),
            "correlation_id": _required_text(correlation_id, "correlation_id"),
        }
        stable_id = decision_id or _hash({
            "decision_at": decision_at.isoformat(), "identifiers": identifiers,
        })
        payload = {
            "contract_version": DECISION_EVIDENCE_VERSION,
            "decision_id": stable_id,
            "decision_at": decision_at.isoformat(),
            "action": label,
            "identifiers": identifiers,
            "features": {"status": feature_state, "values": features,
                         "raw_values_used": raw_values,
                         "unavailable_reason": None if features else "PIT feature lineage is unavailable"},
            "universe": universe_snapshot,
            "quote": quote_snapshot,
            "costs": cost_snapshot,
            "levels": levels,
            "governance": governance_snapshot,
            "feature_quality": quality,
            "maturity": {"status": "PENDING", "horizon_sessions": int(context.horizon_sessions)},
        }
        event = _record(
            self._recorder, aggregate_id=f"decision:{stable_id}",
            event_type="DECISION_EVALUATED", payload=payload,
            effective_at=decision_at,
            idempotency_key=f"decision-evidence:{stable_id}", source=self._source,
        )
        return {"decision_id": stable_id, "event": event, "record": _copy(payload)}

    def capture_candidate_batch(self, *, scan_run_id: str, observed_at: Any,
                                strategy_id: str, target_version: str,
                                horizon_sessions: int, candidates: Sequence[Mapping[str, Any]],
                                universe: Mapping[str, Any], code_version: str,
                                code_hash: str, config_hash: str, policy_hash: str) -> dict[str, Any]:
        """Anchor the complete Stage-1 funnel without thousands of remote writes."""
        run_id = _required_text(scan_run_id, "scan_run_id")
        timestamp = _aware(observed_at, "observed_at")
        rows = []
        for raw in candidates:
            row = dict(raw or {})
            action = str(row.get("action") or "")
            if action not in DECISION_ACTIONS:
                raise EvidenceContractError("every batched candidate needs a valid action")
            rows.append({
                "decision_id": _required_text(row.get("decision_id"), "decision_id"),
                "instrument_key": _required_text(row.get("instrument_key"), "instrument_key"),
                "instrument": _required_text(row.get("instrument"), "instrument"),
                "action": action,
                "stage1_pass": bool(row.get("stage1_pass")),
                "rejection_reason": row.get("rejection_reason"),
                "inputs_used": _copy(dict(row.get("inputs_used") or {})),
                "quote": _copy(dict(row.get("quote") or {
                    "status": "UNAVAILABLE", "reason": "No quote context supplied",
                })),
                "costs": _copy(dict(row.get("costs") or {
                    "status": "NOT_EVALUATED", "reason": "Stage-1 candidate only",
                })),
            })
        if not rows:
            raise EvidenceContractError("candidate batch cannot be empty")
        snapshot = dict(universe or {})
        payload = {
            "contract_version": DECISION_EVIDENCE_VERSION,
            "scan_run_id": run_id,
            "observed_at": timestamp.isoformat(),
            "strategy_id": _required_text(strategy_id, "strategy_id"),
            "target_version": _required_text(target_version, "target_version"),
            "horizon_sessions": int(_finite(horizon_sessions, "horizon_sessions", minimum=1)),
            "code_version": _required_text(code_version, "code_version"),
            "code_hash": _required_text(code_hash, "code_hash"),
            "config_hash": _required_text(config_hash, "config_hash"),
            "policy_hash": _required_text(policy_hash, "policy_hash"),
            "universe": _copy(snapshot),
            "candidate_count": len(rows),
            "candidates": rows,
        }
        event = _record(
            self._recorder, aggregate_id=f"scan:{run_id}",
            event_type="DECISION_BATCH_EVALUATED", payload=payload,
            effective_at=timestamp, idempotency_key=f"decision-batch:{run_id}",
            source=self._source,
        )
        return {"scan_run_id": run_id, "event": event, "record": _copy(payload)}

    def outcome(self, *, decision_id: str, outcome: str, outcome_at: Any,
                actual_forward_return: Any, completed_session_closes: Sequence[Any],
                source_observation_ids: Sequence[str], actual_costs: Mapping[str, Any],
                now=None) -> dict[str, Any]:
        identifier = _required_text(decision_id, "decision_id")
        events = self._ledger.events(f"decision:{identifier}")
        decisions = [event for event in events if event["event_type"] == "DECISION_EVALUATED"]
        if len(decisions) != 1:
            raise EvidenceContractError("exactly one immutable decision event is required")
        decision = decisions[0]["payload"]
        decision_at = _aware(decision["decision_at"], "decision_at")
        observed_at = _aware(outcome_at, "outcome_at")
        current = _aware(now or dt.datetime.now(UTC), "now")
        if observed_at <= decision_at or observed_at > current:
            raise EvidenceContractError("outcome chronology is invalid")
        horizon = int(decision["identifiers"]["horizon_sessions"])
        session_closes = sorted({
            _aware(value, "completed_session_close") for value in completed_session_closes
            if _aware(value, "completed_session_close") > decision_at
        })
        if len(session_closes) < horizon or session_closes[horizon - 1] > current:
            raise EvidenceContractError("real market-session horizon has not passed")
        state = str(outcome or "").upper()
        if state not in OUTCOMES:
            raise EvidenceContractError(f"unsupported outcome: {state}")
        proof = [_required_text(value, "source_observation_id") for value in source_observation_ids]
        if not proof:
            raise EvidenceContractError("source observation proof is required")
        payload = {
            "contract_version": DECISION_EVIDENCE_VERSION,
            "decision_id": identifier,
            "target_version": decision["identifiers"]["target_version"],
            "horizon_sessions": horizon,
            "outcome": state,
            "outcome_at": observed_at.isoformat(),
            "actual_forward_return": _finite(actual_forward_return, "actual_forward_return"),
            "completed_session_closes": [value.isoformat() for value in session_closes],
            "source_observation_ids": proof,
            "actual_costs": _copy(dict(actual_costs or {})),
            "matured_at": current.isoformat(),
        }
        event = _record(
            self._recorder, aggregate_id=f"decision:{identifier}",
            event_type="OUTCOME_MATURED", payload=payload,
            effective_at=observed_at,
            idempotency_key=(
                f"decision-outcome:{identifier}:{decision['identifiers']['target_version']}"
            ),
            source=self._source,
        )
        return {"decision_id": identifier, "event": event, "outcome": _copy(payload)}
