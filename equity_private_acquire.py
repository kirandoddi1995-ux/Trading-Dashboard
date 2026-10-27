"""Private, owner-invoked 36-request equity study; preview is inert.

Never reads capture credentials, environment tokens or secrets files. No retry,
redirect, new instrument, date extension, trading, training or database operation.
Exact valid candle-response bytes are retained after a secrecy/structure check;
unexpected/error bodies are not retained. Reports are only
retrospective price/cost scenarios, not admission or executable-price proof.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import html
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import ssl
import stat
import sys
import time
from typing import Any, Callable, NamedTuple, Never
from urllib.error import HTTPError
from urllib.parse import quote, unquote
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener
import warnings

from equity_daily_ingest import MAX_BYTES, decode_daily
from equity_eod_pilot import COHORT

# Current public security identifiers for the fixed engineering cohort, NOT a
# historical membership or a guarantee that an ISIN's older history is complete.
ISINS = (
    'INE002A01018', 'INE467B01029', 'INE009A01021', 'INE040A01034',
    'INE090A01021', 'INE154A01025', 'INE018A01030', 'INE044A01036',
    'INE397D01024', 'INE733E01010', 'INE081A01020', 'INE101A01026',
)
YEARS = (2022, 2023, 2024)
HOST = 'https://api.upstox.com'
MAX_REQUESTS = 36
MAX_TOTAL_BYTES = MAX_REQUESTS * MAX_BYTES
TIMEOUT_SECONDS = 20
MIN_FREE_BYTES = 512 * 1024 * 1024
FLAGS = {'training_eligible': False, 'promotion_authorised': False,
         'whole_app_accuracy_verified': False, 'performance_claim_verified': False,
         'custody_verified': False, 'executable_prices_verified': False}
HTTP_REVIEW_STATUS = {'STUDY_HTTP_401_UNAUTHENTICATED': 401,
                      'STUDY_HTTP_403_FORBIDDEN': 403}
SAFE_CODES = frozenset({
    'STUDY_LINKED_PATH_REJECTED', 'STUDY_PRIVATE_ABSOLUTE_ROOT_REQUIRED',
    'STUDY_PARENT_REQUIRED', 'STUDY_CAPTURE_OR_REPOSITORY_ROOT_REJECTED',
    'STUDY_NEW_ROOT_REQUIRED_NO_RETRY', 'STUDY_FIXED_OUTPUT_NAME_REQUIRED',
    'STUDY_OUTPUT_READBACK_FAILED', 'STUDY_REDIRECT_REJECTED',
    'STUDY_CONTENT_ENCODING_REJECTED', 'STUDY_HTTP_AUTH_REVIEW', 'STUDY_HTTP_REVIEW',
    'STUDY_INTERACTIVE_HIDDEN_PROMPT_REQUIRED', 'STUDY_TOKEN_INPUT_REVIEW',
    'STUDY_REQUEST_BUDGET_EXHAUSTED', 'STUDY_RESPONSE_REVIEW',
    'STUDY_RESPONSE_BYTES_BOUND', 'STUDY_TOTAL_BYTES_BOUND',
    'STUDY_SOURCE_CHANGED', 'STUDY_PARQUET_READBACK_FAILED',
    'STUDY_REVIEWED_PYTHON_REQUIRED', 'STUDY_RESPONSE_SECRET_ECHO_REJECTED',
    'STUDY_ARGUMENT_REVIEW',
    'STUDY_JSON_SYNTAX_REVIEW', 'STUDY_JSON_STRUCTURE_BOUND',
    'STUDY_RESPONSE_SHAPE_REVIEW',
    'STUDY_RUNTIME_PROFILE_REVIEW',
    'STUDY_LOCAL_FREE_SPACE_REVIEW',
    'STUDY_ORIGINAL_OR_ARTIFACT_CHANGED',
    'STUDY_HTTP_401_UNAUTHENTICATED', 'STUDY_HTTP_403_FORBIDDEN',
})


class StudyBlocked(ValueError):
    """Fixed local code only; upstream errors and response bodies stay private."""


class Window(NamedTuple):
    ordinal: int
    symbol: str
    instrument_key: str
    start: str
    end: str
    filename: str


class Response(NamedTuple):
    status: int
    body: bytes
    content_type: str = 'application/json'


def _category(exc: BaseException) -> str:
    if isinstance(exc, StudyBlocked) and str(exc) in SAFE_CODES:
        return str(exc)
    if isinstance(exc, KeyboardInterrupt):
        return 'OWNER_INTERRUPTED'
    if isinstance(exc, ssl.SSLCertVerificationError):
        return 'TLS_VERIFICATION_REVIEW'
    if isinstance(exc, TimeoutError):
        return 'NETWORK_TIMEOUT_REVIEW'
    if isinstance(exc, OSError):
        return 'LOCAL_OR_NETWORK_IO_REVIEW'
    if isinstance(exc, ValueError):
        return 'STRUCTURE_OR_VALUE_REVIEW'
    return 'UNCLASSIFIED_FAILURE'


def windows() -> tuple[Window, ...]:
    return tuple(Window(i * 3 + j + 1, symbol, 'NSE_EQ|' + ISINS[i],
                        f'{year}-01-01', f'{year}-12-31',
                        f'{i * 3 + j + 1:03d}-{symbol.replace("&", "AND")}-{year}.json')
                 for i, symbol in enumerate(COHORT) for j, year in enumerate(YEARS))


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True,
                       allow_nan=False) + '\n').encode('utf-8')


def preview() -> dict[str, Any]:
    specification = {'format': 'private-equity-36-window-v1',
        'windows': [w._asdict() for w in windows()],
        'cohort_basis': 'CURRENT_SURVIVORS_NOT_HISTORICAL_UNIVERSE',
        'mapping_basis': 'CURRENT_PUBLIC_ISINS_NOT_HISTORICAL_CHAIN_PROOF',
        'max_requests': MAX_REQUESTS, 'max_response_bytes': MAX_BYTES,
        'max_total_response_bytes': MAX_TOTAL_BYTES,
        'minimum_local_free_bytes': MIN_FREE_BYTES,
        'request_timeout_seconds': TIMEOUT_SECONDS,
        'timeout_basis': 'SOCKET_TIMEOUT_NOT_HARD_DNS_OR_BATCH_WALL_DEADLINE',
        'retries': 0, 'redirects': 0, 'metadata_requests': 0,
        'dates': '2022-2024_ONLY', **FLAGS}
    return {'status': 'PREVIEW', 'specification': specification,
            'specification_sha256': _hash(_canonical(specification)),
            'network_calls': 0, 'credential_reads': 0, 'writes': 0,
            'approval_authority': False}


def _reject_links(path: Path) -> None:
    for entry in reversed((path, *path.parents)):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise StudyBlocked('STUDY_LINKED_PATH_REJECTED')


def _new_private_root(value: Path) -> Path:
    if not value.is_absolute() or '..' in value.parts or str(value).startswith(('\\\\', '//')):
        raise StudyBlocked('STUDY_PRIVATE_ABSOLUTE_ROOT_REQUIRED')
    if os.name == 'nt' and ':' in str(value)[len(value.drive):]:
        raise StudyBlocked('STUDY_PRIVATE_ABSOLUTE_ROOT_REQUIRED')
    _reject_links(value.parent)
    if not value.parent.is_dir():
        raise StudyBlocked('STUDY_PARENT_REQUIRED')
    root = value.parent.resolve(strict=True) / value.name
    reserved = {'forward', 'forwardops', '.streamlit', '.git'}
    if any(part.casefold() in reserved or part.casefold().startswith('kiran_forward_') for part in root.parts):
        raise StudyBlocked('STUDY_CAPTURE_OR_REPOSITORY_ROOT_REJECTED')
    source = Path(__file__).resolve().parent
    if root.is_relative_to(source) or root.is_relative_to(Path(sys.prefix).resolve()):
        raise StudyBlocked('STUDY_CAPTURE_OR_REPOSITORY_ROOT_REJECTED')
    for parent in (root.parent, *root.parent.parents):
        if (parent / '.git').exists():
            raise StudyBlocked('STUDY_CAPTURE_OR_REPOSITORY_ROOT_REJECTED')
    try:
        root.lstat()
    except FileNotFoundError:
        return root
    raise StudyBlocked('STUDY_NEW_ROOT_REQUIRED_NO_RETRY')


def _write(root: Path, name: str, raw: bytes) -> dict[str, Any]:
    if Path(name).name != name or name.startswith('.'):
        raise StudyBlocked('STUDY_FIXED_OUTPUT_NAME_REQUIRED')
    _reject_links(root)
    with (root / name).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if (root / name).read_bytes() != raw:
        raise StudyBlocked('STUDY_OUTPUT_READBACK_FAILED')
    return {'name': name, 'bytes': len(raw), 'sha256': _hash(raw)}


def _verify_files(root: Path, files: list[dict[str, Any]]) -> None:
    """Bounded readback of the known artifacts only, never arbitrary folder data."""
    for identity in files:
        path = root / identity['name']
        _reject_links(path)
        expected = identity['bytes']
        if (type(expected) is not int or not 0 <= expected <= 64 * 1024 * 1024
                or not path.is_file() or path.stat().st_size != expected):
            raise StudyBlocked('STUDY_ORIGINAL_OR_ARTIFACT_CHANGED')
        with path.open('rb') as stream:
            raw = stream.read(expected + 1)
        if len(raw) != expected or _hash(raw) != identity['sha256']:
            raise StudyBlocked('STUDY_ORIGINAL_OR_ARTIFACT_CHANGED')


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        raise StudyBlocked('STUDY_REDIRECT_REJECTED')


def _https_get(window: Window, token: str) -> Response:
    import certifi
    context = ssl.create_default_context(cafile=certifi.where())
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=context))
    url = (HOST + '/v3/historical-candle/' + quote(window.instrument_key, safe='')
           + '/days/1/' + window.end + '/' + window.start)
    request = Request(url, method='GET', headers={'Authorization': 'Bearer ' + token,
                      'Accept': 'application/json', 'Accept-Encoding': 'identity'})
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as stream:
            if stream.geturl() != url:
                raise StudyBlocked('STUDY_REDIRECT_REJECTED')
            if stream.headers.get('Content-Encoding', 'identity').lower() not in ('identity', ''):
                raise StudyBlocked('STUDY_CONTENT_ENCODING_REJECTED')
            raw = stream.read(MAX_BYTES + 1)
            return Response(stream.status, raw, stream.headers.get_content_type())
    except HTTPError as exc:
        # Do not decode, print or retain error bodies (which may echo auth input).
        code = {401: 'STUDY_HTTP_401_UNAUTHENTICATED',
                403: 'STUDY_HTTP_403_FORBIDDEN'}.get(exc.code, 'STUDY_HTTP_REVIEW')
        exc.close()
        raise StudyBlocked(code) from None


def _hidden_token() -> str:
    if not sys.stdin.isatty():
        raise StudyBlocked('STUDY_INTERACTIVE_HIDDEN_PROMPT_REQUIRED')
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        token = getpass.getpass('Existing read-only Upstox token (hidden; never saved): ')
    if not 16 <= len(token) <= 8192 or any(not 33 <= ord(c) <= 126 for c in token):
        raise StudyBlocked('STUDY_TOKEN_INPUT_REVIEW')
    return token


def _secret_screen(raw: bytes, token: str) -> None:
    """Inspect bounded JSON strings before retention, including escaped echoes.

    Preserve duplicate pairs until secrecy scanning finishes. Reject non-candle
    response schemas before retention; the decoder then validates every row.
    Unexpected bodies are deliberately not retained as they may contain secrets.
    """
    if token.encode('ascii') in raw:
        raise StudyBlocked('STUDY_RESPONSE_SECRET_ECHO_REJECTED')
    def invalid_constant(value: str) -> Never:
        raise ValueError('NON_JSON_NUMBER')
    try:
        parsed = json.loads(raw.decode('utf-8'), parse_int=str, parse_float=str,
                            parse_constant=invalid_constant, object_pairs_hook=lambda pairs: pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise StudyBlocked('STUDY_JSON_SYNTAX_REVIEW') from None
    pending = [parsed]
    examined = 0
    while pending:
        value = pending.pop()
        examined += 1
        if examined > 50000:
            raise StudyBlocked('STUDY_JSON_STRUCTURE_BOUND')
        if isinstance(value, str):
            if token in value or token in unquote(value) or token in html.unescape(value):
                raise StudyBlocked('STUDY_RESPONSE_SECRET_ECHO_REJECTED')
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
    # Our pairs hook makes JSON objects lists of pairs. Exact documented keys
    # only: an added diagnostic/message/auth field cannot be written to disk.
    if (type(parsed) is not list or len(parsed) != 2
            or any(type(pair) is not tuple or len(pair) != 2 for pair in parsed)):
        raise StudyBlocked('STUDY_RESPONSE_SHAPE_REVIEW')
    obj = dict(parsed)
    if set(obj) != {'status', 'data'} or obj['status'] != 'success':
        raise StudyBlocked('STUDY_RESPONSE_SHAPE_REVIEW')
    data = obj['data']
    if (type(data) is not list or len(data) != 1 or type(data[0]) is not tuple
            or len(data[0]) != 2 or data[0][0] != 'candles'):
        raise StudyBlocked('STUDY_RESPONSE_SHAPE_REVIEW')


def _source_binding() -> dict[str, str]:
    source = Path(__file__).resolve().parent
    binding = {}
    for name in (
        'equity_private_acquire.py', 'equity_real_report.py', 'equity_daily_ingest.py',
        'equity_eod_pilot.py', 'event_backtest.py', 'technical_indicators.py', 'app.py'):
        path = source / name
        _reject_links(path)
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise StudyBlocked('STUDY_SOURCE_CHANGED')
        binding[name] = _hash(path.read_bytes())
    from equity_real_report import APP_SHA256, ENGINE_SHA256, INDICATORS_SHA256
    expected = {'app.py': APP_SHA256, 'event_backtest.py': ENGINE_SHA256,
                'technical_indicators.py': INDICATORS_SHA256}
    if any(binding[name] != digest for name, digest in expected.items()):
        raise StudyBlocked('STUDY_SOURCE_CHANGED')
    return binding


def _runtime_profile() -> dict[str, str]:
    required = {'pandas': '2.3.3', 'numpy': '2.4.6', 'pyarrow': '24.0.0',
                'certifi': '2026.10.23'}
    if any(metadata.version(name) != version for name, version in required.items()):
        raise StudyBlocked('STUDY_RUNTIME_PROFILE_REVIEW')
    return required


def acquire(root: Path, *, token_reader: Callable[[], str] = _hidden_token,
            fetch: Callable[[Window, str], Response] = _https_get,
            pause: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Owner-confirmed acquisition. Injectable collaborators are synthetic evidence."""
    destination = _new_private_root(root)
    specification = preview()
    binding = _source_binding()
    profile = _runtime_profile()
    if shutil.disk_usage(destination.parent).free < MIN_FREE_BYTES:
        raise StudyBlocked('STUDY_LOCAL_FREE_SPACE_REVIEW')
    destination.mkdir(exist_ok=False)
    _write(destination, 'intent.json', _canonical({
        'specification': specification, 'source_sha256': binding,
        'runtime_versions': profile,
        'started_utc': datetime.now(timezone.utc).isoformat(),
        'transport': 'NATIVE_TLS' if fetch is _https_get else 'INJECTED_NOT_PROVIDER_EVIDENCE',
        'credentials_saved': False, **FLAGS}))
    attempts = 0
    files: list[dict[str, Any]] = []
    decoded: dict[str, list[dict[str, Any]]] = {name: [] for name in COHORT}
    chunks: dict[str, list[dict[str, Any]]] = {name: [] for name in COHORT}
    stage = 'HIDDEN_TOKEN'
    try:
        token = token_reader()
        if not isinstance(token, str) or not 16 <= len(token) <= 8192 or any(not 33 <= ord(c) <= 126 for c in token):
            raise StudyBlocked('STUDY_TOKEN_INPUT_REVIEW')
        for window in windows():
            stage = 'REQUEST'
            if shutil.disk_usage(destination).free < MIN_FREE_BYTES:
                raise StudyBlocked('STUDY_LOCAL_FREE_SPACE_REVIEW')
            if attempts >= MAX_REQUESTS:
                raise StudyBlocked('STUDY_REQUEST_BUDGET_EXHAUSTED')
            _write(destination, f'request-{window.ordinal:03d}-intent.json', _canonical(window._asdict()))
            attempts += 1  # Count before GET: an unknown response is still consumed.
            result = fetch(window, token)
            if result.status != 200 or result.content_type.lower().split(';')[0].strip() != 'application/json':
                raise StudyBlocked('STUDY_RESPONSE_REVIEW')
            if type(result.body) is not bytes or not 0 < len(result.body) <= MAX_BYTES:
                raise StudyBlocked('STUDY_RESPONSE_BYTES_BOUND')
            _secret_screen(result.body, token)
            if sum(item['bytes'] for item in files) + len(result.body) > MAX_TOTAL_BYTES:
                raise StudyBlocked('STUDY_TOTAL_BYTES_BOUND')
            stage = 'DECODE'
            value = decode_daily(result.body, instrument_key=window.instrument_key,
                                 start=window.start, end=window.end)
            stage = 'RETAIN_ORIGINAL'
            identity = _write(destination, window.filename, result.body)
            files.append({**identity, **window._asdict(),
                          'retrieved_utc_unattested': datetime.now(timezone.utc).isoformat()})
            decoded[window.symbol].extend(value['rows'])
            chunks[window.symbol].append(value)
            _write(destination, f'request-{window.ordinal:03d}-result.json', _canonical({
                'status': value['status'], 'rows': value['row_count'],
                'source_sha256': identity['sha256'], 'request_ordinal': window.ordinal,
                'calendar_verified': False, 'corporate_actions_verified': False, **FLAGS}))
            if window.ordinal != MAX_REQUESTS:
                pause(1.0)
        token = ''
        stage = 'SOURCE_RECHECK'
        if binding != _source_binding():
            raise StudyBlocked('STUDY_SOURCE_CHANGED')
        stage = 'ORIGINAL_RECHECK'
        _verify_files(destination, files)
        stage = 'REPORT'
        from equity_real_report import build_report, render_html
        inputs = {'format': 'equity-real-inputs-v1', 'cohort': list(COHORT),
            'symbols': {symbol: {'instrument_key': 'NSE_EQ|' + ISINS[i], 'chunks': [
                {key: value[key] for key in ('start', 'end', 'source_sha256', 'decoded_sha256')}
                for value in chunks[symbol]]} for i, symbol in enumerate(COHORT)}}
        input_identity = _write(destination, 'inputs.json', _canonical(inputs))
        report = build_report(chunks, manifest=inputs)
        origin = 'NATIVE_TLS_ORIGINAL_BYTES_NOT_PROVIDER_SIGNATURE' if fetch is _https_get else 'INJECTED_SYNTHETIC_NOT_MARKET_EVIDENCE'
        envelope = {'format': 'private-equity-report-envelope-v1', 'input_origin': origin,
                    'analysis': report, 'specification_sha256': specification['specification_sha256'],
                    **FLAGS}
        report_identity = _write(destination, 'report.json', _canonical(envelope))
        page = render_html(report)
        policy = ('<meta http-equiv="Content-Security-Policy" '
                  'content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">')
        page = page.replace('<head>', '<head>' + policy, 1).replace(
            '<body>', '<body><p><strong>Input origin: ' + html.escape(origin) + '</strong></p>', 1)
        html_identity = _write(destination, 'report.html', page.encode('utf-8'))
        stage = 'PARQUET'
        parquet_identity = _parquet(destination, decoded)
        stage = 'FINAL_READBACK'
        _verify_files(destination, [*files, input_identity, report_identity, html_identity])
        if 'name' in parquet_identity:
            _verify_files(destination, [parquet_identity])
        if binding != _source_binding():
            raise StudyBlocked('STUDY_SOURCE_CHANGED')
        summary = {'status': ('PRIVATE_EQUITY_DATA_AND_SCENARIO_REPORT_NOT_PROMOTION' if fetch is _https_get
                              else 'SYNTHETIC_STUDY_REHEARSAL_NOT_REAL_DATA'),
            'request_attempts': attempts, 'completed_windows': len(files),
            'rows': sum(len(rows) for rows in decoded.values()),
            'files': files, 'inputs': input_identity, 'report': report_identity, 'html': html_identity,
            'parquet': parquet_identity, 'source_sha256': binding,
            'runtime_versions': profile,
            'specification_sha256': specification['specification_sha256'],
            'calendar_coverage_verified': False, 'corporate_actions_verified': False,
            'transport': 'NATIVE_TLS' if fetch is _https_get else 'INJECTED_NOT_PROVIDER_EVIDENCE',
            **FLAGS, 'approval_authority': False}
        manifest = _write(destination, 'acquisition.json', _canonical(summary))
        return {**summary, 'acquisition_sha256': manifest['sha256']}
    except (Exception, KeyboardInterrupt) as exc:
        # Preserve every original and intent. No retry/resume/cleanup is performed.
        failure = {'status': 'BLOCKED', 'code': 'PRIVATE_EQUITY_STUDY_STOP_REVIEW',
                   'stage': stage, 'category': _category(exc),
                   'http_status': HTTP_REVIEW_STATUS.get(_category(exc)),
                   'request_attempts': attempts, 'originals_retained': len(files),
                   'retry_authorised': False, 'raw_error_printed': False, **FLAGS}
        try:
            _write(destination, 'failure.json', _canonical(failure))
        except Exception:
            pass
        return failure


