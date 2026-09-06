"""Fail-closed production resilience control plane for Quant Terminal.

The module contains deterministic policy evaluation only.  Vendor monitoring,
secondary quote feeds, deployment rollback, secret managers and managed backup
services must be connected explicitly; absence is visible and never reported as
healthy.  Trading exits and audit reads remain available in every safety state.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import hashlib
import json
import math
import statistics
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo


UTC = dt.timezone.utc
_CORRELATION_ID = contextvars.ContextVar("quant_correlation_id", default="")


def utcnow() -> dt.datetime:
    return dt.datetime.now(UTC)


def aware_datetime(value, *, name="timestamp") -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, (int, float)) and math.isfinite(float(value)):
        parsed = dt.datetime.fromtimestamp(float(value), UTC)
    else:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception as exc:
            raise ValueError(f"{name} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(UTC)


def finite(value, *, name="value", minimum=None, maximum=None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return parsed


def canonical_hash(value: Mapping) -> str:
    payload = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def current_correlation_id() -> str:
    value = _CORRELATION_ID.get()
    if not value:
        value = new_correlation_id()
        _CORRELATION_ID.set(value)
    return value


class correlation_scope:
    def __init__(self, correlation_id=None):
        self.correlation_id = str(correlation_id or new_correlation_id())
        self._token = None

    def __enter__(self):
        self._token = _CORRELATION_ID.set(self.correlation_id)
        return self.correlation_id

    def __exit__(self, *_):
        if self._token is not None:
            _CORRELATION_ID.reset(self._token)


class SafetyState(IntEnum):
    NORMAL = 0
    DEGRADED = 1
    NO_TRADE = 2
    READ_ONLY = 3
    EMERGENCY_STOP = 4


@dataclass(frozen=True)
class SafetyFinding:
    control: str
    code: str
    detail: str
    state: SafetyState
    observed_at: str = field(default_factory=lambda: utcnow().isoformat())
    correlation_id: str = field(default_factory=current_correlation_id)


@dataclass(frozen=True)
class SafetySnapshot:
    state: SafetyState
    findings: tuple[SafetyFinding, ...]
    correlation_id: str
    evaluated_at: str
    policy_version: str
    policy_hash: str
    clean_windows: int

    @property
    def allow_new_trades(self) -> bool:
        return self.state in {SafetyState.NORMAL, SafetyState.DEGRADED}

    @property
    def allow_writes(self) -> bool:
        return self.state < SafetyState.READ_ONLY

    @property
    def allow_exits(self) -> bool:
        return True

    @property
    def allow_audit_reads(self) -> bool:
        return True

    def public_dict(self) -> dict:
        return {
            "state": self.state.name,
            "allow_new_trades": self.allow_new_trades,
            "allow_writes": self.allow_writes,
            "allow_exits": self.allow_exits,
            "allow_audit_reads": self.allow_audit_reads,
            "findings": [
                {**asdict(item), "state": item.state.name} for item in self.findings
            ],
            "correlation_id": self.correlation_id,
            "evaluated_at": self.evaluated_at,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "clean_windows": self.clean_windows,
        }


@dataclass(frozen=True)
class ResiliencePolicy:
    raw: Mapping
    source_digest: str = ""

    @property
    def version(self):
        return str(self.raw.get("version") or "unknown")

    @property
    def digest(self):
        return self.source_digest or canonical_hash(self.raw)

    def section(self, name):
        value = self.raw.get(name)
        if not isinstance(value, Mapping):
            raise ValueError(f"Policy section {name!r} is missing")
        return value

    @classmethod
    def load(cls, path=None):
        policy_path = Path(path or Path(__file__).with_name("resilience_policy.json"))
        raw_bytes = policy_path.read_bytes()
        sidecar = policy_path.with_suffix(".sha256")
        if sidecar.exists():
            approved = sidecar.read_text(encoding="ascii").strip().lower()
            actual = hashlib.sha256(raw_bytes).hexdigest()
            if not approved or not hmac_compare(approved, actual):
                raise ValueError("Resilience policy checksum does not match its approved sidecar")
        data = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(data, Mapping):
            raise ValueError("Resilience policy must be an object")
        required = {
            "state_machine", "slo", "market_data", "calibration", "execution",
            "continuous_evolution", "clock", "collector", "outbox", "secrets",
            "recovery", "capacity", "retention",
        }
        missing = sorted(required - set(data))
        if missing:
            raise ValueError("Resilience policy is incomplete: " + ", ".join(missing))
        return cls(data, hashlib.sha256(raw_bytes).hexdigest())


class SafetyStateMachine:
    """Thread-safe state machine with hysteresis and manual emergency recovery."""

    def __init__(self, policy: ResiliencePolicy):
        self.policy = policy
        self._state = SafetyState.NORMAL
        self._clean_windows = 0
        self._lock = threading.RLock()

    @property
    def state(self):
        with self._lock:
            return self._state

    def evaluate(self, findings: Iterable[SafetyFinding], *, authorized_recovery=False):
        items = tuple(findings)
        requested = max((item.state for item in items), default=SafetyState.NORMAL)
        clean_required = int(self.policy.section("state_machine")["clean_windows_to_recover"])
        with self._lock:
            previous = self._state
            if requested >= previous:
                self._state = requested
                self._clean_windows = 0 if requested != SafetyState.NORMAL else self._clean_windows + 1
            elif requested < previous:
                self._clean_windows += 1
                emergency_locked = (
                    previous == SafetyState.EMERGENCY_STOP
                    and self.policy.section("state_machine").get("emergency_requires_authorization", True)
                    and not authorized_recovery
                )
                if not emergency_locked and self._clean_windows >= clean_required:
                    self._state = requested
                    self._clean_windows = 0
        cid = current_correlation_id()
        return SafetySnapshot(
            state=self._state, findings=items, correlation_id=cid,
            evaluated_at=utcnow().isoformat(), policy_version=self.policy.version,
            policy_hash=self.policy.digest, clean_windows=self._clean_windows,
        )


@dataclass(frozen=True)
class QuoteObservation:
    price: float
    exchange_at: dt.datetime
    received_at: dt.datetime
    source: str
    bid: float | None = None
    ask: float | None = None
    sequence: int | None = None


class MarketDataSupervisor:
    def __init__(self, policy: ResiliencePolicy):
        self.policy = policy.section("market_data")

    def evaluate(self, primary: QuoteObservation | None, *, secondary: QuoteObservation | None = None,
                 now=None, tick_size=None, heartbeat_age_seconds=0, previous_sequence=None,
                 provider_available=True) -> list[SafetyFinding]:
        findings = []
        now = aware_datetime(now or utcnow(), name="now")
        if not provider_available or primary is None:
            return [SafetyFinding("market_data", "PRIMARY_UNAVAILABLE", "Primary quote provider is unavailable", SafetyState.NO_TRADE)]
        try:
            price = finite(primary.price, name="primary price", minimum=0.0000001)
            exchange_at = aware_datetime(primary.exchange_at, name="exchange timestamp")
            received_at = aware_datetime(primary.received_at, name="receive timestamp")
            heartbeat = finite(heartbeat_age_seconds, name="heartbeat age", minimum=0)
        except ValueError as exc:
            return [SafetyFinding("market_data", "INVALID_QUOTE", str(exc), SafetyState.NO_TRADE)]
        age = (now - exchange_at).total_seconds()
        if age < -float(self.policy["maximum_clock_skew_seconds"]):
            findings.append(SafetyFinding("market_data", "FUTURE_QUOTE", f"Quote is {-age:.3f}s in the future", SafetyState.NO_TRADE))
        if age > float(self.policy["maximum_quote_age_seconds"]):
            findings.append(SafetyFinding("market_data", "STALE_QUOTE", f"Quote age is {age:.3f}s", SafetyState.NO_TRADE))
        if received_at + dt.timedelta(seconds=float(self.policy["maximum_clock_skew_seconds"])) < exchange_at:
            findings.append(SafetyFinding("market_data", "TIMESTAMP_ORDER", "Quote was received before its exchange timestamp", SafetyState.NO_TRADE))
        if heartbeat > float(self.policy["maximum_heartbeat_age_seconds"]):
            findings.append(SafetyFinding("market_data", "STALE_HEARTBEAT", f"Heartbeat age is {heartbeat:.3f}s", SafetyState.NO_TRADE))
        if primary.bid is not None or primary.ask is not None:
            try:
                bid = finite(primary.bid, name="bid", minimum=0)
                ask = finite(primary.ask, name="ask", minimum=0)
                if bid > ask or not (bid <= price <= ask):
                    findings.append(SafetyFinding("market_data", "INVALID_BOOK", "Crossed book or LTP outside best bid/ask", SafetyState.NO_TRADE))
            except ValueError as exc:
                findings.append(SafetyFinding("market_data", "INVALID_BOOK", str(exc), SafetyState.NO_TRADE))
        if previous_sequence is not None and primary.sequence is not None:
            gap = int(primary.sequence) - int(previous_sequence)
            if gap <= 0:
                findings.append(SafetyFinding("market_data", "SEQUENCE_REGRESSION", f"Sequence delta is {gap}", SafetyState.NO_TRADE))
            elif gap > int(self.policy["maximum_sequence_gap"]):
                findings.append(SafetyFinding("market_data", "SEQUENCE_GAP", f"Sequence gap is {gap}", SafetyState.DEGRADED))
        if secondary is None:
            state = SafetyState.NO_TRADE if self.policy.get("require_independent_quote") else SafetyState.DEGRADED
            findings.append(SafetyFinding("quote_reconciliation", "SECONDARY_UNAVAILABLE", "Independent quote adapter is not configured", state))
        else:
            try:
                secondary_price = finite(secondary.price, name="secondary price", minimum=0.0000001)
                secondary_age = (now - aware_datetime(secondary.exchange_at, name="secondary timestamp")).total_seconds()
                if secondary_age > float(self.policy["maximum_quote_age_seconds"]):
                    raise ValueError(f"secondary quote age is {secondary_age:.3f}s")
                difference_bps = abs(price - secondary_price) / ((price + secondary_price) / 2) * 10_000
                tick = finite(tick_size or 0, name="tick size", minimum=0)
                tick_bps = (tick * float(self.policy["minimum_cross_provider_ticks"]) / price * 10_000) if tick else 0
                allowed = max(float(self.policy["maximum_cross_provider_difference_bps"]), tick_bps)
                if difference_bps > allowed:
                    findings.append(SafetyFinding("quote_reconciliation", "QUOTE_DIVERGENCE", f"Provider difference {difference_bps:.2f} bps exceeds {allowed:.2f}", SafetyState.NO_TRADE))
            except ValueError as exc:
                findings.append(SafetyFinding("quote_reconciliation", "SECONDARY_INVALID", str(exc), SafetyState.NO_TRADE))
        return findings


class ClockSessionGuard:
    def __init__(self, policy: ResiliencePolicy):
        self.policy = policy.section("clock")

    def evaluate(self, *, now, exchange_open, ntp_offset_seconds=0, calendar_version=None,
                 expected_calendar_version=None) -> list[SafetyFinding]:
        findings = []
        try:
            aware_datetime(now, name="clock timestamp")
            offset = abs(finite(ntp_offset_seconds, name="NTP offset"))
        except ValueError as exc:
            return [SafetyFinding("clock_session", "CLOCK_INVALID", str(exc), SafetyState.NO_TRADE)]
        if offset > float(self.policy["maximum_ntp_offset_seconds"]):
            findings.append(SafetyFinding("clock_session", "CLOCK_SKEW", f"NTP offset is {offset:.3f}s", SafetyState.NO_TRADE))
        if not exchange_open:
            findings.append(SafetyFinding("clock_session", "SESSION_CLOSED", "Exchange session is not open", SafetyState.NO_TRADE))
        if expected_calendar_version and calendar_version != expected_calendar_version:
            findings.append(SafetyFinding("clock_session", "CALENDAR_DRIFT", "Runtime exchange calendar differs from approved version", SafetyState.NO_TRADE))
        return findings


class CalibrationDriftMonitor:
    def __init__(self, policy: ResiliencePolicy):
        self.policy = policy.section("calibration")
        self._consecutive = 0
        self._lock = threading.Lock()

    def evaluate(self, evidence: Mapping | None, *, now=None) -> list[SafetyFinding]:
        if not evidence:
            return [SafetyFinding("calibration", "PROBABILITY_UNAVAILABLE", "Calibrated probability is unavailable; EV remains disabled", SafetyState.DEGRADED)]
        reasons = []
        try:
            samples = int(finite(evidence.get("oos_samples"), name="OOS samples", minimum=0))
            brier = finite(evidence.get("brier"), name="Brier score", minimum=0)
            ece = finite(evidence.get("ece"), name="ECE", minimum=0)
            log_loss = finite(evidence.get("log_loss"), name="log loss", minimum=0)
            baseline_log_loss = finite(
                evidence.get("baseline_log_loss"), name="baseline log loss", minimum=0,
            )
            log_loss_skill = finite(evidence.get("log_loss_skill"), name="log-loss skill")
            improvement_low = finite(
                evidence.get("log_loss_improvement_ci_low"),
                name="log-loss improvement lower bound",
            )
            validated = aware_datetime(evidence.get("validated_at"), name="validated_at")
            deterioration = finite(evidence.get("brier_deterioration", 0), name="Brier deterioration", minimum=0)
            age_days = ((aware_datetime(now or utcnow(), name="now") - validated).total_seconds() / 86400)
        except ValueError as exc:
            reasons.append(str(exc))
        else:
            p = self.policy
            if samples < int(p["minimum_samples"]): reasons.append("Insufficient chronological OOS samples")
            if age_days > float(p["maximum_age_days"]): reasons.append("Calibration evidence expired")
            if brier > float(p["maximum_brier"]): reasons.append("Brier score breached")
            if ece > float(p["maximum_ece"]): reasons.append("ECE breached")
            if log_loss >= baseline_log_loss: reasons.append("Log loss did not beat base rate")
            if log_loss_skill < float(p["minimum_log_loss_skill"]): reasons.append("Log-loss skill breached")
            if improvement_low <= float(p["minimum_log_loss_improvement_ci_low"]):
                reasons.append("Log-loss improvement is not statistically established")
            if deterioration > float(p["maximum_brier_deterioration"]): reasons.append("Calibration deterioration breached")
        with self._lock:
            self._consecutive = self._consecutive + 1 if reasons else 0
            breached = self._consecutive >= int(self.policy["consecutive_breaches_to_abstain"])
        if not reasons:
            return []
        state = SafetyState.NO_TRADE if breached else SafetyState.DEGRADED
        return [SafetyFinding("calibration", "CALIBRATION_DRIFT", "; ".join(reasons), state)]


class SLOMonitor:
    def __init__(self, policy: ResiliencePolicy, max_samples=10_000):
        self.policy = policy.section("slo")
        self._samples = deque(maxlen=max_samples)
        self._lock = threading.Lock()

    def observe(self, *, latency_ms, ok, at=None):
        sample = (aware_datetime(at or utcnow()), finite(latency_ms, name="latency", minimum=0), bool(ok))
        with self._lock:
            self._samples.append(sample)

    def evaluate(self, *, now=None):
        now = aware_datetime(now or utcnow())
        cutoff = now - dt.timedelta(minutes=float(self.policy["window_minutes"]))
        with self._lock:
            samples = [row for row in self._samples if row[0] >= cutoff]
        if not samples:
            return [SafetyFinding("slo", "NO_TELEMETRY", "No SLO samples exist in the active window", SafetyState.DEGRADED)]
        latencies = sorted(row[1] for row in samples)
        p95 = latencies[max(math.ceil(len(latencies) * 0.95) - 1, 0)]
        error_rate = sum(not row[2] for row in samples) / len(samples)
        target_error = max(1 - float(self.policy["availability_target"]), 1e-9)
        burn = error_rate / target_error
        findings = []
        if p95 > float(self.policy["maximum_p95_latency_ms"]):
            findings.append(SafetyFinding("slo", "LATENCY_SLO", f"p95 latency is {p95:.1f}ms", SafetyState.DEGRADED))
        if error_rate > float(self.policy["maximum_error_rate"]):
            state = SafetyState.NO_TRADE if burn >= float(self.policy["fast_burn_rate"]) else SafetyState.DEGRADED
            findings.append(SafetyFinding("slo", "ERROR_BUDGET_BURN", f"Error rate {error_rate:.3%}; burn {burn:.2f}x", state))
        return findings


class RuntimeAttestor:
    def evaluate(self, *, expected: Mapping, actual: Mapping, signature_valid=True):
        if not signature_valid:
            return [SafetyFinding("configuration", "SIGNATURE_INVALID", "Runtime attestation signature failed", SafetyState.EMERGENCY_STOP)]
        mismatches = [key for key, expected_value in expected.items() if actual.get(key) != expected_value]
        if mismatches:
            return [SafetyFinding("configuration", "CONFIG_DRIFT", "Mismatch: " + ", ".join(sorted(mismatches)), SafetyState.NO_TRADE)]
        return []


class SecretLifecycleMonitor:
    """Evaluates metadata only; secret values must never enter telemetry."""

    def __init__(self, policy: ResiliencePolicy):
        self.policy = policy.section("secrets")

    def evaluate(self, records: Sequence[Mapping], *, now=None):
        now = aware_datetime(now or utcnow())
        findings = []
        for record in records:
            name = str(record.get("name") or "unknown")
            if any(key in record for key in ("value", "secret", "token", "password")):
                findings.append(SafetyFinding("secrets", "SECRET_VALUE_EXPOSED", f"Secret metadata for {name} contains a forbidden value field", SafetyState.EMERGENCY_STOP))
                continue
            try:
                rotated = aware_datetime(record.get("rotated_at"), name=f"{name}.rotated_at")
                expires = aware_datetime(record.get("expires_at"), name=f"{name}.expires_at")
                age = (now - rotated).total_seconds() / 86400
                remaining = (expires - now).total_seconds() / 86400
            except ValueError as exc:
                findings.append(SafetyFinding("secrets", "SECRET_METADATA_INVALID", str(exc), SafetyState.NO_TRADE))
                continue
            if remaining <= 0:
                findings.append(SafetyFinding("secrets", "SECRET_EXPIRED", f"{name} is expired", SafetyState.NO_TRADE))
            elif remaining <= float(self.policy["warning_days_before_expiry"]):
                findings.append(SafetyFinding("secrets", "SECRET_EXPIRING", f"{name} expires in {remaining:.1f} days", SafetyState.DEGRADED))
            if age > float(self.policy["maximum_age_days"]):
                findings.append(SafetyFinding("secrets", "ROTATION_OVERDUE", f"{name} age is {age:.1f} days", SafetyState.DEGRADED))
        return findings


class ReleaseDecision:
    """Creates a deployment decision; the CI/CD adapter performs rollout/rollback."""

    @staticmethod
    def evaluate(*, canary_samples, previous_release, candidate_release):
        if not previous_release or not candidate_release or previous_release == candidate_release:
            return {"action": "BLOCK", "reason": "Distinct candidate and rollback release IDs are required"}
        rows = list(canary_samples or [])
        if len(rows) < 5:
            return {"action": "BLOCK", "reason": "At least five canary probes are required"}
        failures = sum(not bool(row.get("ok")) for row in rows)
        try:
            p95 = sorted(finite(row.get("latency_ms"), name="canary latency", minimum=0) for row in rows)[max(math.ceil(len(rows) * .95) - 1, 0)]
        except ValueError as exc:
            return {"action": "ROLLBACK", "reason": str(exc), "rollback_to": previous_release}
        if failures or p95 > 2500:
            return {"action": "ROLLBACK", "reason": f"failures={failures}, p95={p95:.1f}ms", "rollback_to": previous_release}
        return {"action": "PROMOTE", "reason": "Canary passed", "release": candidate_release,
                "rollback_to": previous_release}


class RetentionAuditGuard:
    def __init__(self, policy: ResiliencePolicy):
        self.policy = policy.section("retention")

    def evaluate(self, *, evidence_retention_days, log_retention_days, personal_data_retention_days,
                 ledger_verified, legal_hold_preserved=True):
        findings = []
        checks = {
            "evidence": (evidence_retention_days, self.policy["evidence_days"], "minimum"),
            "logs": (log_retention_days, self.policy["operational_log_days"], "minimum"),
            "personal_data": (personal_data_retention_days, self.policy["personal_data_days"], "maximum"),
        }
        for name, (value, threshold, direction) in checks.items():
            try:
                parsed = finite(value, name=f"{name} retention", minimum=0)
            except ValueError as exc:
                findings.append(SafetyFinding("retention", "RETENTION_INVALID", str(exc), SafetyState.READ_ONLY))
                continue
            breached = parsed < float(threshold) if direction == "minimum" else parsed > float(threshold)
            if breached:
                findings.append(SafetyFinding("retention", "RETENTION_DRIFT", f"{name} retention={parsed} days", SafetyState.READ_ONLY))
        if not ledger_verified or not legal_hold_preserved:
            findings.append(SafetyFinding("retention", "AUDIT_DURABILITY", "Ledger verification or legal-hold preservation failed", SafetyState.READ_ONLY))
        return findings


class ExecutionSurveillance:
    TERMINAL = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}
    TRANSITIONS = {
        "NEW": {"ACKNOWLEDGED", "REJECTED", "CANCELLED"},
        "ACKNOWLEDGED": {"PARTIAL", "FILLED", "CANCELLED", "REJECTED", "EXPIRED"},
        "PARTIAL": {"PARTIAL", "FILLED", "CANCELLED", "EXPIRED"},
    }

    def __init__(self, policy: ResiliencePolicy):
        self.policy = policy.section("execution")

    def evaluate(self, *, previous_status, status, ordered_quantity, cumulative_quantity,
                 expected_price=None, average_fill_price=None, partial_age_seconds=0):
        findings = []
        previous_status, status = str(previous_status).upper(), str(status).upper()
        if previous_status in self.TERMINAL or status not in self.TRANSITIONS.get(previous_status, set()):
            findings.append(SafetyFinding("execution", "INVALID_TRANSITION", f"{previous_status} -> {status}", SafetyState.READ_ONLY))
        try:
            ordered = finite(ordered_quantity, name="ordered quantity", minimum=0.0000001)
            cumulative = finite(cumulative_quantity, name="cumulative quantity", minimum=0, maximum=ordered)
            partial_age = finite(partial_age_seconds, name="partial fill age", minimum=0)
        except ValueError as exc:
            return findings + [SafetyFinding("execution", "INVALID_FILL", str(exc), SafetyState.READ_ONLY)]
        if status == "FILLED" and cumulative != ordered:
            findings.append(SafetyFinding("execution", "INCOMPLETE_FILL", "FILLED quantity differs from order quantity", SafetyState.READ_ONLY))
        if status == "PARTIAL" and partial_age > float(self.policy["maximum_partial_fill_age_seconds"]):
            findings.append(SafetyFinding("execution", "PARTIAL_FILL_STALE", f"Partial fill age is {partial_age:.1f}s", SafetyState.NO_TRADE))
        if expected_price is not None or average_fill_price is not None:
            try:
                expected = finite(expected_price, name="expected price", minimum=0.0000001)
                filled = finite(average_fill_price, name="average fill price", minimum=0.0000001)
                slippage = abs(filled - expected) / expected * 10_000
                if slippage > float(self.policy["maximum_slippage_bps"]):
                    findings.append(SafetyFinding("execution", "SLIPPAGE_BREACH", f"Slippage is {slippage:.2f} bps", SafetyState.NO_TRADE))
            except ValueError as exc:
                findings.append(SafetyFinding("execution", "INVALID_FILL_PRICE", str(exc), SafetyState.READ_ONLY))
        return findings


class OperationalGuard:
    def __init__(self, policy: ResiliencePolicy):
        self.policy = policy

    def outbox(self, stats: Mapping | None):
        if not stats:
            return [SafetyFinding("outbox", "OUTBOX_UNOBSERVED", "Outbox reconciliation has no telemetry", SafetyState.DEGRADED)]
        try:
            pending = int(finite(stats.get("pending"), name="pending outbox events", minimum=0))
            oldest = finite(stats.get("oldest_pending_seconds", 0), name="oldest pending age", minimum=0)
        except ValueError as exc:
            return [SafetyFinding("outbox", "OUTBOX_INVALID", str(exc), SafetyState.READ_ONLY)]
        p = self.policy.section("outbox")
        if pending > int(p["maximum_pending_events"]) or oldest > float(p["maximum_oldest_pending_seconds"]):
            return [SafetyFinding("outbox", "OUTBOX_BACKLOG", f"pending={pending}, oldest={oldest:.1f}s", SafetyState.READ_ONLY)]
        return []

    def capacity(self, sample: Mapping | None):
        if not sample:
            return [SafetyFinding("capacity", "CAPACITY_UNOBSERVED", "Capacity telemetry is not configured", SafetyState.DEGRADED)]
        p = self.policy.section("capacity")
        findings = []
        for key, threshold in (("cpu_fraction", p["maximum_cpu_fraction"]),
                               ("memory_fraction", p["maximum_memory_fraction"]),
                               ("db_pool_fraction", p["maximum_db_pool_fraction"])):
            try:
                value = finite(sample.get(key), name=key, minimum=0, maximum=1)
                if value > float(threshold):
                    findings.append(SafetyFinding("capacity", "RESOURCE_SATURATION", f"{key}={value:.3f}", SafetyState.DEGRADED))
            except ValueError as exc:
                findings.append(SafetyFinding("capacity", "CAPACITY_INVALID", str(exc), SafetyState.DEGRADED))
        try:
            queue = int(finite(sample.get("queue_depth"), name="queue depth", minimum=0))
            if queue > int(p["maximum_queue_depth"]):
                findings.append(SafetyFinding("capacity", "QUEUE_SATURATION", f"queue_depth={queue}", SafetyState.NO_TRADE))
        except ValueError as exc:
            findings.append(SafetyFinding("capacity", "CAPACITY_INVALID", str(exc), SafetyState.DEGRADED))
        return findings

    def recovery(self, result: Mapping | None, *, now=None):
        if not result:
            return [SafetyFinding("recovery", "DRILL_UNVERIFIED", "No recovery drill evidence is configured", SafetyState.DEGRADED)]
        reasons = []
        try:
            rpo = finite(result.get("rpo_minutes"), name="RPO", minimum=0)
            rto = finite(result.get("rto_minutes"), name="RTO", minimum=0)
            performed = aware_datetime(result.get("performed_at"), name="drill timestamp")
            age = (aware_datetime(now or utcnow()) - performed).total_seconds() / 86400
        except ValueError as exc:
            reasons.append(str(exc))
        else:
            p = self.policy.section("recovery")
            if rpo > float(p["maximum_rpo_minutes"]): reasons.append("RPO breached")
            if rto > float(p["maximum_rto_minutes"]): reasons.append("RTO breached")
            if age > float(p["drill_maximum_age_days"]): reasons.append("Recovery drill expired")
            if not result.get("ledger_verified"): reasons.append("Restored ledger was not verified")
            if not result.get("runtime_role_verified"): reasons.append("Restricted runtime role was not verified")
        return [SafetyFinding("recovery", "RECOVERY_DRILL_FAILED", "; ".join(reasons), SafetyState.READ_ONLY)] if reasons else []


class ModelPromotionGate:
    """Pure statistical gate; the registry separately verifies signatures and approvals."""

    def evaluate(self, package: Mapping):
        required_truthy = (
            "point_in_time_verified", "untouched_holdout", "costs_applied",
            "rollback_model_available",
        )
        failures = [name for name in required_truthy if not package.get(name)]
        try:
            samples = int(finite(package.get("oos_samples"), name="promotion OOS samples", minimum=0))
            if samples < 500: failures.append("oos_samples")
            regimes = int(finite(package.get("regimes_tested"), name="regimes tested", minimum=0))
            if regimes < 3: failures.append("regimes_tested")
        except ValueError as exc:
            failures.append(str(exc))
        if failures:
            return {"status": "REJECTED", "failures": sorted(set(failures)), "promotion_allowed": False}
        manifest = {key: package[key] for key in sorted(package)}
        return {"status": "APPROVED", "failures": [], "promotion_allowed": True,
                "attestation_hash": canonical_hash(manifest)}


class ResilienceControlPlane:
    """Unifies P0/P1/P2 findings into one enforceable safety decision."""

    def __init__(self, policy=None):
        self.policy = policy or ResiliencePolicy.load()
        self.state_machine = SafetyStateMachine(self.policy)
        self.market_data = MarketDataSupervisor(self.policy)
        self.clock = ClockSessionGuard(self.policy)
        self.calibration = CalibrationDriftMonitor(self.policy)
        self.slo = SLOMonitor(self.policy)
        self.attestor = RuntimeAttestor()
        self.secrets = SecretLifecycleMonitor(self.policy)
        self.release = ReleaseDecision()
        self.retention = RetentionAuditGuard(self.policy)
        self.execution = ExecutionSurveillance(self.policy)
        self.operations = OperationalGuard(self.policy)
        self.promotion = ModelPromotionGate()

    def evaluate_recommendation(self, *, price, quote_at, received_at=None, quote_age_seconds=None,
                                provider_available=True, exchange_open=True, calibration_evidence=None,
                                secondary_quote=None, tick_size=None, heartbeat_age_seconds=0,
                                ntp_offset_seconds=0, runtime_expected=None, runtime_actual=None,
                                outbox_stats=None, capacity_sample=None, authorized_recovery=False,
                                correlation_id=None, control_findings=None):
        _CORRELATION_ID.set(str(correlation_id or new_correlation_id()))
        started = time.perf_counter()
        now = utcnow()
        pre_findings = []
        if quote_age_seconds is not None:
            try:
                age = finite(quote_age_seconds, name="quote age", minimum=0)
                quote_at = now - dt.timedelta(seconds=age)
            except ValueError as exc:
                pre_findings.append(SafetyFinding("market_data", "INVALID_QUOTE_AGE", str(exc), SafetyState.NO_TRADE))
        primary = QuoteObservation(
            price=price, exchange_at=quote_at, received_at=received_at or now, source="primary"
        ) if provider_available else None
        secondary = None
        if isinstance(secondary_quote, Mapping):
            secondary = QuoteObservation(
                price=secondary_quote.get("price"), exchange_at=secondary_quote.get("exchange_at"),
                received_at=secondary_quote.get("received_at") or now,
                source=str(secondary_quote.get("source") or "secondary"),
                bid=secondary_quote.get("bid"), ask=secondary_quote.get("ask"),
                sequence=secondary_quote.get("sequence"),
            )
        findings = list(pre_findings)
        for item in control_findings or ():
            if not isinstance(item, SafetyFinding):
                raise TypeError("control_findings must contain SafetyFinding values")
            findings.append(item)
        findings.extend(self.market_data.evaluate(
            primary, secondary=secondary, now=now, tick_size=tick_size,
            heartbeat_age_seconds=heartbeat_age_seconds, provider_available=provider_available,
        ))
        findings.extend(self.clock.evaluate(now=now, exchange_open=exchange_open,
                                            ntp_offset_seconds=ntp_offset_seconds))
        findings.extend(self.calibration.evaluate(calibration_evidence, now=now))
        if runtime_expected is not None:
            findings.extend(self.attestor.evaluate(expected=runtime_expected, actual=runtime_actual or {}))
        if outbox_stats is not None:
            findings.extend(self.operations.outbox(outbox_stats))
        if capacity_sample is not None:
            findings.extend(self.operations.capacity(capacity_sample))
        self.slo.observe(latency_ms=(time.perf_counter() - started) * 1000.0, ok=not any(
            item.state >= SafetyState.NO_TRADE for item in findings
        ), at=now)
        findings.extend(self.slo.evaluate(now=now))
        decision = self.state_machine.evaluate(findings, authorized_recovery=authorized_recovery)
        try:
            from observability import get_registry
            get_registry().record(
                "governance", "recommendation_gate",
                time.perf_counter() - started,
                ok=decision.state in {SafetyState.NORMAL, SafetyState.DEGRADED},
                status=decision.state.name, correlation_id=_CORRELATION_ID.get(),
                count=max(len(findings), 1),
            )
        except Exception:
            pass
        return decision

    def evaluate_operations(self, *, runtime_expected=None, runtime_actual=None,
                            signature_valid=True, secret_records=None, outbox_stats=None,
                            capacity_sample=None, recovery_result=None, retention=None,
                            execution_event=None, authorized_recovery=False,
                            correlation_id=None):
        """Evaluate non-quote P0/P1/P2 controls through the same safety state machine."""
        _CORRELATION_ID.set(str(correlation_id or new_correlation_id()))
        findings = []
        if runtime_expected is not None:
            findings.extend(self.attestor.evaluate(
                expected=runtime_expected, actual=runtime_actual or {}, signature_valid=signature_valid,
            ))
        if secret_records is not None:
            findings.extend(self.secrets.evaluate(secret_records))
        if outbox_stats is not None:
            findings.extend(self.operations.outbox(outbox_stats))
        if capacity_sample is not None:
            findings.extend(self.operations.capacity(capacity_sample))
        if recovery_result is not None:
            findings.extend(self.operations.recovery(recovery_result))
        if retention is not None:
            findings.extend(self.retention.evaluate(**dict(retention)))
        if execution_event is not None:
            findings.extend(self.execution.evaluate(**dict(execution_event)))
        return self.state_machine.evaluate(findings, authorized_recovery=authorized_recovery)


_CONTROL_PLANE = None
_CONTROL_PLANE_LOCK = threading.Lock()


def get_resilience_control_plane(policy_path=None):
    global _CONTROL_PLANE
    with _CONTROL_PLANE_LOCK:
        if _CONTROL_PLANE is None:
            _CONTROL_PLANE = ResilienceControlPlane(ResiliencePolicy.load(policy_path))
        return _CONTROL_PLANE


def hmac_compare(left: str, right: str) -> bool:
    """Constant-time comparison without introducing a policy-signing secret."""
    import hmac
    return hmac.compare_digest(str(left), str(right))
