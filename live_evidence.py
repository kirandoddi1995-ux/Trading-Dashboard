"""Versioned evidence contract for every live recommendation path.

The contract contains references to real evidence only.  It deliberately does
not manufacture timestamps, probabilities, histories, or promotion state when
they are missing.  Consumers must treat every compatibility failure as a
fail-closed NO_TRADE decision.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


UTC = dt.timezone.utc
LIVE_EVIDENCE_CONTRACT_VERSION = "live-evidence-v1"


class EvidenceTier(str, Enum):
    OBSERVATION = "OBSERVATION"
    DEVELOPING = "DEVELOPING"
    VALIDATED = "VALIDATED"
    ESTABLISHED_99 = "99%-ESTABLISHED"

    @property
    def permits_production_probability(self) -> bool:
        return self in {EvidenceTier.VALIDATED, EvidenceTier.ESTABLISHED_99}


def aware_utc(value: Any, *, name: str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a timezone-aware datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def feature_schema_digest(feature_lineage: Mapping[str, Mapping[str, Any]]) -> str:
    """Hash feature names and declared definitions, never their live values."""
    schema = []
    for name, raw in sorted(dict(feature_lineage or {}).items()):
        row = dict(raw or {})
        schema.append({
            "name": str(name),
            "definition_version": str(row.get("definition_version") or ""),
            "dtype": str(row.get("dtype") or type(row.get("value")).__name__),
        })
    return hashlib.sha256(
        json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def provider_timestamp(value: Any) -> dt.datetime | None:
    """Parse an exchange/provider timestamp without assuming a timezone.

    Numeric values may be seconds, milliseconds, microseconds, or nanoseconds
    since the Unix epoch. Naive text timestamps are rejected because assigning
    a timezone would fabricate chronology.
    """
    if value is None or value == "":
        return None
    numeric_text = isinstance(value, str) and value.strip().replace(".", "", 1).isdigit()
    if isinstance(value, (int, float)) or numeric_text:
        try:
            epoch = float(value)
            if not math.isfinite(epoch) or epoch <= 0:
                return None
            magnitude = abs(epoch)
            if magnitude >= 1e18:
                epoch /= 1e9
            elif magnitude >= 1e15:
                epoch /= 1e6
            elif magnitude >= 1e12:
                epoch /= 1e3
            return dt.datetime.fromtimestamp(epoch, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return aware_utc(value, name="provider timestamp")
    except ValueError:
        return None


def quote_evidence_times(quote: Mapping[str, Any] | None) -> tuple[dt.datetime | None, dt.datetime | None]:
    """Return independently represented exchange and receive timestamps."""
    row = dict(quote or {})
    observed = None
    for key in ("last_trade_time", "exchange_timestamp", "exchange_at", "quote_at"):
        observed = provider_timestamp(row.get(key))
        if observed is not None:
            break
    received = None
    for key in ("_received_at", "_ts", "received_at"):
        received = provider_timestamp(row.get(key))
        if received is not None:
            break
    if observed is None or received is None:
        return observed, received
    if received + dt.timedelta(seconds=2) < observed:
        return None, received
    return observed, received


def timestamped_feature_lineage(
    values: Mapping[str, Any],
    *,
    source: str,
    available_at: Any,
    effective_at: Any | None = None,
    definition_version: str,
    maximum_age_seconds: float,
) -> dict[str, dict[str, Any]]:
    """Attach one proven dependency timestamp to already-computed features."""
    available = aware_utc(available_at, name="feature available_at")
    effective = aware_utc(effective_at or available, name="feature effective_at")
    if effective > available:
        raise ValueError("feature effective_at cannot be after available_at")
    if not str(source or "").strip() or not str(definition_version or "").strip():
        raise ValueError("feature source and definition_version are required")
    maximum_age = float(maximum_age_seconds)
    if not math.isfinite(maximum_age) or maximum_age < 0:
        raise ValueError("maximum_age_seconds must be finite and non-negative")
    lineage = {}
    for name, value in dict(values or {}).items():
        lineage[str(name)] = {
            "value": value,
            "source": str(source),
            "available_at": available.isoformat(),
            "effective_at": effective.isoformat(),
            "definition_version": str(definition_version),
            "dtype": type(value).__name__,
            "maximum_age_seconds": maximum_age,
        }
    return lineage


@dataclass(frozen=True)
class LiveEvidenceContext:
    strategy_id: str
    asset_class: str
    target_version: str
    horizon_sessions: int
    instrument: str
    decision_at: dt.datetime
    feature_schema_hash: str

    def __post_init__(self) -> None:
        for name in ("strategy_id", "asset_class", "target_version", "instrument", "feature_schema_hash"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} is required")
        if int(self.horizon_sessions) <= 0:
            raise ValueError("horizon_sessions must be positive")
        object.__setattr__(self, "horizon_sessions", int(self.horizon_sessions))
        object.__setattr__(self, "decision_at", aware_utc(self.decision_at, name="decision_at"))

    def compatibility_fields(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "asset_class": self.asset_class,
            "target_version": self.target_version,
            "horizon_sessions": self.horizon_sessions,
            "feature_schema_hash": self.feature_schema_hash,
        }


@dataclass(frozen=True)
class LiveEvidenceBundle:
    context: LiveEvidenceContext
    tier: EvidenceTier = EvidenceTier.OBSERVATION
    quote_observed_at: dt.datetime | None = None
    quote_received_at: dt.datetime | None = None
    quote_source: str = ""
    feature_lineage: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    universe_observed_at: dt.datetime | None = None
    universe_effective_at: dt.datetime | None = None
    model_predictions: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    model_weights: Mapping[str, float] = field(default_factory=dict)
    calibration_evidence: Mapping[str, Any] | None = None
    conformal_evidence: Mapping[str, Any] | None = None
    fill_evidence: Mapping[str, Any] | None = None
    portfolio_returns: Any = None
    portfolio_weights: Mapping[str, float] = field(default_factory=dict)
    stress_scenarios: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    correctness_evidence: Mapping[str, Any] | None = None
    ledger_status: Mapping[str, Any] | None = None
    contract_version: str = LIVE_EVIDENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != LIVE_EVIDENCE_CONTRACT_VERSION:
            raise ValueError(f"Unsupported live evidence contract: {self.contract_version}")
        if not isinstance(self.tier, EvidenceTier):
            object.__setattr__(self, "tier", EvidenceTier(str(self.tier).upper()))
        for name in ("quote_observed_at", "quote_received_at", "universe_observed_at", "universe_effective_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, aware_utc(value, name=name))

    @property
    def quote_age_seconds(self) -> float | None:
        if self.quote_observed_at is None or self.quote_received_at is None:
            return None
        if self.quote_received_at < self.quote_observed_at:
            return None
        age = (self.context.decision_at - self.quote_observed_at).total_seconds()
        return age if math.isfinite(age) and age >= 0 else None

    def compatibility_failures(self) -> list[str]:
        failures: list[str] = []
        expected = self.context.compatibility_fields()
        if not self.tier.permits_production_probability:
            failures.append(f"Evidence tier {self.tier.value} is not production eligible")
        if self.quote_age_seconds is None:
            failures.append("Measured quote timestamps are missing or invalid")
        if not str(self.quote_source or "").strip():
            failures.append("Quote source is missing")
        if not self.feature_lineage:
            failures.append("Point-in-time feature lineage is missing")
        elif feature_schema_digest(self.feature_lineage) != self.context.feature_schema_hash:
            failures.append("Feature lineage does not match the declared schema hash")
        if self.universe_observed_at is None or self.universe_effective_at is None:
            failures.append("Point-in-time universe lineage is missing")
        for package_name, package in (
            ("calibration", self.calibration_evidence),
            ("conformal", self.conformal_evidence),
            ("fill", self.fill_evidence),
        ):
            if not package:
                failures.append(f"{package_name.capitalize()} evidence is unavailable")
                continue
            for key, value in expected.items():
                if str(package.get(key, "")) != str(value):
                    failures.append(f"{package_name.capitalize()} evidence context mismatch: {key}")
        if not self.model_predictions:
            failures.append("Promoted model prediction evidence is unavailable")
        if not self.portfolio_weights:
            failures.append("Proposed portfolio weights are unavailable")
        if self.portfolio_returns is None:
            failures.append("Portfolio return histories are unavailable")
        if not self.stress_scenarios:
            failures.append("Portfolio stress scenarios are unavailable")
        return sorted(set(failures))

    def public_summary(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "tier": self.tier.value,
            "context": {
                **self.context.compatibility_fields(),
                "instrument": self.context.instrument,
                "decision_at": self.context.decision_at.isoformat(),
            },
            "quote_age_seconds": self.quote_age_seconds,
            "quote_source": self.quote_source,
            "feature_count": len(self.feature_lineage),
            "model_count": len(self.model_predictions),
            "has_calibration": bool(self.calibration_evidence),
            "has_conformal": bool(self.conformal_evidence),
            "has_fill_model": bool(self.fill_evidence),
            "has_portfolio_history": self.portfolio_returns is not None,
            "compatibility_failures": self.compatibility_failures(),
        }


def unavailable_bundle(
    *,
    strategy_id: str,
    asset_class: str,
    target_version: str,
    horizon_sessions: int,
    instrument: str,
    decision_at: dt.datetime,
    feature_lineage: Mapping[str, Mapping[str, Any]] | None = None,
    quote_observed_at: dt.datetime | None = None,
    quote_received_at: dt.datetime | None = None,
    quote_source: str = "",
    universe_observed_at: dt.datetime | None = None,
    universe_effective_at: dt.datetime | None = None,
) -> LiveEvidenceBundle:
    """Construct an explicit non-production bundle without inventing evidence."""
    lineage = dict(feature_lineage or {})
    return LiveEvidenceBundle(
        context=LiveEvidenceContext(
            strategy_id=strategy_id,
            asset_class=asset_class,
            target_version=target_version,
            horizon_sessions=horizon_sessions,
            instrument=instrument,
            decision_at=decision_at,
            feature_schema_hash=feature_schema_digest(lineage),
        ),
        tier=EvidenceTier.OBSERVATION,
        quote_observed_at=quote_observed_at,
        quote_received_at=quote_received_at,
        quote_source=quote_source,
        feature_lineage=lineage,
        universe_observed_at=universe_observed_at,
        universe_effective_at=universe_effective_at,
    )
