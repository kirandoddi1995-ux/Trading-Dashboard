"""Create a deployment archive from an explicit, credential-free allowlist."""
import hashlib
import json
from pathlib import Path
import zipfile
from deployment_canary import run_canaries


ROOT = Path(__file__).resolve().parent
RUNTIME = ['app.py', 'app_runtime.py', 'scan_jobs.py', 'reliable_charts.py',
           'technical_indicators.py', 'mf_research.py', 'observability.py',
           'market_data_gateway.py', 'feature_store.py', 'smc_analysis.py',
           'point_in_time.py', 'prediction_validation.py',
           'provider_contracts.py', 'quantitative_services.py', 'iv_surface.py',
           'model_registry.py', 'mf_archive.py', 'risk_engine.py', 'deployment_canary.py',
           'production_repository.py', 'amfi_ingestion.py', 'scheduled_collector.py',
           'trade_contracts.py', 'evidence_ledger.py', 'quant_foundation.py',
           'deployment_security.py', 'environment_preflight.py',
           'resilience_control_plane.py', 'resilience_acceptance.py',
           'continuous_evolution.py', 'live_evidence.py', 'live_governance.py',
           'decision_evidence.py', 'scanner_funnel.py', 'prospective_collection.py',
           'calibration_artifacts.py', 'artifact_security.py',
           'runtime_evidence_store.py', 'equity_runtime_evidence.py',
           'strategy_validation.py', 'evidence_tiers.py',
           'production_readiness.py', 'verify_promotion_request.py',
           'managed_secrets.py', 'secondary_quote_provider.py', 'recovery_drill.py',
           'research_features.py', 'model_training_pipeline.py',
           'resilience_policy.json', 'resilience_policy.sha256',
           'requirements.txt', 'constraints.txt']
FILES = RUNTIME + ['.gitignore', '.streamlit/secrets.example.toml', 'PRODUCTION_GUIDE.md',
                   'RESILIENCE_IMPLEMENTATION.md', 'RESILIENCE_RUNBOOK.md',
                   'CONTINUOUS_EVOLUTION_IMPLEMENTATION.md',
                   'FIX_VERIFICATION_2026-08-31.md', 'provider_smoke.py', 'package_release.py',
                   'database_runtime_role.sql.example', 'bootstrap_clean_environment.ps1',
                   'tests/test_regressions.py', 'tests/test_mf_research.py', 'tests/test_audit_fixes.py',
                   'tests/test_performance_foundation.py', 'tests/test_prediction_validation.py',
                   'tests/test_remaining_upgrades.py', 'tests/test_production_data_pipeline.py',
                   'tests/test_production_repository_dbapi.py',
                   'tests/test_trade_contracts.py',
                   'tests/test_quant_foundation.py',
                   'tests/test_quant_governance_adversarial.py',
                   'tests/test_deployment_hardening.py',
                   'tests/test_resilience_control_plane.py',
                   'tests/test_continuous_evolution.py',
                   'tests/test_live_evidence.py', 'tests/test_calibration_artifacts.py',
                   'tests/test_artifact_security.py', 'tests/test_runtime_evidence_store.py',
                   'tests/test_equity_runtime_evidence.py', 'tests/test_strategy_validation.py',
                   'tests/test_evidence_tiers.py', 'tests/test_production_readiness.py',
                   'tests/test_decision_evidence.py', 'tests/test_prospective_collection.py',
                   'tests/test_phase3_reliability.py', 'tests/test_research_features.py',
                   'tests/test_model_training_pipeline.py',
                   '.github/workflows/quality.yml', '.github/workflows/scheduled-collector.yml',
                   '.github/workflows/resilience.yml', '.github/workflows/production-promotion.yml',
                   '.github/workflows/production-rollback.yml',
                   '.github/workflows/recovery-drill.yml',
                   '.github/workflows/model-training-smoke.yml',
                   'PRODUCTION_EXTERNAL_ACTIONS.md']


def package():
    canaries = run_canaries(ROOT)
    if not canaries['ok']:
        raise RuntimeError(f"Release canaries failed: {canaries['checks']}")
    manifest = {}
    archive = ROOT / 'release-v22.2-evidence-gated-model-pipeline.zip'
    for name in FILES:
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError(f'Missing or unsafe release member: {name}')
        manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_text = json.dumps(manifest, indent=2) + '\n'
    (ROOT / 'SHA256_MANIFEST.json').write_bytes(manifest_text.encode('utf-8'))
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in FILES:
            bundle.write(ROOT / name, name)
        bundle.writestr('SHA256_MANIFEST.json', manifest_text)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert set(bundle.namelist()) == set(FILES) | {'SHA256_MANIFEST.json'}
        for name, digest in manifest.items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == digest
    print(f'{archive.name}: {len(FILES)} files, verified; no real secrets, databases, caches or environments included')


if __name__ == '__main__':
    package()