def _parquet(root: Path, decoded: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows = [{'symbol': symbol, **row} for symbol in COHORT for row in decoded[symbol]]
    table = pa.Table.from_pylist(rows)
    # Derived strings preserve decimal text. Exact JSON remains the recovery source.
    path = root / 'candles.parquet'
    _reject_links(root)
    with path.open('xb') as stream:
        pq.write_table(table, stream, compression='zstd')
        stream.flush()
        os.fsync(stream.fileno())
    restored = pq.read_table(path)
    if not restored.equals(table):
        raise StudyBlocked('STUDY_PARQUET_READBACK_FAILED')
    return {'name': path.name, 'bytes': path.stat().st_size, 'sha256': _hash(path.read_bytes()),
            'rows': table.num_rows, 'readback_equal': True, 'recovery_source': 'EXACT_ORIGINAL_JSON'}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise StudyBlocked('STUDY_ARGUMENT_REVIEW')


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        print(json.dumps(preview(), sort_keys=True))
        return 0
    try:
        parser = _Parser(allow_abbrev=False, add_help=False)
        parser.add_argument('--output', type=Path, required=True)
        parser.add_argument('--confirm-private-study', action='store_true')
        args = parser.parse_args(arguments)
        if not args.confirm_private_study:
            print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'credential_reads': 0,
                              'writes': 0, 'approval_authority': False}))
            return 0
        if sys.version_info[:3] != (3, 13, 9):
            raise StudyBlocked('STUDY_REVIEWED_PYTHON_REQUIRED')
        result = acquire(args.output)
    except (Exception, KeyboardInterrupt) as exc:
        result = {'status': 'BLOCKED', 'code': 'PRIVATE_EQUITY_STUDY_STOP_REVIEW',
                  'stage': 'ADMISSION', 'category': _category(exc), 'raw_error_printed': False,
                  'retry_authorised': False, 'approval_authority': False}
    # Never print rows, prices, file paths, keys, headers, token or exception text.
    print(json.dumps({key: result[key] for key in ('status', 'code', 'stage',
          'request_attempts', 'completed_windows', 'rows', 'retry_authorised',
          'approval_authority', 'category', 'http_status', 'acquisition_sha256') if key in result}, sort_keys=True))
    return 0 if result['status'] == 'PRIVATE_EQUITY_DATA_AND_SCENARIO_REPORT_NOT_PROMOTION' else 2


if __name__ == '__main__':
    raise SystemExit(main())
