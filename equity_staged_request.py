"""One owner-approved historical GET, fixed campaign reservation, no batch/retry.

Preview is inert. Prepare writes an unapproved binding only. Execute requires an
explicit one-request acknowledgement; reservations survive all outcomes.
"""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from typing import Any, Callable, Never

import equity_private_acquire as acq
from equity_daily_ingest import MAX_BYTES, decode_daily

CAMPAIGN = 'equity-eod-12names-2022-2024-v1'
ACK = 'I_APPROVE_ONE_STAGED_GET_THREE_AGGREGATE'
UPSTREAM_BASE = '72fe7952cb3d04d967bf8d72c74214f091619c7e'
REQUESTER_SHA = '3992e31ac47809b7d573ee4a4fbbc207f73993478a81daee667d1b1886493274'
LEGACY_SHA = 'daa8b6461eafe9bbd57d09631b7b128533e9bb45f57095c9cca61fb830acedda'
SOURCES = ('equity_staged_request.py', 'equity_private_acquire.py', 'equity_daily_ingest.py',
           'equity_eod_pilot.py', 'equity_real_report.py', 'event_backtest.py',
           'technical_indicators.py', 'app.py', 'constraints.txt', 'requirements.txt',
           'requirements-equity-study-tools.txt', 'mypy-equity-study.ini')
SAFE = frozenset({'APPROVAL_ACK_REQUIRED', 'LOCAL_PATH_REQUIRED', 'LINKED_PATH_REJECTED',
    'PRIVATE_NAMESPACE_REQUIRED', 'BINDING_REVIEW_REQUIRED', 'SOURCE_REVIEW_REQUIRED',
    'LEGACY_REVIEW_REQUIRED', 'LOCAL_SPACE_REVIEW_REQUIRED', 'CAMPAIGN_ALREADY_RESERVED',
    'OWNER_BINDING_ALREADY_EXISTS', 'NATIVE_WINDOWS_PYTHON_REQUIRED', 'OPTIONS_REVIEW_REQUIRED'})


class StageBlocked(ValueError):
    pass


@dataclass(frozen=True)
class Context:
    local: Path
    source: Path
    reviewed_commit: str

    @property
    def approval_parent(self) -> Path:
        return self.local / 'KiranTrading' / 'EquityApprovals' / CAMPAIGN

    @property
    def binding(self) -> Path:
        if re.fullmatch('[0-9a-f]{40}', self.reviewed_commit) is None:
            raise StageBlocked('SOURCE_REVIEW_REQUIRED')
        return self.approval_parent / ('stage-one-binding-' + self.reviewed_commit + '.json')

    @property
    def state(self) -> Path:
        return self.local / 'KiranTrading' / 'EquityCampaigns' / CAMPAIGN

    @property
    def legacy_parent(self) -> Path:
        return self.local / 'KiranTrading' / 'EquityStudies'


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')) + '\n').encode()


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path(path: Path) -> None:
    raw = str(path)
    if (not path.is_absolute() or raw.startswith(('\\\\', '//')) or '..' in path.parts
            or (os.name == 'nt' and (re.match(r'^[A-Za-z]:[\\/]', raw) is None
                or ':' in raw[2:]))):
        raise StageBlocked('LOCAL_PATH_REQUIRED')
    for entry in (path, *path.parents):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise StageBlocked('LINKED_PATH_REJECTED')


def _context(ctx: Context) -> None:
    _path(ctx.local)
    _path(ctx.source)
    if not ctx.local.is_dir() or not ctx.source.is_dir():
        raise StageBlocked('PRIVATE_NAMESPACE_REQUIRED')
    for output in (ctx.binding, ctx.state):
        _path(output)
        if output.is_relative_to(ctx.source) or output.is_relative_to(Path(sys.prefix).resolve()):
            raise StageBlocked('PRIVATE_NAMESPACE_REQUIRED')
        for parent in output.parents:
            if (parent / '.git').exists() or parent.name.casefold() in {'forward', 'forwardops'}:
                raise StageBlocked('PRIVATE_NAMESPACE_REQUIRED')


