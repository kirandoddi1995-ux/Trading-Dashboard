"""Owner-approved staged historical acquisition. Preview is inert; never orders.

Reuses the reviewed transport, decoder and local guards. Old attempts/bindings
are never rewritten. Every incomplete claim blocks continuation, including an
unknown result or cancellation before HTTP. Local hashes are not custody proof.
"""
from __future__ import annotations

from datetime import date
from datetime import datetime, timezone
import html
from itertools import islice
import json
from pathlib import Path
import re
import shutil
import time
from typing import Any, Callable

import equity_staged_request as old
import equity_private_acquire as acq
from equity_staged_request import Context, StageBlocked
from equity_daily_ingest import MAX_BYTES, decode_daily

FORMAT = 'equity-staged-campaign-v2'
NAME = 'equity_request_campaign.py'
ACK_PREFIX = 'APPROVE_BINDING_SHA256:'
FLAGS = {'training_eligible': False, 'promotion_authorised': False,
         'performance_claim_verified': False, 'custody_verified': False}


def _source(ctx: Context) -> dict[str, str]:
    values: dict[str, str] = old.source_binding(ctx, ctx.reviewed_commit)
    path = ctx.source / NAME
    old._path(path)
    if not path.is_file() or not 0 < path.stat().st_size < 2 * 1024 * 1024:
        raise StageBlocked('SOURCE_REVIEW_REQUIRED')
    values[NAME] = old._hash(path.read_bytes())
    return values


def _history(ctx: Context, roots: list[Path]) -> dict[str, Any]:
    if len(roots) != 2:
        raise StageBlocked('LEGACY_REVIEW_REQUIRED')
    # Validate the supplied spelling BEFORE resolving: links/traversal stay rejected.
    for root in roots:
        old._path(root)
    canonical = sorted((root.resolve(strict=True) for root in roots), key=str)
    if canonical[0] == canonical[1]:
        raise StageBlocked('LEGACY_REVIEW_REQUIRED')
    previous = [old.predecessor(ctx, root) for root in canonical]
    if previous[0]['sidecar_sha256']['intent.json'] == previous[1]['sidecar_sha256']['intent.json']:
        raise StageBlocked('LEGACY_REVIEW_REQUIRED')
    # An observation, not an invented provider receipt or retained third body.
    external = {'basis': 'OWNER_REPORTED_EXTERNAL_DIAGNOSTIC_NO_RETAINED_BODY',
                'consumed_requests': 1, 'http_status_owner_reported': 200,
                'window': acq.windows()[0]._asdict(), 'original_retained': False,
                'dispatch_time': 'NOT_ESTABLISHED', 'user_agent': acq.USER_AGENT}
    return {'previous': previous, 'external': [external],
            'consumed_requests': sum(p['consumed_requests'] for p in previous)
                + external['consumed_requests']}


def _checked_history(ctx: Context, value: Any) -> dict[str, Any]:
    if type(value) is not dict or type(value.get('previous')) is not list:
        raise StageBlocked('BINDING_REVIEW_REQUIRED')
    try:
        roots = [Path(item['root']) for item in value['previous']]
    except (KeyError, TypeError):
        raise StageBlocked('BINDING_REVIEW_REQUIRED') from None
    actual = _history(ctx, roots)
    if old._canonical(actual) != old._canonical(value):
        raise StageBlocked('LEGACY_REVIEW_REQUIRED')
    return actual


def _require_absent(path: Path) -> None:
    old._path(path)
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise StageBlocked('INCOMPLETE_OR_FAILED_STAGE_NO_RETRY')


