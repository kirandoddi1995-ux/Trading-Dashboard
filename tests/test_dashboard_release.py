"""Offline release/ref simulations: never access GitHub or application secrets."""
import json
from pathlib import Path

import pytest

import dashboard_release as release
from equity_runtime_health import release_fingerprint

REPO = 'owner/dashboard'
OLD, NEW, OTHER = 'a' * 40, 'b' * 40, 'c' * 40


class Fake:
    def __init__(self):
        self.refs = {'heads/main': NEW, 'heads/release': OLD, release.VERIFIED + OLD: OLD}
        self.writes = []
        self.bad = {}
        self.checks = [dict(name='CodeQL', head_sha=NEW, status='completed', conclusion='success',
                            app={'slug': 'github-code-scanning'})]
        self.more_runs = []

    def call(self, path, *, method='GET', data=None):
        if method != 'GET':
            self.writes.append((path, method, data))
            self.refs[data.get('ref', path.replace('/git/', '')).removeprefix('refs/')] = data['sha']
            return {}
        if path.startswith('/git/ref/'):
            value = self.refs.get(path.removeprefix('/git/ref/'))
            return None if value is None else {'object': {'type': 'commit', 'sha': value}}
        if path.startswith('/compare/'):
            return {'status': self.bad.get('ancestry', 'ahead')}
        if '/actions/workflows/' in path:
            workflow = path.split('/')[3]
            sha = path.split('head_sha=')[1].split('&')[0]
            row = dict(id=1, run_attempt=1, head_sha=sha, event='push', head_branch='main',
                       head_repository={'full_name': REPO}, status='completed',
                       conclusion=self.bad.get(workflow, 'success'))
            row.update(self.bad.get('run_fields', {}))
            return {'workflow_runs': [row, *self.more_runs]}
        if '/check-runs?' in path:
            sha = path.split('/')[2]
            return {'check_runs': [dict(row, head_sha=sha) for row in self.checks]}
        raise AssertionError(path)


def ready(api, mode='promote', **kwargs):
    return release.plan(api, REPO, mode, enabled='true' if mode != 'rollback' else 'false', **kwargs)


def test_exact_green_head_promoted_without_merge_commit():
    api = Fake()
    report = ready(api)
    result = release.publish(api, REPO, report, 'promote', enabled='true')
    assert result['status'] == 'PROMOTED'
    assert api.refs['heads/release'] == NEW
    assert api.writes[-1] == ('/git/refs/heads/release', 'PATCH', {'sha': NEW, 'force': False})


@pytest.mark.parametrize('bad', ['failure', 'skipped', 'neutral', None])
def test_non_success_quality_never_publishes(bad):
    api = Fake()
    api.bad['quality.yml'] = bad
    report = ready(api)
    assert not report['ready']
    with pytest.raises(release.ReleaseError): release.publish(api, REPO, report, 'promote', enabled='true')
    assert not api.writes


@pytest.mark.parametrize('fields', [{'event': 'pull_request'}, {'head_branch': 'feature'},
                                   {'head_sha': OTHER}, {'head_repository': {'full_name': 'fork/dashboard'}},
                                   {'status': 'in_progress'}])
def test_wrong_origin_or_incomplete_runs_do_not_count(fields):
    api = Fake()
    api.bad['run_fields'] = fields
    assert not ready(api)['ready']


def test_latest_failed_rerun_overrides_old_success():
    api = Fake()
    api.more_runs = [dict(id=1, run_attempt=2, head_sha=NEW, event='push', head_branch='main',
                         head_repository={'full_name': REPO}, status='completed', conclusion='failure')]
    assert not ready(api)['ready']


@pytest.mark.parametrize('checks', [[], [dict(name='CodeQL', app={'slug': 'github-actions'},
    status='completed', conclusion='success')], [dict(name='CodeQL', app={'slug': 'github-code-scanning'},
    status='completed', conclusion='neutral')]])
def test_missing_spoofed_or_non_success_codeql_blocks(checks):
    api = Fake()
    api.checks = checks
    assert not ready(api)['ready']


def test_every_codeql_category_must_succeed():
    api = Fake()
    api.checks.append(dict(api.checks[0], conclusion='failure'))
    assert not ready(api)['ready']


