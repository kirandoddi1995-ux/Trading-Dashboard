"""Bounded offline prospective index dataset readiness, without model authority.

Registration is a hash-bound local custody claim, not independent timestamping or
licence verification. Persist the returned immutable bytes before collection.
Only one final export per session is admitted; extending a cohort requires a new
prospective protocol, never replacing a previously registered configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, cast

from nifty_session_calendar import cash_session

PUBLIC_ROOT = Path(__file__).resolve().parent
SCOPE = 'FORWARD_OBSERVATIONAL_INDEX_ONLY'
MAX_SESSIONS = 128
MIN_SESSION_CLUSTERS = 20
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_PROTOCOL_BYTES = 256 * 1024
FLAGS = {'training_eligible': False, 'approval_authority': False,
         'production_eligible': False, 'fill_evidence': False,
         'model_backend_enabled': False, 'labels_created': False}
Validator = Callable[[dict[str, Any]], dict[str, Any]]


class CohortError(ValueError):
    """Fixed redacted failure code; never includes supplied data or exceptions."""


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _sha(value: Any) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()


def _hash(value: Any) -> str:
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise CohortError('COHORT_INVALID_HASH')
    return str(value)


def _at(value: Any) -> datetime:
    if type(value) is not str:
        raise CohortError('COHORT_AWARE_TIMESTAMP_REQUIRED')
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        raise CohortError('COHORT_AWARE_TIMESTAMP_REQUIRED') from None
    if at.tzinfo is None or at.utcoffset() is None:
        raise CohortError('COHORT_AWARE_TIMESTAMP_REQUIRED')
    return at


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CohortError('COHORT_DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _load(raw: bytes, maximum: int) -> dict[str, Any]:
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        raise CohortError('COHORT_SIZE_BOUND')
    value = json.loads(raw, object_pairs_hook=_pairs)
    if type(value) is not dict:
        raise CohortError('COHORT_OBJECT_REQUIRED')
    _encoded(value)  # Reject NaN and infinity, including ignored metadata.
    return dict(value)


def _public(operation: str, bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verify against the executing module's public clone; no shell/network.

    Public verify replays frozen receipt versions. Its root explicitly binds the
    transitive source generation. stderr and private exception text are discarded.
    """
    script = (
        'import json,sys; from pathlib import Path; '
        'sys.path.insert(0,sys.argv[1]); import forward_versioned_producer as p; '
        'root=Path(sys.argv[1]); '
        'result=p.environment(root) if sys.argv[2]=="sources" else '
        'p.verify(json.load(sys.stdin),root=root); '
        'print(json.dumps(result,sort_keys=True,separators=(",",":"),allow_nan=False))'
    )
    try:
        process = subprocess.run(
            [sys.executable, '-I', '-B', '-c', script, str(PUBLIC_ROOT), operation],
            input=b'' if bundle is None else _encoded(bundle), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=60, check=True, cwd=PUBLIC_ROOT)
        return _load(process.stdout, MAX_BUNDLE_BYTES)
    except Exception:
        raise CohortError('COHORT_PUBLIC_VERIFICATION_FAILED') from None


def public_sources() -> dict[str, Any]:
    """Read the actual public producer's transitive source generation offline."""
    return _public('sources')