def _existing(ctx: Context, history: dict[str, Any], *, active_stage: int | None = None) -> tuple[list[dict[str, Any]], str]:
    if not ctx.state.exists():
        return [], 'ABSENT'
    old._path(ctx.state)
    children = list(islice(ctx.state.iterdir(), len(acq.windows()) + 2))
    allowed = {'campaign-history.json'} | {f'stage-{n:02d}' for n in range(1, len(acq.windows()) + 1)}
    if len(children) > len(allowed) or any(p.name not in allowed for p in children):
        raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
    try:
        genesis, genesis_sha = old._read(ctx.state / 'campaign-history.json')
    except FileNotFoundError:
        raise StageBlocked('PARTIAL_CAMPAIGN_INITIALIZATION_NO_RETRY') from None
    expected = {'format': FORMAT, 'campaign': old.CAMPAIGN, 'history': history}
    if old._canonical(genesis) != old._canonical(expected):
        raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
    retained: list[dict[str, Any]] = []
    chain = [genesis_sha]
    missing = False
    stage_count = 0
    for number in range(1, len(acq.windows()) + 1):
        path = ctx.state / f'stage-{number:02d}'
        if number == active_stage:
            # Only the caller's already-exclusive current claim may be incomplete.
            old._path(path)
            if not path.is_dir():
                raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
            _require_absent(path / 'complete')
            _require_absent(path / 'failure.json')
            continue
        if not path.exists():
            missing = True
            continue
        if missing:
            raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
        try:
            (path / 'failure.json').lstat()
        except FileNotFoundError:
            pass
        else:
            raise StageBlocked('INCOMPLETE_OR_FAILED_STAGE_NO_RETRY')
        old._path(path / 'complete')
        if not (path / 'complete').is_dir() or next((path / 'complete').iterdir(), None) is not None:
            raise StageBlocked('INCOMPLETE_OR_FAILED_STAGE_NO_RETRY')
        try:
            reservation, reservation_sha = old._read(path / 'reservation.json')
            result, result_sha = old._read(path / 'result.json')
        except FileNotFoundError:
            raise StageBlocked('INCOMPLETE_OR_FAILED_STAGE_NO_RETRY') from None
        commit = reservation.get('execution_commit')
        if type(commit) is not str or re.fullmatch('[0-9a-f]{40}', commit) is None:
            raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
        approved, approved_sha = old._read(ctx.approval_parent / f'campaign-stage-{number:02d}-{commit}.json')
        if (reservation.get('binding_sha256') != approved_sha
                or approved.get('execution_commit') != commit
                or approved.get('format') != FORMAT or approved.get('campaign') != old.CAMPAIGN
                or approved.get('approval_granted') is not False or approved.get('retry_authorised') is not False
                or old._canonical(approved.get('history')) != old._canonical(history)
                or any(reservation.get(key) != approved.get(key) for key in (
                    'stage_number', 'stage_allowance', 'prior_consumed_requests',
                    'stage_cumulative_maximum', 'previous_state_sha256', 'windows', 'source_sha256'))
                or reservation.get('credentials_saved') is not False
                or type(reservation.get('runtime_versions')) is not dict
                or reservation['runtime_versions'] != result.get('runtime_versions')
                or reservation.get('user_agent') != acq.USER_AGENT):
            raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
        count = reservation.get('stage_allowance')
        remaining = len(acq.windows()) - len(retained)
        if (type(count) is not int or not 1 <= count <= remaining
                or reservation.get('format') != FORMAT
                or type(reservation.get('stage_number')) is not int
                or reservation['stage_number'] != number
                or reservation.get('history_sha256') != old._hash(old._canonical(history))
                or reservation.get('previous_state_sha256') != ('ABSENT' if not stage_count
                    else old._hash(old._canonical(chain)))
                or old._canonical(reservation.get('windows')) != old._canonical(
                    [w._asdict() for w in acq.windows()[len(retained):len(retained) + count]])
                or reservation.get('prior_consumed_requests') != history['consumed_requests'] + len(retained)
                or reservation.get('stage_cumulative_maximum') != history['consumed_requests'] + len(retained) + count
                or result.get('status') != 'CAMPAIGN_STAGE_RETAINED_NOT_DATA_ADMISSION'
                or result.get('reservation_sha256') != reservation_sha
                or type(result.get('request_attempts')) is not int or result['request_attempts'] != count
                or type(result.get('retained')) is not list or len(result['retained']) != count):
            raise StageBlocked('INCOMPLETE_OR_FAILED_STAGE_NO_RETRY')
        for key, expected_count in (('stage_number', number), ('stage_allowance', count),
                ('prior_consumed_requests', history['consumed_requests'] + len(retained)),
                ('known_cumulative_attempts', history['consumed_requests'] + len(retained) + count),
                ('retained_windows_total', len(retained) + count)):
            if type(result.get(key)) is not int or result[key] != expected_count:
                raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
        if (result.get('input_origin') != reservation.get('input_origin')
                or result.get('reservation_held') is not True or result.get('retry_authorised') is not False
                or any(result.get(flag) is not False for flag in FLAGS)):
            raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
        for item, window in zip(result['retained'], acq.windows()[len(retained):len(retained) + count]):
            if (type(item) is not dict or type(item.get('ordinal')) is not int
                    or item['ordinal'] != window.ordinal or type(item.get('rows')) is not int
                    or not 1 <= item['rows'] <= 1200):
                raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
            for key in ('first_date', 'last_date'):
                value = item.get(key)
                if type(value) is not str or re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) is None:
                    raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
                date.fromisoformat(value)
                if not window.start <= value <= window.end:
                    raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
            if (item['first_date'] > item['last_date'] or item.get('input_origin') != result['input_origin']
                    or item.get('input_origin') not in
                    ('NATIVE_TLS_NOT_PROVIDER_SIGNATURE', 'INJECTED_SYNTHETIC_NOT_MARKET_EVIDENCE')):
                raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
            for key, name, bound in (('original', window.filename, MAX_BYTES),
                    ('decoded', f'{window.ordinal:03d}-decoded.json', 8 * 1024 * 1024)):
                identity = item.get(key)
                if (type(identity) is not dict or set(identity) != {'name', 'bytes', 'sha256'}
                        or identity['name'] != name or type(identity['bytes']) is not int
                        or not 0 < identity['bytes'] <= bound):
                    raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
                acq._verify_files(path, [identity])
            original_bytes = (path / item['original']['name']).read_bytes()
            decoded = decode_daily(original_bytes, instrument_key=window.instrument_key,
                start=window.start, end=window.end)
            dates = [row['date'] for row in decoded['rows']]
            if ((path / item['decoded']['name']).read_bytes() != old._canonical(decoded)
                    or item['rows'] != decoded['row_count']
                    or item['first_date'] != min(dates) or item['last_date'] != max(dates)):
                raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
            retained.append(item)
        reports = result.get('reports')
        if type(reports) is not list or len(reports) != 2:
            raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
        for identity, name in zip(reports, ('coverage.json', 'coverage.html')):
            if (type(identity) is not dict or set(identity) != {'name', 'bytes', 'sha256'}
                    or identity['name'] != name or type(identity['bytes']) is not int
                    or not 0 < identity['bytes'] <= 65536):
                raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
        acq._verify_files(path, reports)
        coverage = _coverage(retained)
        if ((path / 'coverage.json').read_bytes() != old._canonical(coverage)
                or (path / 'coverage.html').read_bytes() != _coverage_html(coverage)):
            raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
        chain.extend([reservation_sha, result_sha])
        stage_count += 1
    if not stage_count and active_stage != 1:
        raise StageBlocked('PARTIAL_CAMPAIGN_INITIALIZATION_NO_RETRY')
    return retained, old._hash(old._canonical(chain)) if stage_count else 'ABSENT'


