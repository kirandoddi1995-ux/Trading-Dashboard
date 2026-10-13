"""Expanded actual methods; independent native registry remains unchanged."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest
import storage_write_guard as guard
from overnight_storage_contracts import ContractError, digest
from overnight_storage_factory_adapter import FactoryCoverage
from overnight_storage_harness import START
from overnight_storage_repository_routes import FAMILIES, compile_registry, invoke_repository
from overnight_storage_staged_factories import STAGED_METHODS
from overnight_storage_switching import REQUIRED, inventory
from tests.test_overnight_storage_staged_factories import AcceptanceDriver


ROOT = Path(__file__).resolve().parents[1]


def registry_sources() -> dict[str, bytes]:
    return {path: (ROOT / path).read_bytes() for path in REQUIRED if (ROOT / path).is_file()}


def coverage(family: str) -> FactoryCoverage:
    return FactoryCoverage((family,), (family,), digest(b'fixture inventory'), digest(b'fixture migration'))


class Driver(AcceptanceDriver):
    rowcount = 1


CASES: tuple[tuple[str, str, Sequence[object], Mapping[str, object]], ...] = (
    ('production', 'finish_run', ('synthetic',), {'status': 'COMPLETE'}),
    ('production', 'mark_enrichment_checked', ('synthetic', 'synthetic', 'COMPLETE'), {}),
    ('production', 'record_quality_event', ('synthetic', 'INFO', 'FIXTURE', 'synthetic'), {}),
    ('equity_scan', 'heartbeat', ('synthetic', 1), {}),
    ('equity_scan', 'save_manual_review', ({'review_id': 'synthetic', 'decision_id': 'synthetic',
        'decision_digest': digest(b'synthetic'), 'instrument': 'synthetic', 'reviewer': 'synthetic',
        'attested_at': 1, 'secondary_platform': 'synthetic', 'secondary_price': 1,
        'primary_price': 1, 'difference_bps': 0, 'status': 'PASS'},), {}),
    ('derivative', 'set_monitor_state', ('synthetic', 'READY', START, 60), {}),
    ('derivative', 'save_position', ('synthetic', {'account_key': 'synthetic',
        'instrument_key': 'synthetic', 'product': 'synthetic'}, START), {}),
    ('derivative', 'alert', ('synthetic', START), {}),
    ('derivative', 'clear_alert', ('synthetic',), {}),
    ('derivative', 'acknowledge', ('synthetic', START), {}),
    ('derivative', 'finish_email', ('synthetic', 'synthetic', START), {'success': True, 'attempts': 1}),
)


@pytest.mark.parametrize('family,method,args,kwargs', CASES)
@pytest.mark.parametrize('fault', ['', 'fencing', 'full_disk', 'commit_reply_lost'])
def test_expanded_existing_method(family: str, method: str, args: Sequence[object],
        kwargs: Mapping[str, object], fault: str) -> None:
    sources = registry_sources()
    route = compile_registry(sources, {p: digest(v) for p, v in sources.items()}).find(family, method)
    driver = Driver(fault)
    if fault:
        with pytest.raises((guard.GuardError, OSError)):
            invoke_repository(driver, route, args, kwargs, coverage=coverage(family), clock=lambda: START)
        assert driver.commits == int(fault == 'commit_reply_lost')
    else:
        _, receipt = invoke_repository(driver, route, args, kwargs, coverage=coverage(family), clock=lambda: START)
        assert driver.legacy_writes and driver.commits == 1
        assert receipt.status == 'COMMITTED' and not receipt.global_enforcement_commissioned


def test_every_observed_method_has_exact_disposition_and_no_native_expansion() -> None:
    sources = registry_sources()
    result = compile_registry(sources, {p: digest(v) for p, v in sources.items()})
    assert len(result.routes) == 45
    assert set(inventory(sources).callables) <= {d.identity for d in result.dispositions}
    assert all(d.reason for d in result.dispositions)
    assert [(m.factory, m.method) for m in STAGED_METHODS] == [
        ('production', 'start_run'), ('equity_scan', 'create_run'), ('derivative', 'mark_pending')]
    assert 'ledger_historical_repository.py' not in REQUIRED
    missing = compile_registry({}, {})
    assert {d.identity for d in missing.dispositions} == set(REQUIRED)


def test_bad_source_pin_and_tampered_sql_fail_before_guard() -> None:
    sources = registry_sources()
    pins = {p: digest(v) for p, v in sources.items()}
    route = compile_registry(sources, pins).find('derivative', 'alert')
    pins[FAMILIES['derivative'][0]] = digest(b'wrong')
    with pytest.raises(ContractError, match='PIN_MISMATCH'):
        compile_registry(sources, pins)
    altered = replace(route, profile=replace(route.profile, sql=('SELECT dangerous_function()',)))
    driver = Driver()
    with pytest.raises(ContractError, match='TAMPERED'):
        invoke_repository(driver, altered, (), {}, coverage=coverage('derivative'), clock=lambda: START)
    assert not driver.legacy_writes and driver.commits == 0
