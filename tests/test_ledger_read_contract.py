"""Read-only contract and exact native timestamp/schema failure regressions."""
from __future__ import annotations

from collections.abc import Sequence
import json
from typing import Any

import pytest

from ledger_read_contract import begin_read_snapshot
from ledger_source_capture import SourceCapture, SourceCaptureError
from ledger_segments import FIELDS, verify_records

pytest_plugins = ('test_ledger_cold_store',)


@pytest.mark.parametrize('spelling', ['2026-10-06T00:00:00.1234+00:00',
                                     '2026-10-06T05:30:00.1234+05:30'])
def test_native_timestamp_restores_signer_material_without_changing_source(history: Any,
                                                                         spelling: str) -> None:
    sources, ring = history
    row = {key: sources['one'][0][key] for key in FIELDS}
    row['recorded_at'] = row['effective_at'] = spelling
    native = json.dumps(row)
    capture = SourceCapture((native,))
    result = capture.records()
    assert result[0]['recorded_at'] == '2026-10-06T00:00:00.123400+00:00'
    assert verify_records(result, {}, ring)['one'] == (1, row['event_hash'])
    assert capture.row_texts == (native,)
    assert spelling not in repr(capture)


@pytest.mark.parametrize('kind', ['empty', 'extra', 'missing', 'invalid_json', 'naive',
                                 'duplicate', 'wrong_timestamp'])
def test_source_schema_or_clock_failure_is_not_partial_success(history: Any, kind: str) -> None:
    sources, _ = history
    row = {key: sources['one'][0][key] for key in FIELDS}
    if kind == 'extra':
        row['unexpected'] = 'private field'
    elif kind == 'missing':
        row.pop('payload')
    elif kind == 'naive':
        row['recorded_at'] = '2026-10-06T00:00:00'
    elif kind == 'wrong_timestamp':
        row['effective_at'] = 'not-a-time'
    native = json.dumps(row)
    values = () if kind == 'empty' else ('private invalid json',) if kind == 'invalid_json' else (
        (native, native) if kind == 'duplicate' else (native,))
    with pytest.raises(SourceCaptureError) as error:
        SourceCapture(values).records()
    assert 'private' not in str(error.value)


def test_reader_snapshot_contract_is_bounded_and_read_only() -> None:
    statements: list[str] = []
    class Driver:
        def execute(self, query: str, params: Sequence[object] = ()) -> Any:
            assert not params
            statements.append(query)
        def commit(self) -> None:
            pytest.fail('read helper committed')
        def rollback(self) -> None:
            pytest.fail('caller owns finally rollback')
    begin_read_snapshot(Driver())
    assert statements[:2] == ['BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY',
                              'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY']
    assert "SET LOCAL transaction_timeout='15s'" in statements
    assert "SET LOCAL statement_timeout='10s'" in statements
    assert "SET LOCAL lock_timeout='2s'" in statements


@pytest.mark.parametrize('raw', ['{"event_id":"one","event_id":"two"}',
                               '{"payload":{"x":1,"x":2}}', '{"payload":{"x":NaN}}'])
def test_duplicate_json_keys_and_nonfinite_constants_block(raw: str) -> None:
    with pytest.raises(SourceCaptureError, match='SOURCE_INVALID'):
        SourceCapture((raw,)).records()
