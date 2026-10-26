"""Release-only dependency/cache/CI regressions; generated inputs, no providers.

Supports the reviewed Python 3.12/3.13 candidates. Exact package metadata here is
local test-environment evidence, never a claim about the hosted installed runtime.
FileCache tests record Windows chmod intent without a syscall; Linux CI exercises
the native permission-setting roundtrip.
"""

from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from PIL import Image
import pytest
import streamlit as st

import equity_scan_profiling as profiling


ROOT = Path(__file__).resolve().parents[1]
PINS = {
    'streamlit': '1.66.1', 'pillow': '13.0.0', 'certifi': '2026.10.23',
    'filelock': '4.2.1', 'pip': '26.2.2',
    'opentelemetry-api': '1.45.1', 'opentelemetry-sdk': '1.45.1',
    'opentelemetry-exporter-otlp-proto-http': '1.45.1',
    'opentelemetry-proto': '1.45.1',
    'opentelemetry-exporter-otlp-proto-common': '1.45.1',
    'opentelemetry-semantic-conventions': '0.66b1',
    'opentelemetry-exporter-http-transport': '0.66b1',
    'opentelemetry-exporter-otlp-common': '0.66b1',
}


def test_exact_profile_is_installed_and_constrained():
    constraints = (ROOT / 'constraints.txt').read_text(encoding='utf-8').splitlines()
    for name, version in PINS.items():
        assert constraints.count(name + '==' + version) == 1, name
        assert metadata.version(name) == version, name
    requirements = (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines()
    assert '-c constraints.txt' in requirements
    for name in ('streamlit', 'opentelemetry-sdk', 'opentelemetry-exporter-otlp-proto-http'):
        assert requirements.count(name + '==' + PINS[name]) == 1


def test_generated_png_roundtrip_is_exact():
    pixels = Image.new('RGB', (2, 2), (10, 20, 30))
    output = io.BytesIO()
    pixels.save(output, format='PNG')
    with Image.open(io.BytesIO(output.getvalue())) as decoded:
        decoded.load()
        assert decoded.size == (2, 2)
        assert decoded.getpixel((0, 0)) == (10, 20, 30)


CHART_PROBE = r'''
import asyncio, platform, sys
platform.platform()
platform.processor()
import matplotlib
matplotlib.use('Agg')
import matplotlib.font_manager
from streamlit.testing.v1 import AppTest

original_factory = asyncio.new_event_loop
unused = []
violations = []
events = []
try:
    for _ in range(2):
        unused.append(original_factory())
    def bounded_factory():
        if not unused:
            violations.append('POOL_EXHAUSTED')
            raise RuntimeError('Synthetic chart loop pool exhausted')
        return unused.pop()
    asyncio.new_event_loop = bounded_factory
    def deny(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto',
                     'subprocess.Popen', 'os.system'}:
            events.append(event)
            raise RuntimeError('Synthetic chart external I/O forbidden')
    sys.addaudithook(deny)
    app = AppTest.from_string("""
import streamlit as st
import matplotlib.pyplot as plt
from PIL import Image
st.image(Image.new('RGB', (2, 2), (10, 20, 30)))
fig, ax = plt.subplots()
ax.plot([0, 1], [0, 1])
st.pyplot(fig)
plt.close(fig)
""").run(timeout=20)
    assert not app.exception
    assert not events and not violations
    assert len(app.image) == 2
    assert all(len(image.value) == 1 and image.value[0] for image in app.image)
finally:
    asyncio.new_event_loop = original_factory
    for loop in unused:
        loop.close()
print('SYNTHETIC_PNG_PLOT_VERIFIED')
'''


def test_streamlit_generated_png_and_plot_offline(tmp_path):
    home = tmp_path / 'synthetic-home'
    home.mkdir()
    probe = tmp_path / 'generated_chart_probe.py'
    probe.write_text(CHART_PROBE, encoding='utf-8')
    env = {key: value for key, value in os.environ.items() if key.upper() in {
        'SYSTEMROOT', 'WINDIR', 'PATH', 'COMSPEC', 'PATHEXT', 'LANG', 'LC_ALL'}}
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home), LOCALAPPDATA=str(home),
               TMP=str(home), TEMP=str(home), MPLCONFIGDIR=str(home / 'matplotlib'),
               STREAMLIT_BROWSER_GATHER_USAGE_STATS='false')
    result = subprocess.run([sys.executable, '-I', '-B', str(probe)], cwd=home, env=env,
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr[-6000:]
    assert 'SYNTHETIC_PNG_PLOT_VERIFIED' in result.stdout


def test_observed_cache_uses_the_same_underlying_primitive():
    lock = threading.Lock()

    class Cache:
        def compute_value_lock(self, key):
            assert key == 'synthetic-key'
            return lock

    cache = Cache()
    first = profiling._ObservedCache(cache).compute_value_lock('synthetic-key')
    second = profiling._ObservedCache(cache).compute_value_lock('synthetic-key')
    assert first.lock is second.lock is lock
    assert first.acquire(blocking=False) is True
    try:
        assert second.acquire(blocking=False) is False
    finally:
        first.release()
    assert second.acquire(blocking=False) is True
    second.release()


def test_cache_contended_miss_hit_and_clear_preserve_shared_lock(monkeypatch):
    entered = threading.Event()
    allow_refresh = threading.Event()
    contended = threading.Event()
    refreshes = []
    identities = []
    identity_guard = threading.Lock()
    original_lock = profiling._ObservedCache.compute_value_lock
    original_acquire = profiling._ObservedLock.acquire

    def observe_lock(self, key):
        observed = original_lock(self, key)
        assert observed.lock is self.cache.compute_value_lock(key)
        with identity_guard:
            identities.append(id(observed.lock))
        return observed

    def observe_acquire(self, *args, **kwargs):
        acquired = original_acquire(self, *args, **kwargs)
        if kwargs.get('blocking') is False and acquired is False:
            contended.set()
        return acquired

    monkeypatch.setattr(profiling._ObservedCache, 'compute_value_lock', observe_lock)
    monkeypatch.setattr(profiling._ObservedLock, 'acquire', observe_acquire)

    @profiling.observe_health_cache
    @st.cache_data(show_spinner=False)
    def health():
        refreshes.append(1)
        entered.set()
        assert allow_refresh.wait(5)
        return {'status': 'SYNTHETIC'}

    @profiling.profile_controller
    def exercise(self, job):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(profiling.run_candidate, job['id'], 'A', time.perf_counter(), lambda _: health(), None)
            try:
                assert entered.wait(5)
                second = pool.submit(profiling.run_candidate, job['id'], 'B', time.perf_counter(), lambda _: health(), None)
                assert contended.wait(5)
            finally:
                allow_refresh.set()
            assert first.result(5) == second.result(5) == {'status': 'SYNTHETIC'}
        assert len(refreshes) == 1
        assert len(identities) == 2 and identities[0] == identities[1]
        assert health() == {'status': 'SYNTHETIC'}
        assert len(refreshes) == 1 and len(identities) == 2  # Hit acquires no compute lock.
        health.clear()
        assert health() == {'status': 'SYNTHETIC'}
        assert len(refreshes) == 2

    health.clear()
    try:
        exercise(None, {'id': 'release-security-cache'})
    finally:
        allow_refresh.set()
        health.clear()


def test_cachecontrol_filecache_roundtrip_windows_permission_intent_linux_native(tmp_path, monkeypatch):
    """Windows: mock chmod intent and deny the syscall. Linux: native roundtrip."""
    from cachecontrol.caches import FileCache
    import cachecontrol.caches.file_cache as file_cache

    cache = FileCache(str(tmp_path / 'synthetic-audit-cache'))
    key = 'https://example.invalid/synthetic'
    target = Path(cache._fn(key))
    chmod_intents = []
    if sys.platform == 'win32':
        def deny_actual_chmod(*args, **kwargs):
            raise AssertionError('Actual Windows chmod forbidden in this test')

        # file_cache uses `import os` and calls os.chmod on the mkstemp file,
        # before atomic promotion to target. Give only that module a proxy;
        # the real os module keeps a denial guard, not a recording no-op.
        class PermissionIntentOS:
            def __getattr__(self, name):
                return getattr(os, name)

            def chmod(self, name, mode):
                temporary = Path(name)
                assert temporary.parent == target.parent and temporary != target
                assert temporary.is_file() and temporary.read_bytes() == b'synthetic bytes'
                assert mode == cache.filemode == 0o600
                chmod_intents.append((temporary, mode))

        monkeypatch.setattr(os, 'chmod', deny_actual_chmod)
        monkeypatch.setattr(file_cache, 'os', PermissionIntentOS())
        with pytest.raises(AssertionError, match='Actual Windows chmod forbidden'):
            os.chmod(target, cache.filemode)  # Exercise the guard, never the syscall.
        assert chmod_intents == []
    cache.set(key, b'synthetic bytes')
    assert cache.get(key) == b'synthetic bytes'
    if sys.platform == 'win32':
        assert len(chmod_intents) == 1
        temporary, mode = chmod_intents[0]
        assert temporary.parent == target.parent and mode == 0o600
        assert not temporary.exists() and target.read_bytes() == b'synthetic bytes'
    cache.delete(key)
    assert cache.get(key) is None


def test_patched_installer_and_both_audits_are_mandatory_workflow_gates():
    workflow = (ROOT / '.github/workflows/quality.yml').read_text(encoding='utf-8')
    steps = re.split(r'(?m)^      - ', workflow)[1:]
    required = (
        "python -m pip install 'pip==26.2.2'",
        'python -m pip_audit -r requirements.txt',
        'python -m pip_audit',
    )
    positions = []
    for command in required:
        matching = [(index, step) for index, step in enumerate(steps)
                    if re.search(r'(?m)^\s*run:\s*' + re.escape(command) + r'\s*$', step)]
        assert len(matching) == 1, command
        index, step = matching[0]
        positions.append(index)
        assert not re.search(r'(?m)^\s*(?:if|continue-on-error):', step)
    app_install = next(index for index, step in enumerate(steps) if 'pip install -r requirements.txt' in step)
    assert positions[0] < app_install < positions[1] < positions[2]
    for forbidden in ('--ignore-vuln', '--no-deps', '|| true', 'continue-on-error'):
        assert forbidden not in workflow
    for retained in ('python environment_preflight.py --strict', '--config-file mypy-automation.ini',
                     'python -m pytest -q tests/test_streamlit_boot.py',
                     'python -m pytest -q', 'python resilience_acceptance.py --game-day',
                     'python deployment_canary.py', 'python package_release.py', 'npm ci --prefix tests/sql-harness'):
        assert retained in workflow