@pytest.mark.parametrize('change', ['head', 'release', 'checks', 'switch'])
def test_changes_between_plan_and_write_never_publish(change):
    api = Fake()
    report = ready(api)
    if change == 'head': api.refs['heads/main'] = OTHER
    if change == 'release': api.refs['heads/release'] = OTHER
    if change == 'checks': api.bad['resilience.yml'] = 'failure'
    with pytest.raises(release.ReleaseError):
        release.publish(api, REPO, report, 'promote', enabled='false' if change == 'switch' else 'true')
    assert not api.writes


def test_disabled_missing_or_string_false_never_authorize():
    api = Fake()
    for enabled in ('', 'false', 'True'):
        assert not release.plan(api, REPO, 'promote', enabled=enabled)['ready']
    for confirmation in (False, 'false', 'true', 1, None):
        with pytest.raises(release.ReleaseError):
            release.plan(api, REPO, 'rollback', enabled='false', rollback_sha=OLD, confirmed=confirmation)
    assert not api.writes


def test_explicit_paused_rollback_requires_recorded_ancestor():
    api = Fake()
    api.refs['heads/release'] = NEW
    report = ready(api, 'rollback', rollback_sha=OLD, confirmed=True)
    assert release.publish(api, REPO, report, 'rollback', enabled='false',
                           rollback_sha=OLD, confirmed=True)['status'] == 'ROLLED_BACK'
    assert api.writes[-1][2] == {'sha': OLD, 'force': True}
    for bad in ('unrecorded', 'diverged', 'enabled'):
        api = Fake()
        api.refs['heads/release'] = NEW
        if bad == 'unrecorded': del api.refs[release.VERIFIED + OLD]
        if bad == 'diverged': api.bad['ancestry'] = 'diverged'
        with pytest.raises(release.ReleaseError):
            release.plan(api, REPO, 'rollback', enabled='true' if bad == 'enabled' else 'false',
                         rollback_sha=OLD, confirmed=True)


def test_initial_branch_creation_idempotence_and_marker_conflict():
    api = Fake()
    del api.refs['heads/release']
    report = ready(api)
    assert release.publish(api, REPO, report, 'promote', enabled='true')['status'] == 'PROMOTED'
    assert release.publish(api, REPO, ready(api), 'promote', enabled='true')['status'] == 'ALREADY_RELEASED'
    api = Fake()
    api.refs[release.VERIFIED + NEW] = OTHER
    with pytest.raises(release.ReleaseError): release.publish(api, REPO, ready(api), 'promote', enabled='true')
    assert not api.writes


def test_pagination_reads_beyond_first_page_and_bounds_excess():
    class Pager:
        def call(self, path, **kwargs):
            return {'items': [{'id': 1}] * 100 if 'page=1&' in path or path.endswith('page=1') else [{'id': 2}]}
    assert len(release.pages(Pager(), '/example', 'items')) == 101
    class Endless:
        def call(self, path, **kwargs): return {'items': [{}] * 100}
    with pytest.raises(release.ReleaseError): release.pages(Endless(), '/example', 'items')


def test_fingerprint_reads_historical_manifest_without_executing_code(tmp_path):
    (tmp_path / 'equity_runtime_health.py').write_text("raise RuntimeError('must not execute')\nRELEASE_FILES=('app.py',)\n")
    (tmp_path / 'app.py').write_bytes(b'print("test")\r\n')
    assert release.fingerprint(tmp_path) == release_fingerprint(tmp_path, names=('app.py',))
    root = Path(__file__).resolve().parents[1]
    assert release.fingerprint(root) == release_fingerprint(root)


def test_preview_adapter_no_writes_and_errors_never_leak(monkeypatch, capsys):
    api = Fake()
    monkeypatch.setattr(release, 'GitHub', lambda *args: api)
    for key, value in {'EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
                       'GITHUB_REPOSITORY': REPO, 'GH_TOKEN': 'SECRET_TOKEN', 'REQUESTED_MODE': 'preview',
                       'CONFIRM_ROLLBACK_JSON': 'false'}.items(): monkeypatch.setenv(key, value)
    monkeypatch.delenv('GITHUB_OUTPUT', raising=False)
    assert release.main([]) == 0
    assert json.loads(capsys.readouterr().out)['ready'] is True
    assert not api.writes
    monkeypatch.setattr(api, 'call', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('SECRET_TOKEN')))
    assert release.main([]) == 1
    assert 'SECRET_TOKEN' not in capsys.readouterr().out