def _parents(path: Path) -> None:
    _path(path)
    missing = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    if not cursor.is_dir():
        raise StageBlocked('PRIVATE_NAMESPACE_REQUIRED')
    for part in reversed(missing):
        try:
            part.mkdir()
        except FileExistsError:
            pass
        _path(part)
        if not part.is_dir():
            raise StageBlocked('PRIVATE_NAMESPACE_REQUIRED')


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in items:
        if key in value:
            raise StageBlocked('BINDING_REVIEW_REQUIRED')
        value[key] = item
    return value


def _invalid_constant(value: str) -> Never:
    raise StageBlocked('BINDING_REVIEW_REQUIRED')


def _read(path: Path, limit: int = 65536) -> tuple[dict[str, Any], str]:
    _path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
        raise StageBlocked('BINDING_REVIEW_REQUIRED')
    # Windows lstat/fstat expose different ctime semantics on some builds.
    # Compare identity across APIs, then ctime stability within each API.
    identity = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        if any(getattr(opened, key) != getattr(info, key) for key in identity):
            raise StageBlocked('BINDING_REVIEW_REQUIRED')
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    _path(path)
    final = path.lstat()
    if any(getattr(opened, key) != getattr(after, key) or
           getattr(info, key) != getattr(final, key) for key in (*identity, 'st_ctime_ns')):
        raise StageBlocked('BINDING_REVIEW_REQUIRED')
    if len(raw) != info.st_size or len(raw) > limit:
        raise StageBlocked('BINDING_REVIEW_REQUIRED')
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_invalid_constant)
    if type(value) is not dict:
        raise StageBlocked('BINDING_REVIEW_REQUIRED')
    return value, _hash(raw)


def _git(source: Path, *words: str) -> str:
    env = {key: value for key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC',
            'PATHEXT', 'TEMP', 'TMP', 'USERPROFILE')
           if (value := os.environ.get(key)) is not None}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0', GIT_NO_REPLACE_OBJECTS='1')
    result = subprocess.run(['git', '-c', 'core.autocrlf=false', '-c', 'core.fsmonitor=false',
                             '-C', str(source), *words], capture_output=True,
                            env=env, timeout=30, check=False)
    if result.returncode:
        raise StageBlocked('SOURCE_REVIEW_REQUIRED')
    return result.stdout.decode('utf-8').strip()


def source_binding(ctx: Context, commit: str) -> dict[str, str]:
    if (re.fullmatch('[0-9a-f]{40}', commit) is None
            or _git(ctx.source, 'rev-parse', 'HEAD') != commit
            or _git(ctx.source, 'symbolic-ref', '--short', 'HEAD') != 'main'
            or Path(_git(ctx.source, 'rev-parse', '--show-toplevel')).resolve() != ctx.source.resolve()
            or _git(ctx.source, 'status', '--porcelain', '--untracked-files=all')):
        raise StageBlocked('SOURCE_REVIEW_REQUIRED')
    flags = _git(ctx.source, 'ls-files', '-v').splitlines()
    if not flags or any(not line.startswith('H ') for line in flags):
        raise StageBlocked('SOURCE_REVIEW_REQUIRED')
    if any((ctx.source / n).exists() for n in ('token.json', 'client_secret.json', '.streamlit/secrets.toml')):
        raise StageBlocked('SOURCE_REVIEW_REQUIRED')
    binding = {}
    for name in SOURCES:
        path = ctx.source / name
        _path(path)
        if not path.is_file() or not 0 < path.stat().st_size < 2 * 1024 * 1024:
            raise StageBlocked('SOURCE_REVIEW_REQUIRED')
        binding[name] = _hash(path.read_bytes())
    if binding['equity_private_acquire.py'] != REQUESTER_SHA:
        raise StageBlocked('SOURCE_REVIEW_REQUIRED')
    acq._source_binding()  # Also verifies unchanged app/indicator/replay source pins.
    return binding