def _binding_path(ctx: Context, number: int) -> Path:
    if type(number) is not int or not 1 <= number <= len(acq.windows()):
        raise StageBlocked('STAGE_NUMBER_REVIEW_REQUIRED')
    return Path(ctx.approval_parent) / f'campaign-stage-{number:02d}-{ctx.reviewed_commit}.json'


def _next_number(ctx: Context) -> int:
    if not ctx.state.exists():
        return 1
    for number in range(1, len(acq.windows()) + 1):
        if not (ctx.state / f'stage-{number:02d}').exists():
            return number
    raise StageBlocked('CAMPAIGN_COMPLETE_NO_NEW_REQUESTS')


def prepare(ctx: Context, roots: list[Path], allowance: int, *, confirm_history: bool) -> dict[str, Any]:
    if confirm_history is not True:
        raise StageBlocked('OWNER_HISTORY_ATTESTATION_REQUIRED')
    old._context(ctx)
    sources = _source(ctx)
    history = _history(ctx, roots)
    retained, state_sha = _existing(ctx, history)
    if type(allowance) is not int or not 1 <= allowance <= len(acq.windows()) - len(retained):
        raise StageBlocked('STAGE_ALLOWANCE_REVIEW_REQUIRED')
    if not retained and allowance != 1:
        raise StageBlocked('FIRST_STAGE_ONE_REQUEST_REQUIRED')
    number = _next_number(ctx)
    path = _binding_path(ctx, number)
    if path.exists():
        raise StageBlocked('OWNER_BINDING_ALREADY_EXISTS')
    windows = acq.windows()[len(retained):len(retained) + allowance]
    value = {'format': FORMAT, 'campaign': old.CAMPAIGN, 'execution_commit': ctx.reviewed_commit,
        'source_sha256': sources, 'history': history, 'previous_state_sha256': state_sha,
        'stage_number': number, 'stage_allowance': allowance,
        'prior_consumed_requests': history['consumed_requests'] + len(retained),
        'stage_cumulative_maximum': history['consumed_requests'] + len(retained) + allowance,
        'windows': [w._asdict() for w in windows], 'approval_granted': False, 'retry_authorised': False}
    old._parents(ctx.approval_parent)
    acq._write(ctx.approval_parent, path.name, old._canonical(value))
    return {'status': 'CAMPAIGN_BINDING_PREPARED_NOT_APPROVED',
            'binding_sha256': old._hash(old._canonical(value)),
            **{key: value[key] for key in ('stage_number', 'prior_consumed_requests',
                'stage_allowance', 'stage_cumulative_maximum')},
            'new_request_attempts': 0, 'approval_granted': False}