def verify_public_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Real default validator; no trust in eligibility booleans or user claims."""
    return _public('verify', bundle)


@dataclass(frozen=True)
class FrozenCohort:
    """Canonical immutable protocol and preregistration custody bytes."""

    protocol: bytes
    registration: bytes


def _protocol(value: dict[str, Any]) -> None:
    if (set(value) != {'format', 'scope', 'frozen_at', 'required_sessions',
                      'minimum_session_clusters', 'minimum_coverage_slots', 'sources',
                      'rights_document_sha256', 'method', 'context_policy',
                      'daily_config_policy', 'gap_policy'}
            or value['format'] != 'research-forward-cohort-protocol-v2'
            or value['scope'] != SCOPE
            or value['method'] != 'CHRONOLOGICAL_WALK_FORWARD_WHOLE_SESSION_GROUPS'
            or value['context_policy'] != 'ACTUALLY_RECEIVED_VERSION_KNOWN_AT_CUTOFF'
            or value['daily_config_policy'] != 'REGISTERED_OR_LATER_PREOPEN_OPTIONAL_CONFIG_PIN'
            or value['gap_policy'] != 'NO_FILL_ALL_REQUIRED_SESSIONS_MEET_COVERAGE'):
        raise CohortError('COHORT_PROTOCOL_INVALID')
    frozen = _at(value['frozen_at'])
    sessions = value['required_sessions']
    minimum = value['minimum_session_clusters']
    if (type(sessions) is not list or not 1 <= len(sessions) <= MAX_SESSIONS
            or type(minimum) is not int or not MIN_SESSION_CLUSTERS <= minimum <= MAX_SESSIONS
            or type(value['minimum_coverage_slots']) is not int
            or not 1 <= value['minimum_coverage_slots'] <= 75):
        raise CohortError('COHORT_PROTOCOL_BOUNDS')
    sources = value['sources']
    if type(sources) is not dict or not 1 <= len(sources) <= 512:
        raise CohortError('COHORT_SOURCES_REQUIRED')
    for name, sha in sources.items():
        if (type(name) is not str or len(name) > 160 or not name.endswith('.py')
                or not re.fullmatch(r'[A-Za-z0-9_./-]+', name)
                or name.startswith('/') or '..' in name.split('/')):
            raise CohortError('COHORT_SOURCE_REFERENCE_INVALID')
        _hash(sha)
    if value['rights_document_sha256'] is not None:
        _hash(value['rights_document_sha256'])
    previous_close = frozen
    for session in sessions:
        if type(session) is not dict or set(session) != {'session_open', 'session_close', 'config_sha256'}:
            raise CohortError('COHORT_SESSION_INVALID')
        opening, closing = _at(session['session_open']), _at(session['session_close'])
        # Hard exclusion of Oct 12 quarantine and all sealed historical periods.
        if (opening <= _at('2026-10-13T00:00:00+05:30') or opening <= previous_close
                or closing - opening != timedelta(minutes=375)
                or opening.utcoffset() != timedelta(hours=5, minutes=30)
                or opening.strftime('%H:%M:%S.%f') != '09:15:00.000000'):
            raise CohortError('COHORT_PROSPECTIVE_SESSION_REQUIRED')
        # Calendar admission is independent of supplied configs/capture flags.
        try:
            calendar = cast(Callable[[date], dict[str, Any]], cash_session)(opening.date())
        except Exception:
            raise CohortError('COHORT_CALENDAR_UNVERIFIED') from None
        if (calendar.get('kind') != 'REGULAR'
                or calendar.get('windows') != [('09:15', '15:30')]
                or type(calendar.get('source')) is not str or not calendar['source']):
            raise CohortError('COHORT_REGULAR_CALENDAR_SESSION_REQUIRED')
        if session['config_sha256'] is not None:
            _hash(session['config_sha256'])
        previous_close = closing


def freeze_protocol(*, required_sessions: list[dict[str, Any]], frozen_at: str,
                    registered_at: str, minimum_session_clusters: int,
                    minimum_coverage_slots: int, rights_document_sha256: str | None = None,
                    sources: dict[str, Any] | None = None) -> FrozenCohort:
    """Freeze sessions, sources and admission rules before first capture.

    sources injection is intended for offline synthetic tests. A rights hash is
    only claimed document custody; neither it nor any booleans grant a licence.
    Twenty clusters is a planning floor, not a claim of statistical power.
    A null session config hash declares the future daily owner-close config
    unknown. Its verified actual hash is pinned only at admission; dates, source
    generation and gap rules remain immutable. Optional explicit hashes must match.
    """
    try:
        value = {'format': 'research-forward-cohort-protocol-v2', 'scope': SCOPE,
                 'frozen_at': frozen_at, 'required_sessions': required_sessions,
                 'minimum_session_clusters': minimum_session_clusters,
                 'minimum_coverage_slots': minimum_coverage_slots,
                 'sources': public_sources() if sources is None else sources,
                 'rights_document_sha256': rights_document_sha256,
                 'method': 'CHRONOLOGICAL_WALK_FORWARD_WHOLE_SESSION_GROUPS',
                 'context_policy': 'ACTUALLY_RECEIVED_VERSION_KNOWN_AT_CUTOFF',
                 'daily_config_policy': 'REGISTERED_OR_LATER_PREOPEN_OPTIONAL_CONFIG_PIN',
                 'gap_policy': 'NO_FILL_ALL_REQUIRED_SESSIONS_MEET_COVERAGE'}
        raw = _encoded(value)
        _protocol(_load(raw, MAX_PROTOCOL_BYTES))
        if not _at(frozen_at) <= _at(registered_at) < _at(required_sessions[0]['session_open']):
            raise CohortError('COHORT_PREREGISTRATION_REQUIRED')
        receipt = {'format': 'research-forward-cohort-registration-v2',
                   'protocol_sha256': _sha(value), 'registered_at': registered_at}
        return FrozenCohort(raw, _encoded(receipt))
    except CohortError:
        raise
    except Exception:
        raise CohortError('COHORT_PROTOCOL_INVALID') from None


def _registration(cohort: FrozenCohort) -> tuple[dict[str, Any], datetime]:
    protocol = _load(cohort.protocol, MAX_PROTOCOL_BYTES)
    _protocol(protocol)
    receipt = _load(cohort.registration, MAX_PROTOCOL_BYTES)
    if (set(receipt) != {'format', 'protocol_sha256', 'registered_at'}
            or receipt['format'] != 'research-forward-cohort-registration-v2'
            or receipt['protocol_sha256'] != _sha(protocol)):
        raise CohortError('COHORT_REGISTRATION_CONFLICT')
    registered = _at(receipt['registered_at'])
    if not _at(protocol['frozen_at']) <= registered < _at(protocol['required_sessions'][0]['session_open']):
        raise CohortError('COHORT_PREREGISTRATION_REQUIRED')
    return protocol, registered


def _session_rows(bundle: dict[str, Any], registered: datetime,
                  assessed: datetime) -> list[dict[str, Any]]:
    config, recipe = bundle['config'], bundle['recipe']
    opening, closing = _at(config['session_open']), _at(config['session_close'])
    if (bundle['format'] != 'forward-versioned-research-bundle-v1'
            or config['instrument_key'] != 'NSE_INDEX|Nifty 50'
            or any(bundle.get(flag) is not False for flag in
                   ('training_eligible', 'approval_authority', 'fill_evidence'))
            or not registered <= _at(config['frozen_at']) <= _at(recipe['frozen_at']) < opening
            or recipe['config_sha256'] != _sha(config)):
        raise CohortError('COHORT_CAPTURE_IDENTITY_CONFLICT')
    polls = bundle['polls']
    if type(polls) is not list or len(polls) > 75:
        raise CohortError('COHORT_POLL_BOUND')
    prior_slot, prior_received, prior_computed = opening, registered, registered
    refs: list[str] = []
    versions: dict[datetime, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for poll in polls:
        source = poll['source']
        slot, received, computed = _at(source['slot']), _at(source['received_at']), _at(poll['computed_at'])
        if (source['config'] != config or source['accepted_baseline'] != []
                or source['capture_code_hash'] != _sha(recipe)
                or not prior_slot < slot <= closing
                or (slot - opening).total_seconds() % 300
                or not registered < received <= computed <= assessed
                or not prior_received < received or not prior_computed < received
                or not slot <= received <= slot + timedelta(seconds=120)):
            raise CohortError('COHORT_CAPTURE_TIME_OR_SOURCE_CONFLICT')
        prior_slot, prior_received, prior_computed = slot, received, computed
        refs.append(_sha(source))
        for bar in source['closed_bars']:
            start, known = _at(bar['start']), _at(bar['received_at'])
            if known != received or not opening <= start < slot:
                raise CohortError('COHORT_CONTEXT_TIME_CONFLICT')
            versions[start] = {'bar_start': start.astimezone(timezone.utc).isoformat(),
                               'known_at': known.astimezone(timezone.utc).isoformat(),
                               'values': bar['values'], 'finality': 'NOT_ESTABLISHED'}
        decision = poll['decision']
        if decision is None:
            continue
        projection, observation = decision['projection'], decision['observation']
        prefix = [versions[key] for key in sorted(versions)]
        expected = [opening + timedelta(minutes=5 * i)
                    for i in range(int((slot - opening).total_seconds() // 300))]
        unhashed = {key: value for key, value in projection.items() if key != 'projection_sha256'}
        if (projection['source_sha256s'] != refs or _at(projection['cutoff']) != received
                or projection['bars'] != prefix or sorted(versions) != expected
                or projection['projection_sha256'] != _sha(unhashed)
                or observation['input_hash'] != projection['projection_sha256']
                or _at(observation['decision_at']) != slot
                or _at(observation['received_at']) != computed
                or _at(observation['available_at']) != received
                or observation['spec_hash'] != _sha(recipe)
                or observation['origin'] != 'OBSERVED'
                or observation['basis'] != 'recorded_bar_end'
                or _at(observation['session_open']) != opening
                or _at(observation['session_close']) != closing):
            raise CohortError('COHORT_PIT_BINDING_CONFLICT')
        rows.append({'session_open': config['session_open'], 'slot': slot.isoformat(),
                     'known_at': received.isoformat(), 'computed_at': computed.isoformat(),
                     'projection_sha256': projection['projection_sha256'],
                     'context': json.loads(_encoded(prefix)),
                     'indicator_available': observation['available'], **FLAGS})
    count = len(rows)
    if (any(type(bundle[field]) is not int for field in
            ('expected_decisions', 'recorded_decisions', 'missing_decisions'))
            or (bundle['expected_decisions'], bundle['recorded_decisions'], bundle['missing_decisions'])
            != (75, count, 75 - count)):
        raise CohortError('COHORT_CAPTURE_COUNTS_CONFLICT')
    return rows


def assess_readiness(cohort: FrozenCohort, captures: list[bytes], *, assessed_at: str,
                     validator: Validator | None = None) -> dict[str, Any]:
    """Verify bounded actual bundle bytes; atomically return readiness or redaction.

    Missing slots stay missing. Warmup observations count as captured context,
    never as usable targets. All required sessions must finish and meet frozen
    coverage. Readiness means dataset assembly only, never predictive evidence.
    Injection replaces public replay only for synthetic offline tests.
    """
    try:
        protocol, registered = _registration(cohort)
        assessed = _at(assessed_at)
        if assessed < registered:
            raise CohortError('COHORT_ASSESSMENT_TIME_CONFLICT')
        if (type(captures) is not list or len(captures) > MAX_SESSIONS
                or any(type(raw) is not bytes or not 0 < len(raw) <= MAX_BUNDLE_BYTES for raw in captures)
                or sum(map(len, captures)) > MAX_TOTAL_BYTES):
            raise CohortError('COHORT_SIZE_BOUND')
        if validator is None and public_sources() != protocol['sources']:
            raise CohortError('COHORT_SOURCE_GENERATION_CONFLICT')
        planned = {_at(s['session_open']): s for s in protocol['required_sessions']}
        admitted: dict[datetime, tuple[str, list[dict[str, Any]], int, dict[str, Any], str]] = {}
        verify = verify_public_bundle if validator is None else validator
        for raw in captures:
            bundle = _load(raw, MAX_BUNDLE_BYTES)
            identity = _sha(bundle)
            try:
                checked = verify(bundle)
            except Exception:
                raise CohortError('COHORT_CAPTURE_VERIFICATION_FAILED') from None
            if _sha(checked) != identity or _sha(bundle) != identity:
                raise CohortError('COHORT_VALIDATOR_REWRITE_FORBIDDEN')
            config = bundle['config']
            opening = _at(config['session_open'])
            if opening not in planned or opening in admitted:
                raise CohortError('COHORT_DUPLICATE_FORK_OR_UNPLANNED_SESSION')
            session = planned[opening]
            if ((session['config_sha256'] is not None and _sha(config) != session['config_sha256'])
                    or _at(config['session_close']) != _at(session['session_close'])
                    or bundle['recipe']['sources'] != protocol['sources']):
                raise CohortError('COHORT_CONFIG_OR_SOURCE_GENERATION_CONFLICT')
            rows = _session_rows(bundle, registered, assessed)
            for row in rows:
                row.update(bundle_sha256=identity, config_sha256=_sha(config), recipe_sha256=_sha(bundle['recipe']))
            admitted[opening] = (identity, rows, len(bundle['polls']),
                                 _load(_encoded(config), MAX_BUNDLE_BYTES), _sha(bundle['recipe']))
        sessions, dataset, qualified = [], [], []
        for opening, session in planned.items():
            admission = admitted.get(opening)
            sha, rows, polls = (admission[0], admission[1], admission[2]) if admission else (None, [], 0)
            config_snapshot = admission[3] if admission else None
            complete = assessed >= _at(session['session_close'])
            covered = len(rows) >= protocol['minimum_coverage_slots'] and complete
            sessions.append({'session_open': session['session_open'], 'bundle_sha256': sha,
                             'preregistered_config_sha256': session['config_sha256'],
                             'config': config_snapshot,
                             'config_sha256': _sha(config_snapshot) if admission else None,
                             'recipe_sha256': admission[4] if admission else None,
                             'polls': polls, 'captured_slots': len(rows), 'missing_slots': 75 - len(rows),
                             'coverage': len(rows) / 75, 'session_finished': complete,
                             'coverage_met': covered, **FLAGS})
            dataset.extend(rows)
            if covered:
                qualified.append(session['session_open'])
        ready = (len(qualified) == len(planned)
                 and len(qualified) >= protocol['minimum_session_clusters'])
        # Expanding chronological session groups; no random row splits or fit.
        folds = [{'prior_session_groups': qualified[:i], 'next_session_group': qualified[i]}
                 for i in range(protocol['minimum_session_clusters'], len(qualified))] if ready else []
        return {'status': 'ASSEMBLY_READY_LICENCE_UNVERIFIED' if ready else 'INSUFFICIENT_EVIDENCE',
                'scope': SCOPE, 'protocol_sha256': _sha(protocol),
                'registration_sha256': hashlib.sha256(cohort.registration).hexdigest(),
                'assessed_at': assessed_at, 'required_sessions': len(planned),
                'minimum_session_clusters': protocol['minimum_session_clusters'],
                'minimum_coverage_slots': protocol['minimum_coverage_slots'],
                'qualified_session_clusters': len(qualified), 'sessions': sessions,
                'dataset': dataset, 'walk_forward_groups': folds,
                'licence_status': 'NOT_VERIFIED',
                'rights_document_sha256': protocol['rights_document_sha256'],
                'rights_custody': 'CLAIMED_DOCUMENT_HASH_ONLY' if protocol['rights_document_sha256'] else 'NONE',
                'registration_custody': 'LOCAL_HASH_BOUND_CLAIM_NOT_INDEPENDENT_TIMESTAMP',
                'time_authority': 'CALLER_SUPPLIED_AWARE_RECEIPTS_NOT_INDEPENDENT_CLOCK_VERIFICATION',
                'verification': 'PUBLIC_BASELINE_REPLAY' if validator is None else 'INJECTED_TEST_VALIDATOR',
                'performance_status': 'NOT_EVALUATED', **FLAGS}
    except Exception as error:
        code = str(error) if isinstance(error, CohortError) else 'COHORT_VALIDATION_FAILED'
        return {'status': 'BLOCKED', 'code': code, 'scope': SCOPE, 'dataset': [],
                'sessions': [], 'walk_forward_groups': [], 'licence_status': 'NOT_VERIFIED',
                'time_authority': 'CALLER_SUPPLIED_AWARE_RECEIPTS_NOT_INDEPENDENT_CLOCK_VERIFICATION', **FLAGS}
