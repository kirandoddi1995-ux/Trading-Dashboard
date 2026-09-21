"""Exercise the exact inline validators, before any cloud credentials are used."""
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap

import pytest


WORKFLOWS = Path(__file__).resolve().parents[1] / '.github/workflows'


@pytest.fixture(params=['production-promotion.yml', 'production-rollback.yml'])
def workflow(request):
    return (WORKFLOWS / request.param).read_text(encoding='utf-8')


def validate(workflow, root, value):
    script = re.search(r"python - <<'PY'\n(.*?)\n          PY", workflow, re.S).group(1)
    return subprocess.run(
        [sys.executable, '-I', '-c', textwrap.dedent(script)], cwd=root,
        env={**os.environ, 'REQUEST_PATH': value}, capture_output=True, text=True,
        timeout=10,
    )


def test_validation_precedes_credentials_and_shell_uses_only_env(workflow):
    assert workflow.index('Validate repository request path') < workflow.index('google-github-actions/auth')
    if '${{ secrets.' in workflow:
        assert workflow.index('Validate repository request path') < workflow.index('${{ secrets.')
    assert workflow.count('REQUEST_PATH: ${{ inputs.request_path }}') == 2
    for line in workflow.splitlines():
        if '${{ inputs.request_path }}' in line:
            assert line.strip() == 'REQUEST_PATH: ${{ inputs.request_path }}'
    assert 'python verify_promotion_request.py "./$REQUEST_PATH"' in workflow
    if '--require-action ROLLBACK' in workflow:
        section = workflow.split('- name: Validate repository request path')[1].split('- name: Authenticate')[0]
        assert 'working-directory: authorization' in section


@pytest.mark.parametrize('name', ['request.json', 'request with spaces.json', '-request.json'])
def test_existing_repository_file_passes(workflow, tmp_path, name):
    (tmp_path / name).write_text('{}')
    assert validate(workflow, tmp_path, name).returncode == 0


@pytest.mark.parametrize('value', ['', 'missing.json', '.', '../outside.json', 'bad\npath', '$(touch PWNED)', '"; touch PWNED; #'])
def test_invalid_paths_fail_without_executing_input(workflow, tmp_path, value):
    (tmp_path.parent / 'outside.json').write_text('{}')
    result = validate(workflow, tmp_path, value)
    assert result.returncode != 0
    assert 'Invalid request_path:' in result.stderr
    assert not (tmp_path / 'PWNED').exists()


def test_absolute_existing_file_rejected(workflow, tmp_path):
    target = tmp_path / 'request.json'
    target.write_text('{}')
    assert validate(workflow, tmp_path, str(target)).returncode != 0


def test_symlink_escape_rejected(workflow, tmp_path):
    outside = tmp_path.parent / 'outside.json'
    outside.write_text('{}')
    try:
        (tmp_path / 'link.json').symlink_to(outside)
    except OSError:
        pytest.skip('Host does not permit symlink creation')
    assert validate(workflow, tmp_path, 'link.json').returncode != 0


@pytest.mark.skipif(sys.platform == 'win32', reason='Workflow shell is Linux bash')
def test_bash_treats_malicious_filename_as_data(workflow, tmp_path):
    name = '$(touch PWNED); request.json'
    (tmp_path / name).write_text('{}')
    assert validate(workflow, tmp_path, name).returncode == 0
    # Use the real authorization command, replacing only its Python receiver.
    command = next(line.strip()[5:] for line in workflow.splitlines()
                   if line.strip().startswith('run: python verify_promotion_request.py'))
    (tmp_path / 'verify_promotion_request.py').write_text(
        'import os, sys\nassert sys.argv[1] == "./" + os.environ["REQUEST_PATH"]\n')
    result = subprocess.run(['bash', '-e', '-c', command], cwd=tmp_path,
                            env={**os.environ, 'REQUEST_PATH': name}, timeout=10)
    assert result.returncode == 0
    assert not (tmp_path / 'PWNED').exists()
