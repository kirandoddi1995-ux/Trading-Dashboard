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
           'requirements.txt', 'constraints.txt']
FILES = RUNTIME + ['.gitignore', '.streamlit/secrets.example.toml', 'PRODUCTION_GUIDE.md',
                   'FIX_VERIFICATION_2026-08-31.md', 'provider_smoke.py', 'package_release.py',
                   'tests/test_regressions.py', 'tests/test_mf_research.py', 'tests/test_audit_fixes.py',
                   'tests/test_performance_foundation.py', 'tests/test_prediction_validation.py',
                   'tests/test_remaining_upgrades.py', '.github/workflows/quality.yml']


def package():
    canaries = run_canaries(ROOT)
    if not canaries['ok']:
        raise RuntimeError(f"Release canaries failed: {canaries['checks']}")
    manifest = {}
    archive = ROOT / 'release-v18.0-production-foundation.zip'
    for name in FILES:
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError(f'Missing or unsafe release member: {name}')
        manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in FILES:
            bundle.write(ROOT / name, name)
        bundle.writestr('SHA256_MANIFEST.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert set(bundle.namelist()) == set(FILES) | {'SHA256_MANIFEST.json'}
        for name, digest in manifest.items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == digest
    print(f'{archive.name}: {len(FILES)} files, verified; no real secrets, databases, caches or environments included')


if __name__ == '__main__':
    package()