def predecessor(ctx: Context, root: Path) -> dict[str, Any]:
    _path(root)
    if root.parent != ctx.legacy_parent or re.fullmatch('study-[0-9a-f]{32}', root.name) is None:
        raise StageBlocked('LEGACY_REVIEW_REQUIRED')
    intent, ih = _read(root / 'intent.json', 98304)
    failure, fh = _read(root / 'failure.json', 8192)
    request, rh = _read(root / 'request-001-intent.json', 4096)
    if (type(intent.get('source_sha256')) is not dict
            or intent['source_sha256'].get('equity_private_acquire.py') != LEGACY_SHA
            or intent.get('transport') != 'NATIVE_TLS' or intent.get('credentials_saved') is not False
            or failure.get('category') != 'STUDY_HTTP_AUTH_REVIEW'
            or failure.get('code') != 'PRIVATE_EQUITY_STUDY_STOP_REVIEW'
            or failure.get('stage') != 'REQUEST' or failure.get('status') != 'BLOCKED'
            or type(failure.get('request_attempts')) is not int or failure['request_attempts'] != 1
            or type(failure.get('originals_retained')) is not int or failure['originals_retained'] != 0
            or failure.get('retry_authorised') is not False
            or failure.get('raw_error_printed') is not False
            or request != acq.windows()[0]._asdict() or type(request.get('ordinal')) is not int
            or any((root / name).exists() for name in (acq.windows()[0].filename,
                'request-001-result.json', 'request-002-intent.json', 'acquisition.json',
                'inputs.json', 'report.json', 'report.html', 'candles.parquet'))):
        raise StageBlocked('LEGACY_REVIEW_REQUIRED')
    return {'root': str(root), 'consumed_requests': 1,
            'sidecar_sha256': {'intent.json': ih, 'failure.json': fh, 'request-001-intent.json': rh}}


def prepare(ctx: Context, commit: str, roots: list[Path]) -> dict[str, Any]:
    _context(ctx)
    if commit != ctx.reviewed_commit:
        raise StageBlocked('SOURCE_REVIEW_REQUIRED')
    if len(roots) != 2 or roots[0] == roots[1]:
        raise StageBlocked('LEGACY_REVIEW_REQUIRED')
    sources = source_binding(ctx, commit)
    previous = [predecessor(ctx, p) for p in roots]
    if previous[0]['sidecar_sha256']['intent.json'] == previous[1]['sidecar_sha256']['intent.json']:
        raise StageBlocked('LEGACY_REVIEW_REQUIRED')
    if ctx.binding.exists():
        raise StageBlocked('OWNER_BINDING_ALREADY_EXISTS')
    if ctx.state.exists():
        raise StageBlocked('CAMPAIGN_ALREADY_RESERVED')
    value = {'format': 'equity-stage-one-binding-v1', 'campaign': CAMPAIGN,
        'upstream_base': UPSTREAM_BASE, 'execution_commit': commit, 'source_sha256': sources,
        'previous': previous, 'prior_consumed_requests': 2, 'new_request_maximum': 1,
        'aggregate_maximum': 3, 'window': acq.windows()[0]._asdict(),
        'approval_granted': False, 'retry_authorised': False}
    _parents(ctx.approval_parent)
    acq._write(ctx.approval_parent, ctx.binding.name, _canonical(value))
    return {'status': 'STAGE_ONE_BINDING_PREPARED_NOT_APPROVED', 'binding_sha256': _hash(_canonical(value)),
            'previous_consumed_requests': 2, 'new_requests': 0, 'credential_reads': 0,
            'network_requests': 0, 'approval_granted': False}


def reserve(state: Path, raw: bytes) -> None:
    _parents(state.parent)
    _path(state)
    try:
        state.mkdir()  # Atomic exclusive reservation; fixed campaign path, no GUID.
    except FileExistsError:
        raise StageBlocked('CAMPAIGN_ALREADY_RESERVED') from None
    # Any failure/crash after mkdir leaves the reservation held; never remove it.
    acq._write(state, 'reservation.json', raw)


