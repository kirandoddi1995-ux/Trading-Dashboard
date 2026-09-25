"""Build a staged release, close local imports, and gate the extracted artifact."""
import hashlib
import json
from pathlib import Path
import zipfile
import tempfile
from deployment_canary import run_canaries
from release_verification import release_members, verify_archive


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
           'evidence_progress.py', 'event_backtest.py', 'volatility_models.py',
           'track_record.py',
           'resilience_policy.json', 'resilience_policy.sha256',
           'requirements.txt', 'constraints.txt']
FILES = RUNTIME + ['release_verification.py', 'RELEASE_PACKAGING.md',
                   'sql/derivative_foundations_review_only.sql', 'DERIVATIVE_FOUNDATIONS.md',
                   'requirements-archive.txt', 'tests/test_release_packaging.py',
                   '.gitignore', '.streamlit/secrets.example.toml', 'PRODUCTION_GUIDE.md',
                   'RESILIENCE_IMPLEMENTATION.md', 'RESILIENCE_RUNBOOK.md',
                   'CONTINUOUS_EVOLUTION_IMPLEMENTATION.md',
                   'PREDICTION_RIGOR_IMPLEMENTATION.md',
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
                   'tests/test_option_research_features.py',
                   'tests/test_model_training_pipeline.py',
                   'tests/test_evidence_progress.py', 'tests/test_prediction_rigor.py',
                   'tests/test_rejection_transparency.py',
                   'tests/test_app_import_smoke.py',
                   '.github/workflows/quality.yml', '.github/workflows/scheduled-collector.yml',
                   '.github/workflows/resilience.yml', '.github/workflows/production-promotion.yml',
                   '.github/workflows/production-rollback.yml',
                   '.github/workflows/recovery-drill.yml',
                   '.github/workflows/model-training-smoke.yml',
                   '.github/workflows/model-training-readiness.yml',
                   'PRODUCTION_EXTERNAL_ACTIONS.md', 'EVIDENCE_READINESS.md']


def package(root=None):
    root = Path(root or ROOT).resolve()
    canaries = run_canaries(root)
    if not canaries['ok']:
        raise RuntimeError(f"Release canaries failed: {canaries['checks']}")
    manifest = {}
    archive = root / 'release-v22.5.7-futures-history-hotfix.zip'
    members = release_members(root, FILES)
    # Build in a disposable directory on the destination filesystem. Never
    # replace the previous good ZIP with an incomplete or unverified artifact.
    with tempfile.TemporaryDirectory(prefix='.release-stage-', dir=root) as staging:
        staged = Path(staging) / archive.name
        with zipfile.ZipFile(staged, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            for name in members:
                data = (root / name).read_bytes()
                manifest[name] = hashlib.sha256(data).hexdigest()
                bundle.writestr(name, data)
            manifest_text = json.dumps(manifest, indent=2) + '\n'
            bundle.writestr('SHA256_MANIFEST.json', manifest_text)
        verify_archive(staged)  # Mandatory: subprocess imports the extracted ZIP.
        staged.replace(archive)
        sidecar = Path(staging) / 'SHA256_MANIFEST.json'
        sidecar.write_bytes(manifest_text.encode('utf-8'))
        sidecar.replace(root / sidecar.name)
    print(f'{archive.name}: {len(members)} files; extracted import and hashes verified')
    return archive


if __name__ == '__main__':
    package()