def _coverage(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {'status': 'PRIVATE_COVERAGE_NOT_PERFORMANCE', 'retained_windows': len(items),
        'planned_windows': len(acq.windows()), 'rows': sum(item['rows'] for item in items),
        'windows': [{**{key: item[key] for key in ('ordinal', 'rows', 'first_date', 'last_date')},
                     'symbol': acq.windows()[item['ordinal'] - 1].symbol,
                     'requested_start': acq.windows()[item['ordinal'] - 1].start,
                     'requested_end': acq.windows()[item['ordinal'] - 1].end,
                     'original_sha256': item['original']['sha256']}
                    for item in items], 'exchange_calendar_verified': False,
        'corporate_actions_verified': False, 'price_adjustment_basis': 'NOT_ESTABLISHED',
        'missing_exchange_sessions': 'NOT_ESTABLISHED_WITHOUT_VERIFIED_CALENDAR',
        'input_origins': sorted({item['input_origin'] for item in items}),
        'baseline_evaluation': 'INSUFFICIENT_COHORT_INPUTS_AND_SOURCE_RECONCILIATION', **FLAGS}


def _coverage_html(coverage: dict[str, Any]) -> bytes:
    return ('<!doctype html><meta charset="utf-8"><title>Private equity coverage</title><h1>Coverage only — no accuracy claim</h1><pre>'
        + html.escape(json.dumps(coverage, indent=2)) + '</pre>').encode()


def execute(ctx: Context, number: int, ack: str, *,
            token_reader: Callable[[], str] = acq._hidden_token,
            fetch: Callable[[acq.Window, str], acq.Response] = acq._https_get,
            pause: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    if re.fullmatch(ACK_PREFIX + '[0-9a-f]{64}', ack) is None:
        raise StageBlocked('APPROVAL_ACK_REQUIRED')
    old._context(ctx)
    binding, digest = old._read(_binding_path(ctx, number))
    if ack != ACK_PREFIX + digest:
        raise StageBlocked('APPROVAL_ACK_REQUIRED')
    sources = _source(ctx)
    history = _checked_history(ctx, binding.get('history'))
    retained, state_sha = _existing(ctx, history)
    allowance = binding.get('stage_allowance')
    expected_keys = {'format', 'campaign', 'execution_commit', 'source_sha256', 'history',
        'previous_state_sha256', 'stage_number', 'stage_allowance', 'prior_consumed_requests',
        'stage_cumulative_maximum', 'windows', 'approval_granted', 'retry_authorised'}
    if (set(binding) != expected_keys or binding['format'] != FORMAT
            or binding['campaign'] != old.CAMPAIGN or binding['execution_commit'] != ctx.reviewed_commit
            or binding['source_sha256'] != sources or binding['previous_state_sha256'] != state_sha
            or type(allowance) is not int or not 1 <= allowance <= len(acq.windows()) - len(retained)
            or (not retained and allowance != 1)
            or type(binding['stage_number']) is not int or binding['stage_number'] != number
            or number != _next_number(ctx) or binding['approval_granted'] is not False
            or binding['retry_authorised'] is not False
            or any(type(binding[key]) is not int or binding[key] != expected for key, expected in (
                ('prior_consumed_requests', history['consumed_requests'] + len(retained)),
                ('stage_cumulative_maximum', history['consumed_requests'] + len(retained) + allowance)))
            or old._canonical(binding['windows']) != old._canonical(
                [w._asdict() for w in acq.windows()[len(retained):len(retained) + allowance]])):
        raise StageBlocked('BINDING_REVIEW_REQUIRED')
    profile = acq._runtime_profile()
    if shutil.disk_usage(ctx.local).free < acq.MIN_FREE_BYTES:
        raise StageBlocked('LOCAL_SPACE_REVIEW_REQUIRED')
    if state_sha == 'ABSENT':
        old._parents(ctx.state.parent)
        try:
            ctx.state.mkdir()
        except FileExistsError:
            raise StageBlocked('CAMPAIGN_STATE_CHANGED_REVIEW') from None
        acq._write(ctx.state, 'campaign-history.json', old._canonical(
            {'format': FORMAT, 'campaign': old.CAMPAIGN, 'history': history}))
    claim = ctx.state / f'stage-{number:02d}'
    origin = ('NATIVE_TLS_NOT_PROVIDER_SIGNATURE' if fetch is acq._https_get
              else 'INJECTED_SYNTHETIC_NOT_MARKET_EVIDENCE')
    reservation = {'format': FORMAT, 'execution_commit': ctx.reviewed_commit,
        'stage_number': number, 'binding_sha256': digest,
        'stage_allowance': allowance, 'prior_consumed_requests': binding['prior_consumed_requests'],
        'stage_cumulative_maximum': binding['stage_cumulative_maximum'],
        'previous_state_sha256': state_sha, 'windows': binding['windows'],
        'history_sha256': old._hash(old._canonical(history)), 'source_sha256': sources,
        'runtime_versions': profile, 'user_agent': acq.USER_AGENT, 'input_origin': origin,
        'started_utc_unattested': datetime.now(timezone.utc).isoformat(), 'credentials_saved': False}
    old.reserve(claim, old._canonical(reservation))  # Exclusive claim + fsync/readback BEFORE hidden input.
    reservation_sha = old._hash(old._canonical(reservation))
    attempts = 0
    observed_status: int | None = None
    phase = 'HIDDEN_TOKEN'
    current: list[dict[str, Any]] = []
    safe_originals: list[dict[str, Any]] = []
    try:
        token = token_reader()
        if type(token) is not str or not 16 <= len(token) <= 8192 or any(not 33 <= ord(c) <= 126 for c in token):
            raise acq.StudyBlocked('STUDY_TOKEN_INPUT_REVIEW')
        for window in acq.windows()[len(retained):len(retained) + allowance]:
            phase = 'REQUEST'
            observed_status = None
            if sources != _source(ctx):
                raise StageBlocked('SOURCE_REVIEW_REQUIRED')
            # Hidden input/rate pauses may take time: recheck approval and the
            # completed prefix before EACH dispatch, without reusing the claim.
            latest_binding, latest_digest = old._read(_binding_path(ctx, number))
            if (latest_digest != digest or old._canonical(latest_binding) != old._canonical(binding)
                    or old._canonical(_checked_history(ctx, binding['history'])) != old._canonical(history)
                    or _existing(ctx, history, active_stage=number) != (retained, state_sha)
                    or old._read(claim / 'reservation.json')[1] != reservation_sha):
                raise StageBlocked('SOURCE_REVIEW_REQUIRED')
            if shutil.disk_usage(claim).free < acq.MIN_FREE_BYTES:
                raise StageBlocked('LOCAL_SPACE_REVIEW_REQUIRED')
            acq._write(claim, f'{window.ordinal:03d}-intent.json', old._canonical(window._asdict()))
            attempts += 1  # Unknown HTTP outcome consumes the reserved dispatch.
            response = fetch(window, token)
            if type(response.status) is int and 100 <= response.status <= 599:
                observed_status = response.status
            phase = 'RESPONSE_CHECK'
            if response.status != 200 or response.content_type.lower().split(';')[0].strip() != 'application/json':
                raise acq.StudyBlocked('STUDY_RESPONSE_REVIEW')
            if type(response.body) is not bytes or not 0 < len(response.body) <= MAX_BYTES:
                raise acq.StudyBlocked('STUDY_RESPONSE_BYTES_BOUND')
            acq._secret_screen(response.body, token)
            phase = 'DECODE'
            decoded = decode_daily(response.body, instrument_key=window.instrument_key,
                start=window.start, end=window.end)
            if sources != _source(ctx):
                raise StageBlocked('SOURCE_REVIEW_REQUIRED')
            phase = 'RETAIN'
            original = acq._write(claim, window.filename, response.body)
            safe_originals.append({'ordinal': window.ordinal, **original})
            derived = acq._write(claim, f'{window.ordinal:03d}-decoded.json', old._canonical(decoded))
            dates = [row['date'] for row in decoded['rows']]
            current.append({'ordinal': window.ordinal, 'rows': decoded['row_count'],
                'first_date': min(dates), 'last_date': max(dates), 'original': original,
                'decoded': derived, 'input_origin': origin})
            if attempts < allowance:
                pause(1.0)
        token = ''
        phase = 'COVERAGE_REPORT'
        coverage = _coverage(retained + current)
        reports = [acq._write(claim, 'coverage.json', old._canonical(coverage)),
            acq._write(claim, 'coverage.html', _coverage_html(coverage))]
        for item in current:
            acq._verify_files(claim, [item['original'], item['decoded']])
        result = {'status': 'CAMPAIGN_STAGE_RETAINED_NOT_DATA_ADMISSION',
            'reservation_sha256': reservation_sha, 'request_attempts': attempts,
            'prior_consumed_requests': binding['prior_consumed_requests'],
            'known_cumulative_attempts': binding['prior_consumed_requests'] + attempts,
            'stage_allowance': allowance, 'stage_number': number, 'retained': current,
            'runtime_versions': profile,
            'input_origin': origin,
            'retained_windows_total': len(retained) + len(current), 'reports': reports,
            'reservation_held': True, 'retry_authorised': False, **FLAGS}
        acq._write(claim, 'result.json', old._canonical(result))
        # Publication can succeed even if mkdir's acknowledgement raises. Resolve
        # that ambiguity by readback, never by repeating a request or deleting state.
        marker = claim / 'complete'
        _require_absent(marker)
        _require_absent(claim / 'failure.json')
        try:
            marker.mkdir()
        except OSError:
            old._path(marker)
            _require_absent(claim / 'failure.json')
            if (not marker.is_dir() or next(marker.iterdir(), None) is not None
                    or old._read(claim / 'result.json')[1] != old._hash(old._canonical(result))):
                raise
        old._path(marker)
        _require_absent(claim / 'failure.json')
        if not marker.is_dir() or next(marker.iterdir(), None) is not None:
            raise StageBlocked('CAMPAIGN_STATE_REVIEW_REQUIRED')
        return result
    except (Exception, KeyboardInterrupt) as exc:
        category = str(exc) if isinstance(exc, StageBlocked) else acq._category(exc)
        if category not in {'SOURCE_REVIEW_REQUIRED', 'LOCAL_SPACE_REVIEW_REQUIRED'} and isinstance(exc, StageBlocked):
            category = 'CAMPAIGN_LOCAL_REVIEW_REQUIRED'
        failure = {'status': 'CAMPAIGN_STAGE_BLOCKED_RESERVATION_HELD', 'stage': phase,
            'category': category, 'http_status': observed_status or acq.HTTP_REVIEW_STATUS.get(category),
            'request_attempts': attempts, 'stage_allowance': allowance, 'stage_number': number,
            'known_cumulative_attempts': binding['prior_consumed_requests'] + attempts,
            'reserved_cumulative_ceiling': binding['stage_cumulative_maximum'],
            'retained_windows_this_stage': len(current), 'reservation_held': True,
            'safe_originals_not_data_admission': safe_originals,
            'partial_artifacts_possible': True,
            'retry_authorised': False, 'raw_error_printed': False, **FLAGS}
        try:
            acq._write(claim, 'failure.json', old._canonical(failure))
        except Exception:
            pass
        return failure


def main(argv: list[str] | None = None) -> int:
    try:
        parser = old.Parser(add_help=False, allow_abbrev=False)
        parser.add_argument('--mode', choices=('preview', 'prepare', 'execute'), default='preview')
        parser.add_argument('--reviewed-commit')
        parser.add_argument('--previous-root', type=Path, action='append', default=[])
        parser.add_argument('--stage-allowance', type=int, default=1)
        parser.add_argument('--stage-number', type=int, default=1)
        parser.add_argument('--confirm-known-history', action='store_true')
        parser.add_argument('--approval-ack')
        args = parser.parse_args(argv)
        if args.mode == 'preview':
            print(json.dumps({'status': 'PREVIEW', 'network_requests': 0, 'credential_reads': 0,
                'writes': 0, 'approval_granted': False, 'default_stage_allowance': 1,
                'history_basis': 'TWO_VERIFIED_FAILURE_RECORDS_PLUS_OWNER_REPORTED_EXTERNAL_GET'}))
            return 0
        if args.mode == 'execute' and (args.approval_ack is None or re.fullmatch(ACK_PREFIX + '[0-9a-f]{64}', args.approval_ack) is None):
            raise StageBlocked('APPROVAL_ACK_REQUIRED')
        if args.mode == 'prepare' and not args.confirm_known_history:
            raise StageBlocked('OWNER_HISTORY_ATTESTATION_REQUIRED')
        ctx = old.native_context()
        if args.mode == 'prepare':
            if args.approval_ack is not None or args.reviewed_commit != ctx.reviewed_commit:
                raise StageBlocked('SOURCE_REVIEW_REQUIRED')
            result = prepare(ctx, args.previous_root, args.stage_allowance,
                             confirm_history=args.confirm_known_history)
        else:
            if args.reviewed_commit or args.previous_root or args.confirm_known_history or args.stage_allowance != 1:
                raise StageBlocked('OPTIONS_REVIEW_REQUIRED')
            result = execute(ctx, args.stage_number, args.approval_ack)
        fields = {'status', 'binding_sha256', 'stage_number', 'prior_consumed_requests',
            'stage_allowance', 'stage_cumulative_maximum', 'new_request_attempts', 'approval_granted',
            'request_attempts', 'known_cumulative_attempts', 'retained_windows_total', 'reservation_held',
            'stage', 'category', 'http_status', 'retry_authorised', 'reserved_cumulative_ceiling'}
        print(json.dumps({key: result[key] for key in fields if key in result}, sort_keys=True))
        return 0 if result['status'] in ('CAMPAIGN_BINDING_PREPARED_NOT_APPROVED',
            'CAMPAIGN_STAGE_RETAINED_NOT_DATA_ADMISSION') else 2
    except (Exception, KeyboardInterrupt) as exc:
        safe = old.SAFE | {'OWNER_HISTORY_ATTESTATION_REQUIRED', 'STAGE_NUMBER_REVIEW_REQUIRED',
            'STAGE_ALLOWANCE_REVIEW_REQUIRED', 'CAMPAIGN_STATE_REVIEW_REQUIRED',
            'INCOMPLETE_OR_FAILED_STAGE_NO_RETRY', 'PARTIAL_CAMPAIGN_INITIALIZATION_NO_RETRY',
            'CAMPAIGN_COMPLETE_NO_NEW_REQUESTS', 'CAMPAIGN_STATE_CHANGED_REVIEW'}
        safe |= {'FIRST_STAGE_ONE_REQUEST_REQUIRED'}
        code = str(exc) if isinstance(exc, StageBlocked) and str(exc) in safe else 'CAMPAIGN_LOCAL_REVIEW_REQUIRED'
        print(json.dumps({'status': 'BLOCKED', 'code': code, 'retry_authorised': False,
            'reservation_held': None, 'request_attempts': None, 'raw_error_printed': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
