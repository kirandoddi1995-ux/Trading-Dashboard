"""Real entry-point boot in a disposable checkout with synthetic configuration."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from release_verification import module_index, release_members
from package_release import RUNTIME
from equity_runtime_health import RELEASE_FILES

ROOT = Path(__file__).resolve().parents[1]

PROBE = r'''
import importlib.abc, importlib.machinery, json, pathlib, platform, sys
platform.platform()
platform.processor()
events = []
def network(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'}:
        events.append(event)
        raise RuntimeError('Boot smoke external network forbidden')
sys.addaudithook(network)
import matplotlib.font_manager
def subprocess_guard(event, args):
    if event in {'subprocess.Popen', 'os.system'}:
        events.append(event)
        raise RuntimeError('Boot smoke subprocess forbidden')
sys.addaudithook(subprocess_guard)
root = pathlib.Path.cwd()
local_names = set(json.loads(sys.argv[2]))
sys.path[:] = [str(root)] + [p for p in sys.path if p and
    ('site-packages' in pathlib.Path(p).parts or not pathlib.Path(p, 'app.py').exists())]
class LocalOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] not in local_names:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, [str(root)] if path is None else path)
        if spec is None or not spec.origin or not pathlib.Path(spec.origin).resolve().is_relative_to(root):
            raise ImportError('Boot dependency absent from disposable checkout')
        return spec
sys.meta_path.insert(0, LocalOnly())
from streamlit.testing.v1 import AppTest
app = AppTest.from_file(str(root/'app.py'), default_timeout=90)
mode = sys.argv[1]
if mode == 'login':
    app.secrets['auth'] = dict(redirect_uri='http://localhost:8501/oauth2callback',
        cookie_secret='SYNTHETIC_COOKIE', client_id='SYNTHETIC_CLIENT',
        client_secret='SYNTHETIC_SECRET', server_metadata_url='https://example.invalid/.well-known/openid-configuration')
else:
    app.secrets['APP_ENV'] = 'development'
    app.secrets['APP_AUTH_MODE'] = 'disabled'
    app.session_state['primary_section'] = 'Settings'
    app.secrets['EXPECTED_APP_BUILD'] = 'SYNTHETIC_EXPECTED_BUILD'
    app.secrets['RESILIENCE_POLICY_SHA256'] = 'a' * 64
    app.secrets['EXPECTED_EQUITY_CODE_SHA256'] = 'b' * 64
app.run()
assert not app.exception, str([(item.message, item.stack_trace) for item in app.exception])
if mode == 'login':
    assert any(item.label == 'Sign in' for item in app.button), 'OIDC sign-in gate did not render'
else:
    assert any(item.value == 'Quant Terminal' for item in app.title), 'Application title missing'
    assert any(item.label == 'Auto-Refresh Interval' for item in app.select_slider), 'Settings page did not render'
    diagnostics = [json.loads(item.value)['release_configuration_sources']
                   for item in app.json if 'release_configuration_sources' in json.loads(item.value)]
    assert len(diagnostics) == 1, 'Release source diagnostics missing'
    assert all(item['status'] == 'VALID' and item['source'] == 'STREAMLIT_ROOT'
               and item['matches_actual'] is False for item in diagnostics[0].values())
    assert 'SYNTHETIC_EXPECTED_BUILD' not in json.dumps(diagnostics)
assert not events, 'Boot attempted external I/O'
print('STREAMLIT_BOOT_VERIFIED')
'''


@pytest.mark.parametrize('mode', ['login', 'settings'])
def test_actual_app_boot_offline(mode, tmp_path):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    # Dependency discovery includes the real app; no secrets/state/data copied.
    for name in release_members(ROOT, [*RUNTIME, *RELEASE_FILES]):
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    home = tmp_path / 'private'
    home.mkdir()
    env = {key: value for key, value in os.environ.items() if key.upper() in {
        'SYSTEMROOT', 'WINDIR', 'PATH', 'COMSPEC', 'PATHEXT', 'LANG', 'LC_ALL'}}
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home), LOCALAPPDATA=str(home),
               TMP=str(home), TEMP=str(home), MPLCONFIGDIR=str(home / 'matplotlib'),
               QUANT_DB_PATH=str(home / 'cache.sqlite3'), QUANT_IV_PATH=str(home / 'iv.json'),
               STREAMLIT_BROWSER_GATHER_USAGE_STATS='false', QUANT_ALLOW_INSECURE_LOCAL='1')
    names = sorted({name.split('.')[0] for name in module_index(ROOT)})
    process = subprocess.run([sys.executable, '-I', '-B', '-c', PROBE, mode, json.dumps(names)], cwd=checkout,
                             env=env, capture_output=True, text=True, timeout=120, check=False)
    assert process.returncode == 0, process.stderr[-6000:]
    assert 'STREAMLIT_BOOT_VERIFIED' in process.stdout
