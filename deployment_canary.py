"""Credential-free release canaries; live provider checks are explicit opt-in."""
from __future__ import annotations
import ast, hashlib, json, sqlite3, zipfile
from pathlib import Path


def run_canaries(root):
    root=Path(root); checks={}
    app=root/"app.py"; ast.parse(app.read_text(encoding="utf-8")); checks["app_parses"]=True
    for module in ("provider_contracts.py","quantitative_services.py","iv_surface.py","model_registry.py","mf_archive.py",
                   "production_repository.py","amfi_ingestion.py","scheduled_collector.py","prediction_validation.py",
                   "evidence_ledger.py","quant_foundation.py","deployment_security.py","environment_preflight.py",
                   "resilience_control_plane.py","resilience_acceptance.py"):
        ast.parse((root/module).read_text(encoding="utf-8")); checks[f"parses:{module}"]=True
    db=sqlite3.connect(":memory:"); checks["sqlite_json"]=db.execute("SELECT json_valid('{}')").fetchone()[0]==1; db.close()
    archives=sorted(root.glob("release-*.zip"),key=lambda p:p.stat().st_mtime,reverse=True)
    if archives:
        with zipfile.ZipFile(archives[0]) as z: checks["latest_zip_integrity"]=z.testzip() is None
    ignored=(root/".gitignore").read_text(encoding="utf-8") if (root/".gitignore").exists() else ""
    checks["secrets_excluded"]=".streamlit/secrets.toml" in ignored
    example=(root/".streamlit"/"secrets.example.toml").read_text(encoding="utf-8")
    checks["durable_secret_documented"]=("DATABASE_URL" in example and "UPSTOX_ANALYTICS_TOKEN" in example
                                          and "EVIDENCE_LEDGER_SIGNING_KEY" in example
                                          and "AUTH_ALLOWED_EMAILS" in example and "[auth]" in example)
    app_source=app.read_text(encoding="utf-8")
    checks["auth_precedes_services"]=(app_source.index("require_streamlit_auth(st)")
                                       < app_source.index("OBSERVABILITY = observability.get_registry()")
                                       < app_source.index("\n_ensure_cache_schema()\n")
                                       < app_source.index("MARKET_DATA_GATEWAY =")
                                       < app_source.index("TECHNICAL_FEATURE_STORE ="))
    workflow=(root/".github"/"workflows"/"scheduled-collector.yml").read_text(encoding="utf-8")
    checks["scheduled_collector_present"]=("scheduled_collector.py" in workflow
                                            and "secrets.DATABASE_URL" in workflow
                                            and "secrets.DATABASE_MIGRATION_URL" in workflow)
    quality=(root/".github"/"workflows"/"quality.yml").read_text(encoding="utf-8")
    checks["dependency_preflight"]="environment_preflight.py --strict" in quality
    policy = root / "resilience_policy.json"
    approved = (root / "resilience_policy.sha256").read_text(encoding="ascii").strip().lower()
    checks["resilience_policy_integrity"] = hashlib.sha256(policy.read_bytes()).hexdigest() == approved
    resilience_workflow = (root/".github"/"workflows"/"resilience.yml").read_text(encoding="utf-8")
    checks["resilience_gate_present"] = ("resilience_acceptance.py" in resilience_workflow
                                          and "test_resilience_control_plane.py" in resilience_workflow)
    checks["live_resilience_gate_wired"] = ("RESILIENCE_CONTROL_PLANE.evaluate_recommendation" in app_source
                                             and '"resilience": resilience_public' in app_source
                                             and 'not resilience.allow_new_trades' in app_source)
    return {"ok":all(checks.values()),"checks":checks}


if __name__ == "__main__":
    result=run_canaries(Path(__file__).resolve().parent); print(json.dumps(result,indent=2)); raise SystemExit(0 if result["ok"] else 1)
