"""Offline checklist never turns receipt references into deletion permission."""
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from storage_commissioning import Cycle, REQUIRED_PROOFS, evaluate
from storage_policy import BUDGETS, CATALOG_ALLOWANCE_BYTES, Measurement

NOW = datetime.fromisoformat('2026-10-17T09:00:00+05:30')
RELATIONS = {b.name: b.allocated_bytes for b in BUDGETS}
SIZE = sum(RELATIONS.values()) + CATALOG_ALLOWANCE_BYTES


def inputs():
    days = [date(2026, 10, 5)+timedelta(days=i) for i in range(12)
            if (date(2026, 10, 5)+timedelta(days=i)).weekday() < 5]
    return dict(measurement=Measurement(NOW, SIZE, dict(RELATIONS)), now=NOW,
                receipt_hashes={name: 'a'*64 for name in REQUIRED_PROOFS},
                cycles=[Cycle(day, SIZE+1000, SIZE, True, True, False) for day in days],
                steady_state_growth_bound_bytes=1_000_000)


def test_full_checklist_is_not_verified_receipts_or_deletion_authority():
    result = evaluate(**inputs())
    assert result['status'] == 'CHECKLIST_COMPLETE_REQUIRES_RECEIPT_VERIFICATION'
    assert not result['receipts_verified_by_tool'] and not result['deletion_authorised']
    assert result['approval_authority'] is False and result['hosted_changes'] == 0


@pytest.mark.parametrize('name', REQUIRED_PROOFS)
def test_every_required_proof_blocks_when_missing(name):
    args = inputs()
    del args['receipt_hashes'][name]
    result = evaluate(**args)
    assert result['status'] == 'NOT_COMMISSIONED' and name in result['missing_proofs']


def test_current_owner_size_not_permanent_acceptance():
    args = inputs()
    args['measurement'] = Measurement(NOW, 455_555_893, {})
    args['cycles'] = []
    args['receipt_hashes'] = {}
    result = evaluate(**args)
    assert result['status'] == 'NOT_COMMISSIONED'
    assert 'NONESSENTIAL_WRITE_PAUSE' in result['blockers']
    assert 'STORAGE_OBSERVATION_WINDOW_INCOMPLETE' in result['blockers']


@pytest.mark.parametrize('field,value', [('collection_complete', False), ('archive_verified', False),
    ('backlog_growing', True), ('peak_bytes', 350_000_000)])
def test_all_modes_archive_backlog_and_peak_matter(field, value):
    args = inputs()
    args['cycles'][0] = replace(args['cycles'][0], **{field: value})
    assert 'STORAGE_CYCLE_NOT_STEADY' in evaluate(**args)['blockers']


def test_stale_or_unknown_inventory_not_hidden():
    args = inputs()
    args['measurement'] = Measurement(NOW-timedelta(seconds=61), SIZE, dict(RELATIONS))
    assert 'STORAGE_MEASUREMENT_STALE_OR_FUTURE' in evaluate(**args)['blockers']
    args['measurement'] = Measurement(NOW, SIZE, dict(RELATIONS, unbudgeted=1))
    assert 'UNBUDGETED_RELATION' in evaluate(**args)['blockers']


@pytest.mark.parametrize('bad', [True, -1, 1.5])
def test_invalid_growth_bound(bad):
    args = inputs()
    args['steady_state_growth_bound_bytes'] = bad
    with pytest.raises(ValueError, match='BOUND_INVALID'): evaluate(**args)


def test_growth_bound_includes_metadata_not_just_current_size():
    args = inputs()
    args['steady_state_growth_bound_bytes'] = 350_000_000-SIZE
    assert 'STORAGE_STEADY_STATE_BOUND_EXCEEDED' in evaluate(**args)['blockers']


def test_missing_duplicate_future_closed_and_unordered_sessions():
    args = inputs()
    args['cycles'].pop(2)
    assert 'STORAGE_CYCLE_SESSION_COVERAGE_INCOMPLETE' in evaluate(**args)['blockers']
    for day in [args['cycles'][0].session_date, date(2026, 10, 17)]:
        args = inputs()
        args['cycles'][-1] = replace(args['cycles'][-1], session_date=day)
        with pytest.raises(ValueError, match='DATES_INVALID'): evaluate(**args)
    args = inputs()
    args['cycles'][0] = replace(args['cycles'][0], session_date=date(2026, 10, 4))
    assert 'STORAGE_CYCLE_SESSION_COVERAGE_INCOMPLETE' in evaluate(**args)['blockers']


@pytest.mark.parametrize('field,value', [('after_bytes', 0), ('after_bytes', True),
    ('peak_bytes', SIZE-1), ('archive_verified', 'true')])
def test_invalid_cycle_measurement(field, value):
    args = inputs()
    args['cycles'][0] = replace(args['cycles'][0], **{field: value})
    with pytest.raises(ValueError, match='CYCLE_INVALID'): evaluate(**args)


def test_unknown_or_unverified_hash_shape_fails_closed():
    args = inputs()
    args['receipt_hashes']['unknown'] = 'a'*64
    with pytest.raises(ValueError, match='PROOF_UNKNOWN'): evaluate(**args)
    args = inputs()
    args['receipt_hashes'][REQUIRED_PROOFS[0]] = 'green CI'
    with pytest.raises(ValueError, match='HASH_INVALID'): evaluate(**args)
