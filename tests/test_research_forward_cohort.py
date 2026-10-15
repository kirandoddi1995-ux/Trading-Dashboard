"""Entirely synthetic offline cohort tests, including the actual public verifier."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, cast

import pytest

from nifty_session_calendar import cash_session
import research_forward_cohort as cohort

SOURCES = {'forward_versioned_producer.py': 'a' * 64}
FROZEN = '2026-10-15T08:50:00+05:30'
REGISTERED = '2026-10-15T08:55:00+05:30'
ASSESSED = '2026-12-31T16:00:00+05:30'


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def capture(index: int = 0, slots: tuple[int, ...] = (1, 2)) -> dict[str, Any]:
    """Minimal public-shaped fixtures; the injected validator is test-only."""
    opening = datetime.fromisoformat('2026-10-15T09:15:00+05:30')
    remaining = index
    while remaining:
        opening += timedelta(days=1)
        definition = cast(Callable[[date], dict[str, Any]], cash_session)(opening.date())
        if definition['kind'] == 'REGULAR':
            remaining -= 1
    config = {'instrument_key': 'NSE_INDEX|Nifty 50', 'session_open': opening.isoformat(),
              'session_close': (opening + timedelta(minutes=375)).isoformat(),
              'frozen_at': (opening - timedelta(minutes=15)).isoformat()}
    recipe = {'config_sha256': cohort._sha(config), 'frozen_at':
              (opening - timedelta(minutes=15)).isoformat(), 'sources': SOURCES}
    polls: list[dict[str, Any]] = []
    refs: list[str] = []
    for number in slots:
        slot = opening + timedelta(minutes=5 * number)
        received = slot + timedelta(seconds=30)
        computed = received + timedelta(seconds=1)
        bars = [{'start': utc(opening + timedelta(minutes=5 * i)),
                 'received_at': utc(received), 'values': [100, 105, 95, 101 + number, 0, 0]}
                for i in range(number)]
        source = {'config': config, 'accepted_baseline': [], 'capture_code_hash': cohort._sha(recipe),
                  'slot': utc(slot), 'received_at': utc(received), 'closed_bars': bars}
        refs.append(cohort._sha(source))
        projection: dict[str, Any] = {'source_sha256s': list(refs), 'cutoff': utc(received),
            'bars': [{'bar_start': bar['start'], 'known_at': bar['received_at'],
                      'values': bar['values'], 'finality': 'NOT_ESTABLISHED'} for bar in bars]}
        projection['projection_sha256'] = cohort._sha(projection)
        observation = {'input_hash': projection['projection_sha256'], 'decision_at': utc(slot),
            'received_at': utc(computed), 'available_at': utc(received),
            'spec_hash': cohort._sha(recipe), 'available': False, 'origin': 'OBSERVED',
            'basis': 'recorded_bar_end', 'session_open': utc(opening),
            'session_close': utc(opening + timedelta(minutes=375))}
        polls.append({'source': source, 'computed_at': utc(computed),
                      'decision': {'projection': projection, 'observation': observation}})
    return {'format': 'forward-versioned-research-bundle-v1', 'config': config, 'recipe': recipe,
            'polls': polls, 'recorded_decisions': len(polls), 'missing_decisions': 75 - len(polls),
            'expected_decisions': 75, 'training_eligible': False, 'approval_authority': False,
            'fill_evidence': False}


def freeze(bundles: list[dict[str, Any]], **changes: Any) -> cohort.FrozenCohort:
    options: dict[str, Any] = {'required_sessions': [
        {'session_open': b['config']['session_open'], 'session_close': b['config']['session_close'],
         'config_sha256': cohort._sha(b['config'])} for b in bundles],
        'frozen_at': FROZEN, 'registered_at': REGISTERED,
        'minimum_session_clusters': 20, 'minimum_coverage_slots': 2, 'sources': SOURCES}
    options.update(changes)
    return cohort.freeze_protocol(**options)


def identity(bundle: dict[str, Any]) -> dict[str, Any]:
    return bundle


def assess(protocol: cohort.FrozenCohort, bundles: list[dict[str, Any]],
           **kwargs: Any) -> dict[str, Any]:
    return cohort.assess_readiness(protocol, [cohort._encoded(b) for b in bundles],
                                   assessed_at=ASSESSED, validator=identity, **kwargs)


def assert_no_authority(result: dict[str, Any]) -> None:
    for flag in cohort.FLAGS:
        assert result[flag] is False
    assert result['licence_status'] == 'NOT_VERIFIED'


def test_few_sessions_are_insufficient_actual_context_is_not_rewritten() -> None:
    bundle = capture()
    protocol = freeze([bundle], rights_document_sha256='d' * 64)
    result = assess(protocol, [bundle])
    assert result['status'] == 'INSUFFICIENT_EVIDENCE'
    assert result['qualified_session_clusters'] == 1
    assert result['dataset'][0]['context'][0]['values'][3] == 102
    assert result['dataset'][1]['context'][0]['values'][3] == 103
    assert result['dataset'][0]['known_at'] != result['dataset'][1]['known_at']
    assert result['sessions'][0]['missing_slots'] == 73
    assert result['performance_status'] == 'NOT_EVALUATED'
    assert result['walk_forward_groups'] == []
    assert result['rights_custody'] == 'CLAIMED_DOCUMENT_HASH_ONLY'
    assert_no_authority(result)
    assert json.loads(protocol.protocol)['rights_document_sha256'] == 'd' * 64
    bundle['polls'][0]['source']['closed_bars'][0]['values'][3] = 999
    assert result['dataset'][0]['context'][0]['values'][3] == 102
    with pytest.raises(FrozenInstanceError):
        setattr(protocol, 'protocol', b'changed')


def test_dataset_ready_only_for_all_covered_finished_session_clusters() -> None:
    bundles = [capture(i) for i in range(21)]
    protocol = freeze(bundles)
    result = assess(protocol, list(reversed(bundles)))
    assert result['status'] == 'ASSEMBLY_READY_LICENCE_UNVERIFIED'
    assert len(result['dataset']) == 42
    assert result['qualified_session_clusters'] == 21
    folds = result['walk_forward_groups']
    assert len(folds) == 1
    assert len(folds[0]['prior_session_groups']) == 20
    assert folds[0]['next_session_group'] == bundles[-1]['config']['session_open']
    assert folds[0]['next_session_group'] not in folds[0]['prior_session_groups']
    assert_no_authority(result)
    missing = assess(protocol, bundles[:-1])
    assert missing['status'] == 'INSUFFICIENT_EVIDENCE'
    assert missing['sessions'][-1]['missing_slots'] == 75
    in_progress = cohort.assess_readiness(protocol, [cohort._encoded(bundles[0])],
        assessed_at='2026-10-15T10:00:00+05:30', validator=identity)
    assert in_progress['qualified_session_clusters'] == 0


def test_blocked_poll_and_late_poll_do_not_fill_missing_observations() -> None:
    bundle = capture(slots=(3, 4))
    bundle['polls'][0]['decision'] = None
    bundle.update(recorded_decisions=1, missing_decisions=74)
    result = assess(freeze([bundle]), [bundle])
    assert result['status'] == 'INSUFFICIENT_EVIDENCE'
    assert len(result['dataset']) == 1
    assert result['sessions'][0]['polls'] == 2
    assert result['sessions'][0]['missing_slots'] == 74


def test_many_intraday_rows_are_still_one_cluster_and_no_targets() -> None:
    bundle = capture(slots=tuple(range(1, 76)))
    result = assess(freeze([bundle], minimum_coverage_slots=75), [bundle])
    assert result['status'] == 'INSUFFICIENT_EVIDENCE'
    assert result['qualified_session_clusters'] == 1
    assert len(result['dataset']) == 75
    assert result['sessions'][0]['missing_slots'] == 0
    assert all('direction' not in row and 'target' not in row for row in result['dataset'])
    assert_no_authority(result)


def test_config_freeze_before_registration_is_rejected_even_with_matching_config_hash() -> None:
    bundle = capture()
    bundle['config']['frozen_at'] = '2026-10-15T08:51:00+05:30'
    protocol = freeze([bundle])
    result = assess(protocol, [bundle])
    assert result['code'] == 'COHORT_CAPTURE_IDENTITY_CONFLICT'


def test_unknown_future_daily_configs_work_for_twenty_preregistered_sessions() -> None:
    bundles = [capture(i) for i in range(20)]
    sessions = [{'session_open': b['config']['session_open'],
                 'session_close': b['config']['session_close'], 'config_sha256': None}
                for b in bundles]
    protocol = freeze(bundles, required_sessions=sessions)
    frozen = json.loads(protocol.protocol)
    assert all(s['config_sha256'] is None for s in frozen['required_sessions'])
    result = assess(protocol, bundles)
    assert result['status'] == 'ASSEMBLY_READY_LICENCE_UNVERIFIED'
    assert result['qualified_session_clusters'] == 20
    assert_no_authority(result)
    for bundle, admitted in zip(bundles, result['sessions']):
        assert datetime.fromisoformat(bundle['config']['frozen_at']) >= datetime.fromisoformat(REGISTERED)
        assert admitted['config'] == bundle['config']
        assert admitted['config_sha256'] == cohort._sha(bundle['config'])
        assert admitted['preregistered_config_sha256'] is None
    before = deepcopy(result['sessions'][-1]['config'])
    bundles[-1]['config']['owner_claim'] = 'changed after report'
    assert result['sessions'][-1]['config'] == before
    assert json.loads(protocol.protocol) == frozen


@pytest.mark.parametrize('frozen_at', [
    '2026-10-15T08:54:59+05:30', '2026-10-16T09:15:00+05:30',
    '2026-10-16T09:16:00+05:30', '2026-10-16T09:00:00',
])
def test_unknown_daily_config_must_freeze_after_registration_before_open(frozen_at: str) -> None:
    bundle = capture(1)
    bundle['config']['frozen_at'] = frozen_at
    protocol = freeze([bundle], required_sessions=[{
        'session_open': bundle['config']['session_open'],
        'session_close': bundle['config']['session_close'], 'config_sha256': None}])
    result = assess(protocol, [bundle])
    assert result['status'] == 'BLOCKED'
    assert_no_authority(result)


def test_registration_equal_daily_freeze_is_permitted_and_optional_pin_enforced() -> None:
    bundle = capture()
    # Test a legitimate daily config frozen exactly at registration, then recipe.
    bundle['config']['frozen_at'] = REGISTERED
    bundle['recipe']['config_sha256'] = cohort._sha(bundle['config'])
    for poll in bundle['polls']:
        poll['source']['capture_code_hash'] = cohort._sha(bundle['recipe'])
        poll['decision']['observation']['spec_hash'] = cohort._sha(bundle['recipe'])
    refs: list[str] = []
    for poll in bundle['polls']:
        refs.append(cohort._sha(poll['source']))
        projection = poll['decision']['projection']
        projection['source_sha256s'] = list(refs)
        projection['projection_sha256'] = cohort._sha({
            key: value for key, value in projection.items() if key != 'projection_sha256'})
        poll['decision']['observation']['input_hash'] = projection['projection_sha256']
    protocol = freeze([bundle])
    assert assess(protocol, [bundle])['status'] == 'INSUFFICIENT_EVIDENCE'
    wrong_pin = json.loads(protocol.protocol)['required_sessions']
    wrong_pin[0]['config_sha256'] = 'f' * 64
    assert assess(freeze([bundle], required_sessions=wrong_pin), [bundle])['code'] == 'COHORT_CONFIG_OR_SOURCE_GENERATION_CONFLICT'


@pytest.mark.parametrize('day', ['2026-10-17', '2026-10-20', '2026-11-08', '2027-01-04'])
def test_calendar_independently_rejects_weekends_holidays_special_and_unreviewed_year(day: str) -> None:
    opening = datetime.fromisoformat(day + 'T09:15:00+05:30')
    with pytest.raises(cohort.CohortError, match='COHORT_.*CALENDAR'):
        freeze([capture()], required_sessions=[{
            'session_open': opening.isoformat(),
            'session_close': (opening + timedelta(minutes=375)).isoformat(),
            'config_sha256': None}])


@pytest.mark.parametrize('definition', [
    {'kind': 'REGULAR', 'windows': [('09:15', '15:30')]},
    {'kind': 'REGULAR', 'windows': None, 'source': 'synthetic'},
    {'kind': 'REGULAR', 'windows': [('09:15', '15:30')], 'source': ''},
])
def test_calendar_missing_metadata_fails_closed(monkeypatch: pytest.MonkeyPatch,
                                              definition: dict[str, Any]) -> None:
    monkeypatch.setattr(cohort, 'cash_session', lambda day: definition)
    with pytest.raises(cohort.CohortError, match='COHORT_REGULAR_CALENDAR_SESSION_REQUIRED'):
        freeze([capture()])


def test_default_root_is_executing_module_clone() -> None:
    assert cohort.PUBLIC_ROOT == Path(cohort.__file__).resolve().parent


def test_equivalent_aware_assessment_timestamp_and_protocol_caller_mutation() -> None:
    bundle = capture()
    sessions = [{'session_open': bundle['config']['session_open'],
                 'session_close': bundle['config']['session_close'],
                 'config_sha256': cohort._sha(bundle['config'])}]
    protocol = freeze([bundle], required_sessions=sessions)
    sessions[0]['config_sha256'] = 'f' * 64
    result = cohort.assess_readiness(protocol, [cohort._encoded(bundle)],
        assessed_at='2026-12-31T10:30:00+00:00', validator=identity)
    assert result['status'] == 'INSUFFICIENT_EVIDENCE'
    assert len(result['dataset']) == 2


def test_poll_count_bound_and_unfinished_reception_are_fail_closed() -> None:
    bundle = capture()
    protocol = freeze([bundle])
    broken = deepcopy(bundle)
    broken['polls'] *= 38
    assert assess(protocol, [broken])['code'] == 'COHORT_POLL_BOUND'
    result = cohort.assess_readiness(protocol, [cohort._encoded(bundle)],
        assessed_at='2026-10-15T09:25:30+05:30', validator=identity)
    assert result['status'] == 'BLOCKED'


@pytest.mark.parametrize('damage', [
    'duplicate', 'fork', 'config', 'sources', 'mixed_refs', 'future_context',
    'rewritten_context', 'hash', 'naive', 'receipt_backwards', 'computed_backwards',
    'duplicate_slot', 'replay', 'counts', 'training', 'quarantine', 'before_registration'])
def test_capture_conflicts_fail_closed_without_partial_dataset(damage: str) -> None:
    bundle = capture()
    protocol = freeze([bundle])
    damaged = deepcopy(bundle)
    if damage == 'duplicate':
        inputs = [bundle, damaged]
    elif damage == 'fork':
        damaged['polls'].pop()
        inputs = [bundle, damaged]
    else:
        inputs = [damaged]
        poll = damaged['polls'][1]
        if damage == 'config':
            damaged['config']['unexpected'] = True
        elif damage == 'sources':
            damaged['recipe']['sources'] = {'foreign.py': 'f' * 64}
        elif damage == 'mixed_refs':
            poll['decision']['projection']['source_sha256s'][0] = 'f' * 64
        elif damage == 'future_context':
            poll['decision']['projection']['bars'][0]['known_at'] = ASSESSED
        elif damage == 'rewritten_context':
            damaged['polls'][0]['decision']['projection']['bars'][0]['values'][3] = 999
        elif damage == 'hash':
            poll['decision']['projection']['projection_sha256'] = 'f' * 64
        elif damage == 'naive':
            poll['computed_at'] = '2026-10-15T09:25:31'
        elif damage == 'receipt_backwards':
            poll['source']['received_at'] = damaged['polls'][0]['source']['received_at']
        elif damage == 'computed_backwards':
            damaged['polls'][0]['computed_at'] = ASSESSED
        elif damage == 'duplicate_slot':
            poll['source']['slot'] = damaged['polls'][0]['source']['slot']
        elif damage == 'replay':
            poll['decision']['observation']['origin'] = 'REPLAY'
        elif damage == 'counts':
            damaged['recorded_decisions'] = 75
        elif damage == 'training':
            damaged['training_eligible'] = True
        elif damage == 'quarantine':
            damaged['format'] = 'quarantined-as-of-source-versions-v1'
        else:
            damaged['polls'][0]['source']['received_at'] = REGISTERED
    result = assess(protocol, inputs)
    assert result['status'] == 'BLOCKED'
    assert result['dataset'] == [] and result['sessions'] == []
    assert_no_authority(result)


@pytest.mark.parametrize('changes', [
    {'registered_at': '2026-10-15T09:15:00+05:30'},
    {'registered_at': '2026-10-15T08:49:00+05:30'},
    {'registered_at': '2026-10-15T08:55:00'},
    {'minimum_session_clusters': 2}, {'minimum_coverage_slots': 0},
    {'minimum_coverage_slots': True}, {'rights_document_sha256': True},
    {'sources': {}}, {'sources': {'../foreign.py': 'a' * 64}},
])
def test_protocol_is_preregistered_aware_bounded_and_rights_are_not_booleans(changes: dict[str, Any]) -> None:
    with pytest.raises(cohort.CohortError):
        freeze([capture()], **changes)


def test_no_quarantined_or_sealed_historical_sessions_or_duplicate_plan() -> None:
    for opening in ['2026-10-12T09:15:00+05:30', '2025-01-03T09:15:00+05:30']:
        bundle = capture()
        bundle['config']['session_open'] = opening
        bundle['config']['session_close'] = (datetime.fromisoformat(opening) + timedelta(minutes=375)).isoformat()
        with pytest.raises(cohort.CohortError):
            freeze([bundle], frozen_at='2025-01-01T08:00:00+05:30', registered_at='2025-01-01T08:01:00+05:30')
    with pytest.raises(cohort.CohortError):
        freeze([capture(), capture()])


def test_registration_hash_conflict_and_redacted_validator_failures() -> None:
    bundle = capture()
    protocol = freeze([bundle])
    bad = cohort.FrozenCohort(protocol.protocol.replace(b'coverage_slots":2', b'coverage_slots":3'),
                              protocol.registration)
    assert assess(bad, [bundle])['status'] == 'BLOCKED'

    def secret_failure(value: dict[str, Any]) -> dict[str, Any]:
        raise cohort.CohortError('private-token-and-price')

    result = cohort.assess_readiness(protocol, [cohort._encoded(bundle)],
                                    assessed_at=ASSESSED, validator=secret_failure)
    assert result['code'] == 'COHORT_CAPTURE_VERIFICATION_FAILED'
    assert 'private' not in json.dumps(result)

    def rewrite(value: dict[str, Any]) -> dict[str, Any]:
        value['missing_decisions'] = 0
        return value

    result = cohort.assess_readiness(protocol, [cohort._encoded(bundle)],
                                    assessed_at=ASSESSED, validator=rewrite)
    assert result['code'] == 'COHORT_VALIDATOR_REWRITE_FORBIDDEN'


def test_bounds_and_duplicate_json_keys_before_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    protocol = freeze([capture()])

    def forbidden(value: dict[str, Any]) -> dict[str, Any]:
        pytest.fail('validator should not run')

    for raw in [b'{"secret":1,"secret":2}', b'{"price":NaN}', b'[]']:
        result = cohort.assess_readiness(protocol, [raw], assessed_at=ASSESSED, validator=forbidden)
        assert result['status'] == 'BLOCKED'
    for captures in [[b'{}'] * 129, [b'x' * (cohort.MAX_BUNDLE_BYTES + 1)]]:
        assert cohort.assess_readiness(protocol, captures, assessed_at=ASSESSED,
                                       validator=forbidden)['code'] == 'COHORT_SIZE_BOUND'
    monkeypatch.setattr(cohort, 'MAX_TOTAL_BYTES', 3)
    assert cohort.assess_readiness(protocol, [b'{}', b'{}'], assessed_at=ASSESSED,
                                   validator=forbidden)['code'] == 'COHORT_SIZE_BOUND'


@pytest.fixture(scope='module')
def public_bundle() -> dict[str, Any]:
    """Generate synthetic received versions using public packages, without journals."""
    script = '''
import json, sys
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, sys.argv[1])
import forward_versioned_producer as p
from forward_nifty_producer import prepare_config
from forward_revision_quarantine import snapshot
from research_integrity import hash_value
root = Path(sys.argv[1])
config = prepare_config('2026-10-15', 24900, 'a'*64, '2026-10-15T09:00:00+05:30', root=root)
recipe = p.recipe(config, '2026-10-15T09:00:00+05:30', root=root)
opening = datetime.fromisoformat(config['session_open'])
polls, sources = [], []
for n in (1, 2):
    at = opening + timedelta(minutes=5*n, seconds=30)
    bars = [[(opening+timedelta(minutes=5*i)).isoformat(),24900,24920,24890,24905+n,0,0] for i in range(n)]
    source = snapshot(config, bars, at.isoformat(), [], hash_value(recipe))
    sources.append(source)
    computed = (at+timedelta(seconds=1)).isoformat()
    decision = p._decision(config, recipe, sources, computed)
    polls.append(dict(source=source, decision=decision, computed_at=computed))
bundle = dict(format=p.FORMAT, config=config, recipe=recipe, polls=polls,
    recorded_decisions=2, missing_decisions=73, expected_decisions=75,
    training_eligible=False, approval_authority=False, fill_evidence=False)
p.verify(bundle, root=root)
print(json.dumps(bundle))
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(cohort.PUBLIC_ROOT)],
                            capture_output=True, check=True, timeout=60, cwd=cohort.PUBLIC_ROOT)
    value: dict[str, Any] = json.loads(result.stdout)
    return value


def test_real_default_public_baseline_replay(public_bundle: dict[str, Any]) -> None:
    protocol = freeze([public_bundle], sources=cohort.public_sources(), required_sessions=[{
        'session_open': public_bundle['config']['session_open'],
        'session_close': public_bundle['config']['session_close'], 'config_sha256': None}])
    result = cohort.assess_readiness(protocol, [cohort._encoded(public_bundle)], assessed_at=ASSESSED)
    assert result['status'] == 'INSUFFICIENT_EVIDENCE', result
    assert result['verification'] == 'PUBLIC_BASELINE_REPLAY'
    assert len(result['dataset']) == 2
    assert result['dataset'][0]['context'][0]['values'][3] == 24906
    assert result['dataset'][1]['context'][0]['values'][3] == 24907
    assert result['sessions'][0]['config'] == public_bundle['config']
    assert result['sessions'][0]['config_sha256'] == cohort._sha(public_bundle['config'])
    assert result['sessions'][0]['preregistered_config_sha256'] is None
    assert result['time_authority'] == 'CALLER_SUPPLIED_AWARE_RECEIPTS_NOT_INDEPENDENT_CLOCK_VERIFICATION'
    assert_no_authority(result)
    broken = deepcopy(public_bundle)
    broken['polls'][0]['decision']['observation']['direction'] = 1
    result = cohort.assess_readiness(protocol, [cohort._encoded(broken)], assessed_at=ASSESSED)
    assert result['code'] == 'COHORT_CAPTURE_VERIFICATION_FAILED'


def test_default_source_generation_drift_blocks_before_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    protocol = freeze([capture()])
    monkeypatch.setattr(cohort, 'public_sources', lambda: {'different.py': 'f' * 64})
    result = cohort.assess_readiness(protocol, [], assessed_at=ASSESSED)
    assert result['code'] == 'COHORT_SOURCE_GENERATION_CONFLICT'


def test_default_freeze_uses_actual_public_source_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []

    def sources() -> dict[str, Any]:
        calls.append(cohort.PUBLIC_ROOT)
        return SOURCES

    monkeypatch.setattr(cohort, 'public_sources', sources)
    protocol = freeze([capture()], sources=None)
    assert calls == [cohort.PUBLIC_ROOT]
    assert json.loads(protocol.protocol)['sources'] == SOURCES
