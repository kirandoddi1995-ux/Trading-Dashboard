"""Actual release page, synthetic configuration, no provider/private inputs."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

from package_release import RUNTIME
from release_verification import module_index, release_members
from equity_runtime_health import RELEASE_FILES

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('consent', [False, True])
def test_real_evidence_page_has_opt_in_without_approvals_or_network(tmp_path, consent):
    # Reuse the existing guarded bootstrap, without changing its original tests.
    original = runpy.run_path(str(ROOT / 'tests/test_streamlit_boot.py'))['PROBE']
    marker = '    mode = sys.argv[1]\n'
    assert original.count(marker) == 1
    probe = original.split(marker)[0] + '''
    app.secrets['APP_ENV'] = 'development'
    app.secrets['APP_AUTH_MODE'] = 'disabled'
    app.secrets['EXPECTED_APP_BUILD'] = 'SYNTHETIC_MISMATCH'
    app.secrets['RESILIENCE_POLICY_SHA256'] = 'a' * 64
    app.secrets['EXPECTED_EQUITY_CODE_SHA256'] = 'b' * 64
    app.session_state['primary_section'] = 'Research'
    app.session_state['subpage_Research'] = 'Evidence Readiness'
    app.run()
    assert not app.exception, str([(x.message, x.stack_trace) for x in app.exception])
    controls = [x for x in app.checkbox if x.label == 'I consent to sending my coverage report to this app host']
    assert len(controls) == 1 and controls[0].value is False
    assert not app.get('file_uploader')
    assert any('Selecting a file uploads it to the app host' in x.value for x in app.warning)
    assert not any(x.label == 'Reported retained windows' for x in app.metric)
    if sys.argv[1] == 'consent':
        controls[0].check().run()
        assert not app.exception
        assert len(app.get('file_uploader')) == 1
        assert not any(x.label == 'Reported retained windows' for x in app.metric)
    assert not events, 'Evidence page attempted external I/O'
    print('EQUITY_COVERAGE_PAGE_VERIFIED_SYNTHETIC_ONLY')
'''
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    for name in release_members(ROOT, [*RUNTIME, *RELEASE_FILES]):
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    home = tmp_path / 'private'
    home.mkdir()
    env = {key:value for key,value in os.environ.items() if key.upper() in {
        'SYSTEMROOT','WINDIR','PATH','COMSPEC','PATHEXT','LANG','LC_ALL'}}
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home), LOCALAPPDATA=str(home),
               TEMP=str(home), TMP=str(home), MPLCONFIGDIR=str(home/'matplotlib'),
               QUANT_DB_PATH=str(home/'cache.sqlite3'), QUANT_IV_PATH=str(home/'iv.json'),
               STREAMLIT_BROWSER_GATHER_USAGE_STATS='false', QUANT_ALLOW_INSECURE_LOCAL='1')
    names = sorted({name.split('.')[0] for name in module_index(ROOT)})
    result = subprocess.run([sys.executable,'-I','-B','-c',probe,
                             'consent' if consent else 'default', json.dumps(names)],
                            cwd=checkout, env=env, capture_output=True, text=True,
                            timeout=180, check=False)
    assert result.returncode == 0, result.stderr[-6000:]
    assert 'EQUITY_COVERAGE_PAGE_VERIFIED_SYNTHETIC_ONLY' in result.stdout