def execute(ctx: Context, ack: str, *, token_reader: Callable[[], str] = acq._hidden_token,
            fetch: Callable[[acq.Window, str], acq.Response] = acq._https_get) -> dict[str, Any]:
    if ack != ACK:
        raise StageBlocked('APPROVAL_ACK_REQUIRED')
    _context(ctx)
    if ctx.state.exists():
        raise StageBlocked('CAMPAIGN_ALREADY_RESERVED')
    binding, digest = _read(ctx.binding)
    if (set(binding) != {'format', 'campaign', 'upstream_base', 'execution_commit',
            'source_sha256', 'previous', 'prior_consumed_requests', 'new_request_maximum',
            'aggregate_maximum', 'window', 'approval_granted', 'retry_authorised'}
            or type(binding.get('execution_commit')) is not str
            or binding.get('execution_commit') != ctx.reviewed_commit
            or type(binding.get('source_sha256')) is not dict
            or type(binding.get('window')) is not dict
            or type(binding['window'].get('ordinal')) is not int
            or binding.get('format') != 'equity-stage-one-binding-v1' or binding.get('campaign') != CAMPAIGN
            or binding.get('approval_granted') is not False or binding.get('retry_authorised') is not False
            or binding.get('upstream_base') != UPSTREAM_BASE
            or any(type(binding.get(k)) is not int or binding[k] != v for k, v in
                   (('prior_consumed_requests', 2), ('new_request_maximum', 1), ('aggregate_maximum', 3)))
            or binding.get('window') != acq.windows()[0]._asdict()):
        raise StageBlocked('BINDING_REVIEW_REQUIRED')
    sources = source_binding(ctx, binding['execution_commit'])
    if sources != binding['source_sha256'] or type(binding.get('previous')) is not list or len(binding['previous']) != 2:
        raise StageBlocked('BINDING_REVIEW_REQUIRED')
    if any(type(p) is not dict or set(p) != {'root', 'consumed_requests', 'sidecar_sha256'}
            or type(p.get('root')) is not str or type(p.get('consumed_requests')) is not int
            or p['consumed_requests'] != 1 or type(p.get('sidecar_sha256')) is not dict
            for p in binding['previous']):
        raise StageBlocked('BINDING_REVIEW_REQUIRED')
    previous = [predecessor(ctx, Path(p['root'])) for p in binding['previous']]
    if previous != binding['previous'] or previous[0]['root'] == previous[1]['root']:
        raise StageBlocked('LEGACY_REVIEW_REQUIRED')
    profile = acq._runtime_profile()
    if shutil.disk_usage(ctx.local).free < acq.MIN_FREE_BYTES:
        raise StageBlocked('LOCAL_SPACE_REVIEW_REQUIRED')
    reserve(ctx.state, _canonical({'format': 'equity-one-use-reservation-v1',
        'campaign': CAMPAIGN, 'binding_sha256': digest, 'acknowledgement': ACK,
        'prior_consumed_requests': 2, 'new_requests_reserved': 1, 'aggregate_maximum': 3,
        'started_utc_unattested': datetime.now(timezone.utc).isoformat(),
        'source_sha256': sources, 'runtime_versions': profile, 'credentials_saved': False}))
    attempts = 0
    phase = 'HIDDEN_TOKEN'
    try:
        token = token_reader()
        if type(token) is not str or not 16 <= len(token) <= 8192 or any(not 33 <= ord(c) <= 126 for c in token):
            raise acq.StudyBlocked('STUDY_TOKEN_INPUT_REVIEW')
        window = acq.windows()[0]
        acq._write(ctx.state, 'request-intent.json', _canonical(window._asdict()))
        phase = 'REQUEST'
        attempts = 1  # Unknown outcome consumes the one reserved dispatch.
        response = fetch(window, token)  # Exactly one dispatch; never a loop/retry.
        if response.status != 200 or response.content_type.lower().split(';')[0].strip() != 'application/json':
            raise acq.StudyBlocked('STUDY_RESPONSE_REVIEW')
        if type(response.body) is not bytes or not 0 < len(response.body) <= MAX_BYTES:
            raise acq.StudyBlocked('STUDY_RESPONSE_BYTES_BOUND')
        acq._secret_screen(response.body, token)
        token = ''
        phase = 'DECODE'
        decoded = decode_daily(response.body, instrument_key=window.instrument_key,
                                   start=window.start, end=window.end)
        if sources != source_binding(ctx, binding['execution_commit']):
            raise StageBlocked('SOURCE_REVIEW_REQUIRED')
        identity = acq._write(ctx.state, window.filename, response.body)
        acq._write(ctx.state, 'decoded.json', _canonical(decoded))
        result = {'status': 'STAGE_ONE_STRUCTURE_PASSED_NOT_DATA_ADMISSION',
            'prior_consumed_requests': 2, 'new_request_attempts': 1, 'known_aggregate_attempts': 3,
            'new_requests_reserved': 1, 'aggregate_maximum': 3, 'reservation_held': True,
            'rows': decoded['row_count'], 'original': identity,
            'decoded_sha256': decoded['decoded_sha256'], 'http_status': 200,
            'input_origin': 'NATIVE_TLS_NOT_PROVIDER_SIGNATURE' if fetch is acq._https_get else 'INJECTED_SYNTHETIC',
            'training_eligible': False, 'promotion_authorised': False, 'retry_authorised': False}
        acq._write(ctx.state, 'result.json', _canonical(result))
        return result
    except (Exception, KeyboardInterrupt) as exc:
        category = str(exc) if isinstance(exc, StageBlocked) and str(exc) in SAFE else acq._category(exc)
        failure = {'status': 'STAGE_ONE_BLOCKED_RESERVATION_HELD', 'stage': phase,
            'category': category, 'http_status': acq.HTTP_REVIEW_STATUS.get(category),
            'prior_consumed_requests': 2, 'new_request_attempts': attempts,
            'known_aggregate_attempts': 2 + attempts, 'new_requests_reserved': 1,
            'aggregate_maximum': 3, 'reservation_held': True, 'raw_error_printed': False,
            'retry_authorised': False, 'training_eligible': False}
        try:
            acq._write(ctx.state, 'failure.json', _canonical(failure))
        except Exception:
            pass
        return failure


