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
        self.codeql_fields = {}
        self.codeql_more = []
        self.job_fields = {}
        self.job_names = list(release.CODEQL_JOBS)
        self.workflow_fields = {}
        self.refresh_fields = {}
        self.codeql_sha = NEW
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
        if path == '/actions/workflows/42':
            return dict(dict(id=42, path=release.CODEQL_PATH, name='CodeQL', state='active'),
                        **self.workflow_fields)
        if path.startswith('/actions/runs?'):
            self.codeql_sha = path.split('head_sha=')[1].split('&')[0]
            return {'workflow_runs': [self.codeql_run(), *self.codeql_more]}
        if path.startswith('/actions/runs/99/attempts/'):
            attempt = int(path.split('/')[5])
            return {'jobs': [dict(dict(name=name, run_id=99, run_attempt=attempt,
                head_sha=self.codeql_sha, head_branch='main', status='completed', conclusion='success'),
                **self.job_fields) for name in self.job_names]}
        if path == '/actions/runs/99':
            return dict(self.codeql_run(), **self.refresh_fields)
        if '/actions/workflows/' in path:
            workflow = path.split('/')[3]
            sha = path.split('head_sha=')[1].split('&')[0]
            row = dict(id=1, run_attempt=1, head_sha=sha, event='push', head_branch='main',
                       head_repository={'full_name': REPO}, status='completed',
                       conclusion=self.bad.get(workflow, 'success'))
            row.update(self.bad.get('run_fields', {}))
            return {'workflow_runs': [row, *self.more_runs]}
        raise AssertionError(path)

    def codeql_run(self):
        return dict(dict(id=99, workflow_id=42, run_attempt=1, path=release.CODEQL_PATH,
            name='Push on main', event='dynamic', head_sha=self.codeql_sha, head_branch='main',
            head_repository={'full_name': REPO}, repository={'full_name': REPO},
            status='completed', conclusion='success'), **self.codeql_fields)


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


@pytest.mark.parametrize('fields', [{'path': '.github/workflows/codeql.yml'},
    {'event': 'push'}, {'conclusion': 'neutral'}, {'head_sha': OTHER},
    {'head_branch': 'feature'}, {'head_repository': {'full_name': 'fork/dashboard'}},
    {'repository': {'full_name': 'fork/dashboard'}}, {'status': 'in_progress'},
    {'conclusion': 'failure'}, {'conclusion': 'skipped'}, {'conclusion': None}])
def test_missing_spoofed_or_non_success_codeql_blocks(fields):
    api = Fake()
    api.codeql_fields = fields
    assert not ready(api)['ready']
    assert not api.writes


def test_every_codeql_category_must_succeed():
    api = Fake()
    api.job_fields = {'conclusion': 'failure'}
    assert not ready(api)['ready']


def test_real_default_setup_shape_passes_without_any_aggregate_check():
    report = ready(Fake())
    assert report['ready'] and report['blockers'] == []
    assert report['codeql'] == dict(ready=True, reason='VERIFIED', run_id=99,
        run_attempt=1, workflow_id=42, required_jobs=list(release.CODEQL_JOBS), missing_or_failed_jobs=[])


@pytest.mark.parametrize('names', [[], list(release.CODEQL_JOBS[:-1]),
    [*release.CODEQL_JOBS, release.CODEQL_JOBS[0]], ['CodeQL']])
def test_missing_or_duplicate_languages_block(names):
    api = Fake()
    api.job_names = names
    assert not ready(api)['ready']


@pytest.mark.parametrize('fields', [{'run_attempt': 2}, {'run_id': 100}, {'head_sha': OTHER},
    {'head_branch': 'feature'}, {'status': 'in_progress'}, {'conclusion': 'neutral'},
    {'conclusion': 'skipped'}, {'conclusion': None}])
def test_wrong_attempt_or_non_success_analysis_jobs_block(fields):
    api = Fake()
    api.job_fields = fields
    assert not ready(api)['ready']


@pytest.mark.parametrize('fields', [{'path': '.github/workflows/codeql.yml'},
    {'id': 43}, {'state': 'disabled_manually'}])
def test_managed_workflow_metadata_is_required(fields):
    api = Fake()
    api.workflow_fields = fields
    assert ready(api)['codeql']['reason'] == 'MANAGED_WORKFLOW_INVALID'


def test_latest_codeql_run_failure_and_rerun_races_block():
    api = Fake()
    api.codeql_more = [dict(api.codeql_run(), id=100, conclusion='failure')]
    assert ready(api)['codeql']['reason'] == 'RUN_NOT_SUCCESSFUL'
    api.codeql_more = [dict(api.codeql_run(), run_attempt=2, conclusion='failure')]
    assert ready(api)['codeql']['reason'] == 'RUN_NOT_SUCCESSFUL'
    api.codeql_more = []
    api.refresh_fields = {'run_attempt': 2, 'status': 'in_progress', 'conclusion': None}
    assert ready(api)['codeql']['reason'] == 'RUN_CHANGED_DURING_VERIFICATION'


def test_new_codeql_run_appearing_during_jobs_fetch_blocks():
    api = Fake()
    original = api.call
    def call(path, **kwargs):
        result = original(path, **kwargs)
        if '/attempts/' in path:
            api.codeql_more = [dict(api.codeql_run(), id=100, status='in_progress', conclusion=None)]
        return result
    api.call = call
    assert ready(api)['codeql']['reason'] == 'NEWER_RUN_REQUIRES_VERIFICATION'


def test_codeql_attempt_endpoint_is_pinned_and_new_successful_attempt_passes():
    api = Fake()
    api.codeql_fields = {'run_attempt': 2}
    calls = []
    original = api.call
    def call(path, **kwargs):
        calls.append(path)
        return original(path, **kwargs)
    api.call = call
    assert ready(api)['ready']
    assert any('/runs/99/attempts/2/jobs?' in path for path in calls)
    assert not any('check-runs' in path for path in calls)


@pytest.mark.parametrize('value', [None, '42', True, 0, -1])
def test_invalid_codeql_identity_never_reaches_jobs(value):
    api = Fake()
    api.codeql_fields = {'workflow_id': value}
    with pytest.raises(release.ReleaseError, match='CODEQL_IDENTITY_INVALID'):
        ready(api)


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
    assert 'CodeQL, codeql]' in source
    assert "github.event.workflow_run.event == 'dynamic'" in source
    assert "github.event.workflow_run.head_branch == 'main'" in source
