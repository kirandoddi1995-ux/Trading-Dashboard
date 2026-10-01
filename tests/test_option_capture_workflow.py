"""Execute the actual workflow scripts offline; never connect to broker or Drive."""
import json
from pathlib import Path
import textwrap

import pytest

import option_capture_job as job


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/option-research-capture.yml'


def scripts():
    text = WORKFLOW.read_text()
    return [textwrap.dedent(part.split('          PY', 1)[0])
            for part in text.split("python - <<'PY'\n")[1:]]


@pytest.mark.parametrize('event,mode,confirmation,enabled,expected', [
    ('workflow_dispatch', 'capture', False, 'true', False),
    ('workflow_dispatch', 'capture', True, 'false', True),
    ('workflow_dispatch', 'audit', False, 'true', False),
    ('workflow_dispatch', 'audit', True, 'false', True),
    ('schedule', '', False, 'false', False),
    ('schedule', '', False, 'true', True),
    ('workflow_dispatch', 'preview', False, 'false', False),
    ('workflow_dispatch', 'capture', 'false', 'true', False),
    ('workflow_dispatch', 'capture', 'true', 'true', False),
    ('workflow_dispatch', 'capture', 1, 'true', False),
    ('push', 'capture', True, 'true', False),
    ('pull_request', 'capture', True, 'true', False),
])
def test_authorization_and_dispatch(monkeypatch, tmp_path, capsys,
                                    event, mode, confirmation, enabled, expected):
    output = tmp_path / 'output'
    for key, value in dict(EVENT_NAME=event, REQUESTED_MODE=mode,
                           CONFIRMATION_JSON=json.dumps(confirmation),
                           SCHEDULE_ENABLED=enabled, GITHUB_OUTPUT=str(output),
                           REQUESTED_SLOT='1500', CRON='25 9 * * 1-5').items():
        monkeypatch.setenv(key, value)
    authorize, dispatch = scripts()
    exec(compile(authorize, '<authorization>', 'exec'), {})
    assert output.read_text() == f'authorized={str(expected).lower()}\n'
    monkeypatch.setenv('OPTION_CAPTURE_ENABLED', str(expected).lower())
    # Missing license stops authorized runs before network; denied runs must
    # stop even earlier at the unchanged Python enable guard.
    monkeypatch.delenv('OPTION_CAPTURE_LICENSE_ACK', raising=False)
    calls = []
    original = job.main

    def main(args):
        calls.append(args)
        return original(args)

    monkeypatch.setattr(job, 'main', main)
    monkeypatch.setattr(job, 'DriveArchive', lambda *a, **k: pytest.fail('Network path reached'))
    with pytest.raises(SystemExit) as result:
        exec(compile(dispatch, '<dispatch>', 'exec'), {})
    if event not in {'schedule', 'workflow_dispatch'}:
        assert not calls
        return
    report = json.loads(capsys.readouterr().out)
    if mode == 'preview':
        assert result.value.code == 0
        assert report['status'] == 'PREVIEW' and report['network_calls'] == 0
    else:
        assert result.value.code == 1
        assert report['status'] == ('LICENSE_ACK_REQUIRED' if expected else 'CAPTURE_DISABLED')
    if event == 'workflow_dispatch':
        assert ('--wait-for-slot' in calls[0]) == (mode == 'capture' and expected)


def test_workflow_safety_structure():
    text = WORKFLOW.read_text()
    triggers = text.split('on:\n', 1)[1].split('\npermissions:', 1)[0]
    assert {line.strip().rstrip(':') for line in triggers.splitlines()
            if line.startswith('  ') and not line.startswith('   ')} == {'schedule', 'workflow_dispatch'}
    confirmation = triggers.split('      confirm_one_run:', 1)[1].split('  schedule:', 1)[0]
    assert 'type: boolean' in confirmation and 'default: false' in confirmation
    assert 'permissions:\n  contents: read\n\n' in text
    assert 'concurrency:\n  group: option-research-capture\n  cancel-in-progress: false' in text
    assert 'timeout-minutes: 25' in text
    assert "OPTION_CAPTURE_ENABLED: ${{ steps.authorization.outputs.authorized || 'false' }}" in text
    authorization = text.split('      - name: Compute one-run authorization', 1)[1].split('      - uses:', 1)[0]
    assert 'secrets.' not in authorization