def native_context() -> Context:
    if os.name != 'nt' or sys.version_info[:3] != (3, 13, 9):
        raise StageBlocked('NATIVE_WINDOWS_PYTHON_REQUIRED')
    loader: Any = getattr(ctypes, 'windll')
    buffer = ctypes.create_unicode_buffer(32768)
    if loader.shell32.SHGetFolderPathW(None, 0x1C, None, 0, buffer) != 0:
        raise StageBlocked('PRIVATE_NAMESPACE_REQUIRED')
    source = Path(__file__).resolve().parent
    return Context(Path(buffer.value), source, _git(source, 'rev-parse', 'HEAD'))


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise StageBlocked('OPTIONS_REVIEW_REQUIRED')


def main(argv: list[str] | None = None) -> int:
    ctx: Context | None = None
    try:
        parser = Parser(add_help=False, allow_abbrev=False)
        parser.add_argument('--mode', choices=('preview', 'prepare', 'execute'), default='preview')
        parser.add_argument('--reviewed-commit')
        parser.add_argument('--previous-root', type=Path, action='append', default=[])
        parser.add_argument('--approval-ack')
        args = parser.parse_args(argv)
        if args.mode == 'preview':
            print(json.dumps({'status': 'PREVIEW', 'network_requests': 0, 'credential_reads': 0,
                'writes': 0, 'prior_consumed_requests': 2, 'proposed_new_request_maximum': 1,
                'proposed_aggregate_maximum': 3, 'approval_granted': False,
                'window': acq.windows()[0]._asdict()}))
            return 0
        if ((args.mode == 'prepare' and args.approval_ack is not None)
                or (args.mode == 'execute' and (args.reviewed_commit or args.previous_root))):
            raise StageBlocked('OPTIONS_REVIEW_REQUIRED')
        if args.mode == 'execute' and args.approval_ack != ACK:
            raise StageBlocked('APPROVAL_ACK_REQUIRED')
        ctx = native_context()
        if args.mode == 'prepare':
            result = prepare(ctx, args.reviewed_commit or '', args.previous_root)
        else:
            result = execute(ctx, args.approval_ack)
        fields = ('status', 'stage', 'category', 'http_status', 'prior_consumed_requests',
            'new_request_attempts', 'known_aggregate_attempts', 'new_requests_reserved',
            'aggregate_maximum', 'reservation_held', 'rows', 'decoded_sha256',
            'input_origin', 'binding_sha256', 'new_requests', 'network_requests',
            'credential_reads', 'approval_granted', 'retry_authorised')
        print(json.dumps({key: result[key] for key in fields if key in result}, sort_keys=True))
        return 0 if result['status'] in ('STAGE_ONE_BINDING_PREPARED_NOT_APPROVED',
                                         'STAGE_ONE_STRUCTURE_PASSED_NOT_DATA_ADMISSION') else 2
    except (Exception, KeyboardInterrupt) as exc:
        code = str(exc) if isinstance(exc, StageBlocked) and str(exc) in SAFE else 'STAGED_LOCAL_REVIEW_REQUIRED'
        held: bool | None = None
        if ctx is not None:
            try:
                held = ctx.state.exists()
            except OSError:
                pass
        print(json.dumps({'status': 'BLOCKED', 'code': code, 'new_request_attempts': 0,
                          'reservation_held': held,
                          'retry_authorised': False, 'raw_error_printed': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
