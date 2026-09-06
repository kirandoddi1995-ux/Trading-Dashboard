import datetime as dt
import json

import pytest

from artifact_security import ApprovalAuthority, ArtifactSigner
from production_readiness import readiness_report, runtime_controls, runtime_readiness_findings
from resilience_control_plane import SafetyState
from verify_promotion_request import verify_request


def complete_environment(now):
    return {
        "DATABASE_URL": "postgresql://quant_app_runtime:secret@db.example.com:5432/postgres",
        "MODEL_ARTIFACT_SIGNING_KEY": "m" * 32,
        "RUNTIME_EVIDENCE_SIGNING_KEY": "r" * 32,
        "MODEL_APPROVER_KEYS_JSON": json.dumps({"risk": "a" * 32, "deploy": "b" * 32}),
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.example.com",
        "SECONDARY_QUOTE_PROVIDER_URL": "https://quotes.example.com",
        "DEPLOYMENT_ROLLBACK_TARGET": "streamlit-revision:previous",
        "SECRETS_MANAGER_URI": "vault://quant-production",
        "NTP_MONITOR_ENDPOINT": "https://clock.example.com",
        "RECOVERY_DRILL_AT": (now - dt.timedelta(days=1)).isoformat(),
        "RECOVERY_DRILL_RPO_MINUTES": "10",
        "RECOVERY_DRILL_RTO_MINUTES": "45",
        "RECOVERY_DRILL_LEDGER_VERIFIED": "true",
        "RECOVERY_DRILL_RUNTIME_ROLE_VERIFIED": "true",
        "PRODUCTION_ENVIRONMENT_PROTECTED": "true",
    }


def test_complete_external_attestation_passes_without_exposing_values(tmp_path):
    now = dt.datetime(2026, 9, 6, tzinfo=dt.timezone.utc)
    controls = runtime_controls(complete_environment(now), now=now)
    assert all(control.configured for control in controls)
    assert all("secret@" not in control.detail for control in controls)


def test_owner_database_and_stale_recovery_drill_fail_closed():
    now = dt.datetime(2026, 9, 6, tzinfo=dt.timezone.utc)
    env = complete_environment(now)
    env["DATABASE_URL"] = "postgresql://postgres:secret@db.example.com/postgres"
    env["RECOVERY_DRILL_AT"] = (now - dt.timedelta(days=91)).isoformat()
    findings = runtime_readiness_findings(env, now=now)
    assert any(finding.code == "EXTERNAL_RESTRICTED_DATABASE_ROLE" for finding in findings)
    assert any(finding.state == SafetyState.READ_ONLY for finding in findings)


def test_repository_readiness_requires_promotion_workflow_and_runbook():
    report = readiness_report(".", include_external=False)
    assert report["ready"]
    assert report["repository_code_complete"]


def test_protected_promotion_request_requires_real_artifact_and_two_approval_signatures(tmp_path):
    signer = ArtifactSigner(b"m" * 32, key_id="production")
    artifact = signer.sign({"model_id": "m1", "version": "1"})
    authority = ApprovalAuthority({"risk": b"a" * 32, "deploy": b"b" * 32})
    approvals = [
        authority.issue(approver="risk", role="model-risk",
                        artifact_hash=artifact["artifact_hash"], action="PROMOTE"),
        authority.issue(approver="deploy", role="deployment",
                        artifact_hash=artifact["artifact_hash"], action="PROMOTE"),
    ]
    path = tmp_path / "request.json"
    path.write_text(json.dumps({"action": "PROMOTE", "artifact": artifact,
                                "approvals": approvals}), encoding="utf-8")
    env = {
        "MODEL_ARTIFACT_SIGNING_KEY": "m" * 32,
        "MODEL_ARTIFACT_SIGNING_KEY_ID": "production",
        "MODEL_APPROVER_KEYS_JSON": json.dumps({"risk": "a" * 32, "deploy": "b" * 32}),
    }
    assert verify_request(path, env)["authorized"]
    tampered = {**artifact, "version": "2"}
    path.write_text(json.dumps({"action": "PROMOTE", "artifact": tampered,
                                "approvals": approvals}), encoding="utf-8")
    with pytest.raises(ValueError, match="signature"):
        verify_request(path, env)
