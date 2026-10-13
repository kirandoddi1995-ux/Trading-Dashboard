"""Signed exact cold result rows drive the unchanged business readers."""
from __future__ import annotations

from collections.abc import Sequence

import pytest
import catalog_receipts as receipts
import cold_catalog as catalog
from overnight_storage_cold_methods import ColdMethodDriver, query_key, rowset_bytes
from overnight_storage_contracts import Candidate, CatalogCut, ContractError, digest
from overnight_storage_harness import START, SYNTHETIC_KEY, SyntheticTier
from overnight_storage_repository_routes import compile_registry, invoke_repository
from tests.test_overnight_storage_repository_routes import coverage, registry_sources


@pytest.mark.parametrize('family,method,args,rows,expected', [
    ('derivative', 'positions', (), [['synthetic', {'instrument_key': 'fixture'}]],
     {'synthetic': {'instrument_key': 'fixture'}}),
    ('derivative', 'alerts', (), [['id', 'code', 'time', None, None, None]],
     [{'alert_id': 'id', 'code': 'code', 'last_seen': 'time', 'acknowledged_at': None,
       'delivered_at': None, 'last_error': None}]),
    ('equity_scan', 'latest_manual_review', ('synthetic',), [[{'status': 'PASS'}]], {'status': 'PASS'}),
    ('equity_scan', 'unresolved_orders', ('synthetic',), [[{'intent_id': 'fixture'}]], [{'intent_id': 'fixture'}]),
])
@pytest.mark.parametrize('fault', ['', 'corrupt', 'partial', 'wrong_query', 'revision', 'missing_key'])
def test_actual_reader_exact_authenticated_rows(family: str, method: str,
        args: Sequence[object], rows: Sequence[Sequence[object]], expected: object, fault: str) -> None:
    sources = registry_sources()
    route = compile_registry(sources, {p: digest(v) for p, v in sources.items()}).find(family, method)
    sql = route.profile.sql[0]
    parameters: Sequence[object] | None = tuple(args) if args else None
    raw = rowset_bytes(sql, ('wrong',) if fault == 'wrong_query' else parameters, rows)
    candidate = Candidate(route.profile.tables[0].replace('.', '__'), 'fixture', 1,
                          START.replace(year=2025), START, digest(raw), len(raw), digest(raw))
    patch = catalog.Catalog(catalog.EMPTY_ROOT, lambda _: None).patch({candidate.identity: candidate.metadata()})
    previous = receipts.genesis('overnight:synthetic')
    signed = receipts.sign(previous, patch.root, digest(raw), START, 'synthetic', SYNTHETIC_KEY)
    cut = CatalogCut(previous, signed.anchor, signed.data)
    tier = SyntheticTier('disk', {digest(raw): raw}, fault if fault in {'corrupt', 'partial'} else '')
    if fault == 'revision':
        from dataclasses import replace
        candidate = replace(candidate, revision=2)
    driver = ColdMethodDriver(START, route, {query_key(sql, parameters): candidate}, cut,
        {} if fault == 'missing_key' else {'synthetic': SYNTHETIC_KEY}, patch.pages.get, (tier,))
    if fault:
        with pytest.raises((ContractError, receipts.ReceiptError)):
            invoke_repository(driver, route, args, {}, coverage=coverage(family), clock=lambda: START)
        assert driver.commits == 0
    else:
        result, receipt = invoke_repository(driver, route, args, {}, coverage=coverage(family), clock=lambda: START)
        assert result == expected and driver.reads == 1
        assert receipt.status == 'COMMITTED' and receipt.before_bytes == receipt.after_bytes


def test_query_codec_refuses_unsupported_parameters_and_nonfinite() -> None:
    for value in (object(), float('nan')):
        with pytest.raises(ContractError):
            query_key('SELECT fixture', (value,))
