"""Machine-enforced boundary between repository controls and external production setup."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import urllib.parse
from dataclasses import asdict, dataclass
from typing import Mapping

from resilience_control_plane import SafetyFinding, SafetyState


UTC = dt.timezone.utc


@dataclass(frozen=True)
class ReadinessControl:
    name: str
    configured: bool
    code_complete: bool
    external_action_required: bool
    detail: str
    state: str


def _secret_length_ok(value, minimum=32):
    return len(str(value or "").encode("utf-8")) >= int(minimum)


def _runtime_role_url_ok(value):
    try:
        parsed = urllib.parse.urlsplit(str(value or ""))
        username = urllib.parse.unquote(parsed.username or "").casefold()
        return (parsed.scheme in {"postgres", "postgresql"} and bool(parsed.hostname)
                and bool(parsed.password) and username not in {
                    "postgres", "supabase_admin", "dashboard_user", "service_role",
                })
    except Exception:
        return False


def _approver_keys_ok(value):
    try:
        keys = json.loads(str(value or "{}"))
        return isinstance(keys, dict) and len(keys) >= 2 and all(
            str(identity).strip() and _secret_length_ok(key) for identity, key in keys.items()
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def _recovery_drill_ok(environ: Mapping[str, str], now: dt.datetime):
    try:
        performed = dt.datetime.fromisoformat(str(environ.get("RECOVERY_DRILL_AT", "")).replace("Z", "+00:00"))
        if performed.tzinfo is None:
            return False
        age = now - performed.astimezone(UTC)
        return (
            dt.timedelta(0) <= age <= dt.timedelta(days=90)
            and float(environ.get("RECOVERY_DRILL_RPO_MINUTES", "nan")) <= 15
            and float(environ.get("RECOVERY_DRILL_RTO_MINUTES", "nan")) <= 60
            and str(environ.get("RECOVERY_DRILL_LEDGER_VERIFIED", "")).casefold() == "true"
            and str(environ.get("RECOVERY_DRILL_RUNTIME_ROLE_VERIFIED", "")).casefold() == "true"
        )
    except (TypeError, ValueError, OverflowError):
        return False


def runtime_controls(environ=None, *, now=None) -> list[ReadinessControl]:
    environ = environ or os.environ
    now = now or dt.datetime.now(UTC)
    checks = [
        ("restricted_database_role", _runtime_role_url_ok(environ.get("DATABASE_URL")),
         "Set DATABASE_URL to the non-owner quant_app_runtime connection", "NO_TRADE"),
        ("model_artifact_signing", _secret_length_ok(environ.get("MODEL_ARTIFACT_SIGNING_KEY")),
         "Provision a >=32-byte model-artifact key in the managed secret store", "NO_TRADE"),
        ("runtime_evidence_signing", _secret_length_ok(environ.get("RUNTIME_EVIDENCE_SIGNING_KEY")),
         "Provision a separate >=32-byte runtime-evidence key", "NO_TRADE"),
        ("independent_model_approvers", _approver_keys_ok(environ.get("MODEL_APPROVER_KEYS_JSON")),
         "Configure two or more independent approver identities and keys", "NO_TRADE"),
        ("telemetry_export", bool(str(environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")).strip()),
         "Connect the bounded telemetry exporter and alert routing", "DEGRADED"),
        ("independent_quote_source", bool(str(environ.get("SECONDARY_QUOTE_PROVIDER_URL", "")).strip()),
         "Configure a licensed independent NSE quote source", "NO_TRADE"),
        ("automated_rollback", bool(str(environ.get("DEPLOYMENT_ROLLBACK_TARGET", "")).strip()),
         "Connect rollback decisions to an immutable previous deployment", "DEGRADED"),
        ("managed_secrets", bool(str(environ.get("SECRETS_MANAGER_URI", "")).strip()),
         "Configure managed rotation, revocation, and access audit logging", "NO_TRADE"),
        ("clock_monitor", bool(str(environ.get("NTP_MONITOR_ENDPOINT", "")).strip()),
         "Configure measured NTP/session-clock monitoring", "NO_TRADE"),
        ("recovery_drill", _recovery_drill_ok(environ, now),
         "Complete and attest a <=90-day isolated PITR drill meeting RPO/RTO", "READ_ONLY"),
        ("protected_promotion_environment",
         str(environ.get("PRODUCTION_ENVIRONMENT_PROTECTED", "")).casefold() == "true",
         "Protect the GitHub production environment with independent reviewers", "NO_TRADE"),
    ]
    return [ReadinessControl(
        name=name, configured=bool(ok), code_complete=True,
        external_action_required=not bool(ok), detail=("Configured" if ok else detail), state=state,
    ) for name, ok, detail, state in checks]


def runtime_readiness_findings(environ=None, *, now=None) -> list[SafetyFinding]:
    state = {
        "DEGRADED": SafetyState.DEGRADED,
        "NO_TRADE": SafetyState.NO_TRADE,
        "READ_ONLY": SafetyState.READ_ONLY,
        "EMERGENCY_STOP": SafetyState.EMERGENCY_STOP,
    }
    return [SafetyFinding(
        "production_readiness", f"EXTERNAL_{control.name.upper()}",
        control.detail, state[control.state],
    ) for control in runtime_controls(environ, now=now) if not control.configured]


def repository_controls(root) -> list[ReadinessControl]:
    root = pathlib.Path(root)
    required = {
        "resilience_policy": root / "resilience_policy.json",
        "policy_digest": root / "resilience_policy.sha256",
        "quality_workflow": root / ".github" / "workflows" / "quality.yml",
        "resilience_workflow": root / ".github" / "workflows" / "resilience.yml",
        "promotion_workflow": root / ".github" / "workflows" / "production-promotion.yml",
        "operator_runbook": root / "PRODUCTION_EXTERNAL_ACTIONS.md",
    }
    controls = []
    for name, path in required.items():
        controls.append(ReadinessControl(
            name=name, configured=path.is_file(), code_complete=path.is_file(),
            external_action_required=False, detail=str(path.name),
            state="PASS" if path.is_file() else "NO_TRADE",
        ))
    policy, digest = required["resilience_policy"], required["policy_digest"]
    digest_ok = False
    if policy.is_file() and digest.is_file():
        expected = digest.read_text(encoding="utf-8").strip().split()[0]
        digest_ok = hashlib.sha256(policy.read_bytes()).hexdigest() == expected
    controls.append(ReadinessControl(
        "policy_hash_integrity", digest_ok, digest_ok, False,
        "Policy bytes match the committed SHA-256" if digest_ok else "Policy digest mismatch",
        "PASS" if digest_ok else "EMERGENCY_STOP",
    ))
    return controls


def readiness_report(root, *, include_external=True, environ=None, now=None):
    controls = repository_controls(root)
    if include_external:
        controls.extend(runtime_controls(environ, now=now))
    return {
        "ready": all(control.configured for control in controls),
        "repository_code_complete": all(control.code_complete for control in controls),
        "controls": [asdict(control) for control in controls],
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-only", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parent))
    args = parser.parse_args(argv)
    report = readiness_report(args.root, include_external=not args.repository_only)
    print(json.dumps(report, indent=2))
    return 1 if args.strict and not report["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
