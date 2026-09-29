"""Keep reviewed CI images/actions separate from application runtime versions."""
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / '.github' / 'workflows').glob('*.yml'))
ACTION_VERSIONS = {
    'actions/checkout': 'v5',
    'actions/setup-node': 'v6',
    'actions/setup-python': 'v6',
    'actions/upload-artifact': 'v6',
}


@pytest.mark.parametrize('path', WORKFLOWS, ids=lambda p: p.name)
def test_workflows_use_reviewed_image_and_node24_actions(path):
    text = path.read_text(encoding='utf-8')
    runners = re.findall(r'^\s*runs-on:\s*(\S+)\s*$', text, re.MULTILINE)
    assert runners and all(r == 'ubuntu-24.04' for r in runners)
    for action, version in re.findall(r'uses:\s*(actions/[\w-]+)@(\S+)', text):
        if action in ACTION_VERSIONS:
            assert version == ACTION_VERSIONS[action]
    # Do not conceal incompatible actions by opting back into obsolete runtimes.
    assert 'ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION' not in text
    assert 'FORCE_JAVASCRIPT_ACTIONS_TO_NODE24' not in text
    versions = re.findall(r"python-version:\s*'([^']+)'", text)
    assert versions and set(versions) == {'3.13'}


def test_sql_harness_runtime_and_locked_install_are_preserved():
    text = (ROOT / '.github/workflows/quality.yml').read_text(encoding='utf-8')
    assert "node-version: '24'" in text
    assert 'package-manager-cache: false' in text
    assert 'npm ci --prefix tests/sql-harness --ignore-scripts --no-audit --no-fund' in text
    assert 'EQUITY_TEST_PGLITE_MODULE:' in text
    assert 'Verify SQL safety test engine (mandatory)' in text
    assert 'python -m pytest -q' in text
    assert (ROOT / 'tests/sql-harness/package-lock.json').is_file()