@pytest.mark.parametrize('event,ref', [('push', 'refs/heads/main'),
    ('pull_request', 'refs/heads/main'), ('workflow_dispatch', 'refs/heads/feature')])
def test_adapter_forbids_untrusted_triggers_before_api(event, ref, monkeypatch, capsys):
    monkeypatch.setenv('EVENT_NAME', event)
    monkeypatch.setenv('GITHUB_REF', ref)
    monkeypatch.setattr(release, 'GitHub', lambda *a: pytest.fail('API must not be constructed'))
    assert release.main([]) == 1
    assert json.loads(capsys.readouterr().out)['ready'] is False


def test_publisher_adapter_fails_on_controller_checks_before_any_write(tmp_path, monkeypatch, capsys):
    api = Fake()
    original = api.call
    def call(path, **kwargs):
        result = original(path, **kwargs)
        if 'head_sha=' + OTHER in path:
            for row in result['workflow_runs']: row['conclusion'] = 'failure'
        return result
    api.call = call
    monkeypatch.setattr(release, 'GitHub', lambda *a: api)
    for key, value in {'EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
        'GITHUB_SHA': OTHER, 'GITHUB_REPOSITORY': REPO, 'GH_TOKEN': 'SECRET_TOKEN',
        'REQUESTED_MODE': 'promote', 'RELEASE_ENABLED': 'true', 'EXPECTED_CANDIDATE_SHA': NEW,
        'EXPECTED_PREVIOUS_SHA': OLD, 'CONFIRM_ROLLBACK_JSON': 'false'}.items():
        monkeypatch.setenv(key, value)
    assert release.main(['--publish', '--candidate-root', str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'RELEASE_CONTROLLER_NOT_VERIFIED'
    assert not api.writes


def test_wait_abandons_superseded_main_without_writes(monkeypatch, capsys):
    api = Fake()
    api.bad['quality.yml'] = 'failure'
    monkeypatch.setattr(release, 'GitHub', lambda *a: api)
    for key, value in {'EVENT_NAME': 'workflow_run', 'GITHUB_REF': 'refs/heads/main',
        'GITHUB_REPOSITORY': REPO, 'GH_TOKEN': 'SECRET_TOKEN', 'RELEASE_ENABLED': 'true',
        'CONFIRM_ROLLBACK_JSON': 'null'}.items(): monkeypatch.setenv(key, value)
    monkeypatch.delenv('GITHUB_OUTPUT', raising=False)
    monkeypatch.setattr(release.time, 'sleep', lambda *a: api.refs.update({'heads/main': OTHER}))
    assert release.main([]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'SUPERSEDED'
    assert not api.writes


def test_api_errors_and_bad_identities_are_sanitized(monkeypatch, capsys):
    from urllib.error import HTTPError
    for sha in ('main', 'a' * 39, 'A' * 40, '; echo token'):
        with pytest.raises(release.ReleaseError): release.commit(sha)
    with pytest.raises(release.ReleaseError): release.GitHub('owner/../repo', 'secret')
    client = release.GitHub(REPO, 'SECRET_TOKEN')
    def fail(*args, **kwargs): raise HTTPError('https://example.invalid/SECRET_TOKEN', 403, 'SECRET_TOKEN', {}, None)
    monkeypatch.setattr(release, 'urlopen', fail)
    with pytest.raises(release.ReleaseError, match='^RELEASE_API_FAILED$'):
        client.call('/git/ref/heads/main')
    assert not capsys.readouterr().out


def test_workflow_limits_privilege_and_does_not_touch_model_workflows():
    source = (Path(__file__).resolve().parents[1] / '.github/workflows/dashboard-release.yml').read_text()
    assert 'cancel-in-progress: false' in source
    assert 'persist-credentials: false' in source
    assert 'needs.verify.outputs.ready' in source
    assert source.count('contents: write') == 1
    assert 'secrets.' not in source and 'id-token: write' not in source
