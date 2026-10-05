"""Exact-commit dashboard release policy; unrelated to model authorization.

All writes require explicit publication, repository authorization and freshly
verified GitHub results. No deployment, broker or database credentials are used.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SHA = re.compile(r'[0-9a-f]{40}')
WORKFLOWS = ('quality.yml', 'resilience.yml')
CODEQL_PATH = 'dynamic/github-code-scanning/codeql'
CODEQL_JOBS = ('Analyze (actions)', 'Analyze (javascript-typescript)', 'Analyze (python)')
RELEASE = 'heads/release'
VERIFIED = 'tags/dashboard-verified/'


class ReleaseError(ValueError):
    """Fixed, non-sensitive failure codes suitable for CI output."""


class API(Protocol):
    def call(self, path: str, *, method: str = 'GET', data: Any = None) -> Any: ...


class GitHub:
    """Bounded authenticated calls to GitHub only; never print response bodies."""
    def __init__(self, repository: str, token: str) -> None:
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository) or not token:
            raise ReleaseError('RELEASE_API_CONFIGURATION_REQUIRED')
        self.base = 'https://api.github.com/repos/' + repository
        self.token = token

    def call(self, path: str, *, method: str = 'GET', data: Any = None) -> Any:
        if not path.startswith('/') or '..' in path:
            raise ReleaseError('RELEASE_API_PATH_INVALID')
        body = None if data is None else json.dumps(data).encode()
        request = Request(self.base + path, data=body, method=method, headers={
            'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read(4 * 1024 * 1024))
        except HTTPError as exc:
            if exc.code == 404 and method == 'GET' and path.startswith('/git/ref/'):
                return None
            raise ReleaseError('RELEASE_API_FAILED') from None
        except Exception:
            raise ReleaseError('RELEASE_API_FAILED') from None


def commit(value: Any) -> str:
    """Require a full immutable commit identity, never a branch or shell fragment."""
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise ReleaseError('FULL_COMMIT_SHA_REQUIRED')
    return value


def reference(api: API, name: str) -> str | None:
    row = api.call('/git/ref/' + name)
    if row is None:
        return None
    if row['object']['type'] != 'commit':
        raise ReleaseError('RELEASE_REFERENCE_NOT_COMMIT')
    return commit(row['object']['sha'])


def pages(api: API, path: str, key: str) -> list[dict[str, Any]]:
    """Pagination is mandatory; missing or excessive results fail closed."""
    result: list[dict[str, Any]] = []
    for page in range(1, 11):
        separator = '&' if '?' in path else '?'
        payload = api.call(f'{path}{separator}per_page=100&page={page}')
        rows = payload[key]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ReleaseError('RELEASE_CHECK_RESPONSE_INVALID')
        result.extend(rows)
        if len(rows) < 100:
            return result
    raise ReleaseError('RELEASE_CHECK_PAGINATION_LIMIT')


def codeql_result(api: API, repository: str, sha: str) -> dict[str, Any]:
    """Verify GitHub-managed default setup, not a similarly named YAML job.

    The managed path and dynamic event were verified against this repository's
    public API. A provider metadata change fails closed and needs policy review.
    All three installed languages are mandatory; no aggregate PR check is needed.
    """
    commit(sha)
    rows = pages(api, f'/actions/runs?head_sha={sha}&event=dynamic&branch=main', 'workflow_runs')
    matching = [row for row in rows if row.get('path') == CODEQL_PATH
                and row.get('head_sha') == sha and row.get('event') == 'dynamic'
                and row.get('head_branch') == 'main'
                and row.get('head_repository', {}).get('full_name') == repository
                and row.get('repository', {}).get('full_name') == repository]
    latest = max(matching, key=lambda row: (row['id'], row.get('run_attempt', 1)), default=None)
    report: dict[str, Any] = dict(ready=False, reason='MANAGED_RUN_MISSING',
                                 required_jobs=list(CODEQL_JOBS))
    if latest is None:
        return report
    run_id, attempt, workflow_id = (latest.get(key) for key in ('id', 'run_attempt', 'workflow_id'))
    if any(type(value) is not int or value <= 0 for value in (run_id, attempt, workflow_id)):
        raise ReleaseError('CODEQL_IDENTITY_INVALID')
    report.update(run_id=run_id, run_attempt=attempt, workflow_id=workflow_id)
    workflow = api.call(f'/actions/workflows/{workflow_id}')
    if workflow.get('id') != workflow_id or workflow.get('path') != CODEQL_PATH or workflow.get('state') != 'active':
        return dict(report, reason='MANAGED_WORKFLOW_INVALID')
    if latest.get('status') != 'completed' or latest.get('conclusion') != 'success':
        return dict(report, reason='RUN_NOT_SUCCESSFUL')
    jobs = pages(api, f'/actions/runs/{run_id}/attempts/{attempt}/jobs', 'jobs')
    # Reject duplicates and unexpected failed/skipped jobs as well as missing
    # languages. Never mix jobs across attempts, SHAs or branches.
    valid = bool(jobs) and all(row.get('run_id') == run_id and row.get('run_attempt') == attempt
                              and row.get('head_sha') == sha and row.get('head_branch') == 'main'
                              and row.get('status') == 'completed' and row.get('conclusion') == 'success'
                              for row in jobs)
    failed = [name for name in CODEQL_JOBS if len([row for row in jobs if row.get('name') == name]) != 1
              or any(row.get('name') == name and (row.get('status') != 'completed'
                     or row.get('conclusion') != 'success') for row in jobs)]
    report['missing_or_failed_jobs'] = failed
    if not valid or failed:
        return dict(report, reason='ANALYSIS_JOBS_NOT_VERIFIED')
    # A rerun can begin while jobs are fetched. Re-read the run and discover any
    # newer run before accepting this attempt's now-historical success.
    refreshed = api.call(f'/actions/runs/{run_id}')
    identity = ('id', 'workflow_id', 'run_attempt', 'head_sha', 'head_branch', 'event',
                'path', 'head_repository', 'repository', 'status', 'conclusion')
    if any(refreshed.get(key) != latest.get(key) for key in identity):
        return dict(report, reason='RUN_CHANGED_DURING_VERIFICATION')
    newest = pages(api, f'/actions/runs?head_sha={sha}&event=dynamic&branch=main', 'workflow_runs')
    if any(row.get('path') == CODEQL_PATH and row.get('head_sha') == sha
           and row.get('event') == 'dynamic' and row.get('head_branch') == 'main'
           and row.get('head_repository', {}).get('full_name') == repository
           and row.get('repository', {}).get('full_name') == repository
           and (row['id'], row.get('run_attempt', 1)) > (run_id, attempt) for row in newest):
        return dict(report, reason='NEWER_RUN_REQUIRES_VERIFICATION')
    return dict(report, ready=True, reason='VERIFIED')


def blockers(api: API, repository: str, sha: str, *, diagnostics: dict[str, Any] | None = None) -> list[str]:
    """Latest push attempt of each mandatory workflow, plus real CodeQL results.

    PR results, skipped/neutral checks and old successful reruns never substitute
    for the required exact-SHA main push. CodeQL uses its managed dynamic workflow
    identity and explicit per-language jobs, not an aggregate pull-request check.
    """
    commit(sha)
    missing = []
    for workflow in WORKFLOWS:
        rows = pages(api, f'/actions/workflows/{workflow}/runs?head_sha={sha}&event=push&branch=main',
                     'workflow_runs')
        matching = [row for row in rows if row.get('head_sha') == sha
                    and row.get('event') == 'push' and row.get('head_branch') == 'main'
                    and row.get('head_repository', {}).get('full_name') == repository]
        latest = max(matching, key=lambda row: (row['id'], row.get('run_attempt', 1)), default=None)
        if latest is None or latest.get('status') != 'completed' or latest.get('conclusion') != 'success':
            missing.append(workflow)
    codeql = codeql_result(api, repository, sha)
    if diagnostics is not None:
        diagnostics['codeql'] = codeql
    if not codeql['ready']:
        missing.append('CodeQL')
    return missing


def plan(api: API, repository: str, mode: str, *, enabled: str,
         rollback_sha: str = '', confirmed: Any = False) -> dict[str, Any]:
    """Read-only plan. Rollback requires pausing promotion and explicit bool True."""
    if mode not in ('promote', 'preview', 'rollback'):
        raise ReleaseError('RELEASE_MODE_INVALID')
    head = reference(api, 'heads/main')
    if head is None:
        raise ReleaseError('MAIN_REFERENCE_MISSING')
    current = reference(api, RELEASE)
    if mode == 'rollback':
        if enabled != 'false' or confirmed is not True:
            raise ReleaseError('ROLLBACK_REQUIRES_PAUSE_AND_CONFIRMATION')
        sha = commit(rollback_sha)
        if current is None or reference(api, VERIFIED + sha) != sha:
            raise ReleaseError('ROLLBACK_TARGET_NOT_VERIFIED')
        if sha != current and api.call(f'/compare/{sha}...{current}')['status'] != 'ahead':
            raise ReleaseError('ROLLBACK_TARGET_NOT_ANCESTOR')
    else:
        sha = head
        if mode == 'promote' and enabled != 'true':
            return dict(status='PROMOTION_DISABLED', ready=False, sha=sha, previous=current)
        if current is not None and sha != current:
            if api.call(f'/compare/{current}...{sha}')['status'] != 'ahead':
                raise ReleaseError('PROMOTION_NOT_FAST_FORWARD')
    diagnostics: dict[str, Any] = {}
    blocked = blockers(api, repository, sha, diagnostics=diagnostics)
    return dict(status='CHECKS_PENDING_OR_FAILED' if blocked else 'READY', ready=not blocked,
                sha=sha, previous=current, main=head, blockers=blocked, **diagnostics)


def fingerprint(root: Path) -> str:
    """Read the candidate's own manifest as data, including on historical rollback.

    Never import or execute candidate app code to calculate its expected hash.
    Matches the existing LF-normalized equity fingerprint; it is an operator
    report, never an automatic replacement for the external Streamlit secret.
    """
    tree = ast.parse((root / 'equity_runtime_health.py').read_text(encoding='utf-8-sig'))
    values = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == 'RELEASE_FILES' for target in node.targets)]
    if len(values) != 1 or not isinstance(values[0], tuple) or not values[0]:
        raise ReleaseError('FINGERPRINT_MANIFEST_INVALID')
    names = values[0]
    if any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_]+\.py', name) for name in names):
        raise ReleaseError('FINGERPRINT_MANIFEST_INVALID')
    digest = hashlib.sha256()
    for name in sorted(names):
        digest.update(name.encode() + b'\0' + (root / name).read_bytes().replace(b'\r\n', b'\n') + b'\0')
    return digest.hexdigest()


def publish(api: API, repository: str, expected: dict[str, Any], mode: str, *, enabled: str,
            rollback_sha: str = '', confirmed: Any = False) -> dict[str, Any]:
    """Revalidate immediately before an atomic ref update, without creating a commit."""
    fresh = plan(api, repository, mode, enabled=enabled, rollback_sha=rollback_sha, confirmed=confirmed)
    if not fresh['ready'] or any(fresh.get(key) != expected.get(key) for key in ('sha', 'previous', 'main')):
        raise ReleaseError('RELEASE_STATE_CHANGED')
    sha = fresh['sha']
    if sha == fresh['previous']:
        return dict(fresh, status='ALREADY_RELEASED')
    marker = reference(api, VERIFIED + sha)
    if marker not in (None, sha):
        raise ReleaseError('VERIFIED_MARKER_CONFLICT')
    if marker is None:
        api.call('/git/refs', method='POST', data={'ref': 'refs/' + VERIFIED + sha, 'sha': sha})
    if fresh['previous'] is None:
        api.call('/git/refs', method='POST', data={'ref': 'refs/' + RELEASE, 'sha': sha})
    else:
        api.call('/git/refs/' + RELEASE, method='PATCH', data={'sha': sha, 'force': mode == 'rollback'})
    if reference(api, RELEASE) != sha:
        raise ReleaseError('RELEASE_UPDATE_UNVERIFIED')
    return dict(fresh, status='ROLLED_BACK' if mode == 'rollback' else 'PROMOTED')


def main(argv: list[str] | None = None) -> int:
    """CI adapter: read-only by default; authorization and tokens only via env."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--candidate-root', type=Path)
    args = parser.parse_args(argv)
    try:
        event = os.environ.get('EVENT_NAME', '')
        if event not in ('workflow_run', 'workflow_dispatch'):
            raise ReleaseError('RELEASE_EVENT_FORBIDDEN')
        if os.environ.get('GITHUB_REF') not in ('refs/heads/main', 'refs/heads/release'):
            raise ReleaseError('RELEASE_CONTROLLER_BRANCH_FORBIDDEN')
        repository = os.environ['GITHUB_REPOSITORY']
        api = GitHub(repository, os.environ['GH_TOKEN'])
        mode = 'promote' if event == 'workflow_run' else os.environ.get('REQUESTED_MODE', 'preview')
        enabled = os.environ.get('RELEASE_ENABLED', '')
        confirmed = json.loads(os.environ.get('CONFIRM_ROLLBACK_JSON', 'false'))
        rollback = os.environ.get('ROLLBACK_SHA', '')
        deadline = time.monotonic() + (900 if event == 'workflow_run' and not args.publish else 0)
        expected_sha = os.environ.get('EXPECTED_CANDIDATE_SHA', '')
        expected_previous = os.environ.get('EXPECTED_PREVIOUS_SHA', '')
        initial = reference(api, 'heads/main')
        while True:
            report = plan(api, repository, mode, enabled=enabled, rollback_sha=rollback, confirmed=confirmed)
            if mode != 'rollback' and report['sha'] != initial:
                report.update(status='SUPERSEDED', ready=False)
                break
            if report['ready'] or report['status'] == 'PROMOTION_DISABLED' or time.monotonic() >= deadline:
                break
            time.sleep(15)
        if args.publish:
            if mode == 'preview' or args.candidate_root is None or not report['ready']:
                raise ReleaseError('PUBLICATION_NOT_AUTHORIZED')
            if report['sha'] != commit(expected_sha) or (report['previous'] or '') != expected_previous:
                raise ReleaseError('RELEASE_STATE_CHANGED')
            # workflow_run uses the default-branch controller, which can differ
            # from the candidate. It too must be checked before receiving writes.
            if blockers(api, repository, commit(os.environ.get('GITHUB_SHA', ''))):
                raise ReleaseError('RELEASE_CONTROLLER_NOT_VERIFIED')
            # Fingerprint must be calculable before any write.
            code_hash = fingerprint(args.candidate_root)
            report = publish(api, repository, report, mode, enabled=enabled,
                             rollback_sha=rollback, confirmed=confirmed)
            report['EXPECTED_EQUITY_CODE_SHA256'] = code_hash
        print(json.dumps(report, sort_keys=True))
        if not args.publish and os.environ.get('GITHUB_OUTPUT'):
            with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
                output.write(f"ready={'true' if report['ready'] and mode != 'preview' else 'false'}\n")
                output.write(f"sha={commit(report['sha'])}\nprevious={report['previous'] or ''}\n")
        return 0
    except Exception as exc:
        code = str(exc) if type(exc) is ReleaseError else 'RELEASE_FAILED'
        print(json.dumps({'status': code, 'ready': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
