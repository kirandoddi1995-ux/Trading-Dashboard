"""Synthetic reconstruction only; no real outcomes or archive data."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import outcomes_private_worker as w


def fixture(change: str = '', large: bool = False) -> tuple[bytes, Any]:
    row = dict(snapshot_id='SYNTHETIC-1', decision_id='SYNTHETIC-2',
        payload={'SYNTHETIC_ONLY': 'x' * (300000 if large else 3), 'decimal': Decimal('0.1234567890123456789')},
        recorded_at='2022-01-01T00:00:00Z')
    rows = [row] * (80 if large else 1)
    if large:
        rows = [{**r, 'snapshot_id': f'SYNTHETIC-{i:03}'} for i, r in enumerate(rows)]
    identity = w.exact({'version': w.review.FORMAT, 'table': 'equity_research.outcomes', 'rows': rows})
    batch = hashlib.sha256(identity.encode()).hexdigest()
    spec = w.review.SPECS['equity_research.outcomes']
    schema = pa.schema([pa.field(n, pa.timestamp('us', tz='UTC') if k == 'timestamptz' else pa.string()) for n, k in spec.items()]
        + [pa.field('_row_json', pa.string(), nullable=False)], metadata={b'quant_archive': w.exact(dict(
            format=w.review.FORMAT, table='equity_research.outcomes', batch_id=batch,
            postgres_types=spec, numeric_encoding='decimal-string')).encode()})
    columns: dict[str, Any] = dict(snapshot_id=[r['snapshot_id'] for r in rows],
        decision_id=[r['decision_id'] for r in rows], payload=[w.exact(r['payload']) for r in rows],
        recorded_at=[datetime(2022, 1, 1, tzinfo=timezone.utc)] * len(rows), _row_json=[w.exact(r) for r in rows])
    if change == 'column':
        columns['decision_id'][0] = 'SYNTHETIC_CORRUPT'
    if change == 'payload':
        columns['payload'][0] = '{}'
    if change == 'timestamp':
        columns['recorded_at'][0] = datetime(2022, 1, 2, tzinfo=timezone.utc)
    if change == 'duplicate':
        columns = {key: value * 2 for key, value in columns.items()}
    if change == 'whitespace':
        columns['_row_json'][0] = ' ' + columns['_row_json'][0]
    sink = io.BytesIO()
    pq.write_table(pa.Table.from_pydict(columns, schema=schema), sink, compression='zstd', use_dictionary=False)
    data = sink.getvalue()
    receipt = w.review.Receipt(batch if change != 'identity' else 'f' * 64, 'equity_research.outcomes',
        len(columns['_row_json']), hashlib.sha256(data).hexdigest(), 'synthetic-data', 'synthetic-manifest', 0, '')
    return data, receipt


def test_structural_check_matches_small_synthetic_export() -> None:
    data, receipt = fixture()
    assert w.verify_batch(data, receipt) == 1


def test_large_synthetic_profile_does_not_change_original_guard() -> None:
    data, receipt = fixture(large=True)
    with pytest.raises(ValueError, match='PARQUET_COLUMN_EXPANSION_BOUND'):
        w.review._footer(data, receipt)
    assert w.verify_batch(data, receipt) == 80
    assert w.review.MAX_COLUMN_EXPANDED == 16 * 1024**2


@pytest.mark.parametrize('change', ['column', 'payload', 'timestamp', 'identity', 'duplicate', 'whitespace'])
def test_corrupted_synthetic_columns_or_identity_rejected(change: str) -> None:
    data, receipt = fixture(change)
    with pytest.raises(ValueError):
        w.verify_batch(data, receipt)


@pytest.mark.parametrize('text', ['{}', '{"a":1,"a":2}', 'NaN', '"not a row"', 'x' * (1024**2 + 1)],
                         ids=['schema', 'duplicate', 'nonfinite', 'scalar', 'oversize'])
def test_row_contract_is_bounded(text: str) -> None:
    with pytest.raises(ValueError):
        w.decode_row(text)


def test_decimal_identity_matches_exporter_without_float_rounding() -> None:
    assert w.exact({'a': Decimal('1.000000000000000001')}) == '{"a":1.000000000000000001}'
    with pytest.raises(ValueError):
        w.exact(Decimal('NaN'))


def test_original_generation_required_before_selection() -> None:
    with pytest.raises(ValueError, match='ORIGINAL_GENERATION_PINS_REQUIRED'):
        w.verify_selected(b'{}', io.BytesIO(b''), 'a' * 64, 'b' * 64)


def test_selftest_refuses_uncontained_host_before_write_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    checks = dict.fromkeys(w.KERNEL_FIELDS, True)
    checks['nonroot'] = False
    monkeypatch.setattr(w, 'kernel_checks', lambda: checks)
    with pytest.raises(ValueError, match='KERNEL_NONROOT_UNVERIFIED'):
        w.selftest()
