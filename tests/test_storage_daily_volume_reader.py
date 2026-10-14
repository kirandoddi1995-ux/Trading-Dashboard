"""Offline authenticated in-memory cuts; no SQL, accounts, host or private reads."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
import json
import math
from typing import Any

import pytest

import catalog_receipts as receipts
import cold_catalog as catalog
from overnight_storage_contracts import Candidate, CatalogCut, ContractError, digest
import storage_daily_volume_reader as reader

KNOWN = datetime(2024, 1, 15, 20, tzinfo=timezone.utc)  # Jan 16 in IST
LOWER = datetime(2024, 1, 1, tzinfo=reader.IST).astimezone(timezone.utc)
KEY = b'generated offline authentication key, not a credential'


def row(key: str, day: int, volume: str) -> reader.DailyVolumeRow:
    return reader.DailyVolumeRow(key, date(2024, 1, day), Decimal(volume))


def snapshot(rows: tuple[reader.DailyVolumeRow, ...], identity: str = 'part_a') -> reader.DailyVolumeSnapshot:
    return reader.DailyVolumeSnapshot(identity, 1, LOWER, KNOWN, KNOWN, rows)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


@dataclass
class MemoryTier:
    domain: str
    objects: dict[str, bytes]
    fault: str = ''
    reads: list[tuple[str, int]] = field(default_factory=list)

    def read(self, identity: str, limit: int) -> bytes | None:
        self.reads.append((identity, limit))
        raw = self.objects.get(identity)
        if self.fault == 'failure':
            raise OSError('private transport detail')
        if raw is None or self.fault == 'missing':
            return None
        if self.fault == 'partial':
            return raw[:-1]
        if self.fault == 'corrupt':
            return b'x' + raw[1:]
        if self.fault == 'oversize':
            return raw + b'x'
        if self.fault == 'changes_after_first_read' and len(self.reads) > 1:
            return b'changed after proof'
        return raw[:limit]


@dataclass
class Fixture:
    candidates: tuple[Candidate, ...]
    cut: CatalogCut
    pages: dict[str, bytes]
    tiers: tuple[MemoryTier, ...]
    raw: dict[str, bytes]

    def recover(self, **overrides: Any) -> reader.DailyVolumeResult:
        arguments: dict[str, Any] = {'candidates': self.candidates, 'cut': self.cut,
            'cut_id': 'whole_cut', 'known_at': KNOWN, 'as_of_at': KNOWN,
            'keys': {'fixture': KEY}, 'pages': self.pages.get, 'tiers': self.tiers,
            'instrument_keys': ['A', 'B'], 'lookback': 2}
        arguments.update(overrides)
        return reader.recover_prior_average_volumes(**arguments)


def fixture(snapshots: tuple[reader.DailyVolumeSnapshot, ...], *, declared: bool = True,
            extra_catalog: int = 0) -> Fixture:
    raw: dict[str, bytes] = {}
    candidates: list[Candidate] = []
    for item in snapshots:
        encoded = reader.encode_snapshot(item)
        candidate = Candidate(reader.SOURCE, item.snapshot, item.revision, item.lower, item.upper,
            digest(encoded), len(encoded), reader.restore_witness(encoded))
        candidates.append(candidate)
        raw[candidate.identity] = encoded
    pages: dict[str, bytes] = {}
    entries: dict[str, dict[str, object]] = {candidate.identity: candidate.metadata() for candidate in candidates}
    if declared:
        entries['daily-volume-cut:whole_cut'] = reader.cut_declaration('whole_cut', KNOWN, candidates)
    for index in range(extra_catalog):
        entries[f'other:{index}'] = {'index': index}
    patch = catalog.Catalog(catalog.EMPTY_ROOT, pages.get).patch(entries)
    pages.update(patch.pages)
    previous = receipts.genesis('generated:daily-volumes')
    signed = receipts.sign(previous, patch.root, digest(b'generated cut'), KNOWN, 'fixture', KEY)
    cut = CatalogCut(previous, signed.anchor, signed.data)
    objects = {digest(value): value for value in raw.values()}
    return Fixture(tuple(candidates), cut, pages,
                   (MemoryTier('online', dict(objects)), MemoryTier('offline', dict(objects))), raw)


@pytest.fixture
def populated() -> Fixture:
    return fixture((snapshot((row('A', 2, '10'), row('A', 5, '0'), row('A', 12, '-2'),
        row('A', 15, '20'), row('A', 16, '999'), row('B', 3, '6'), row('B', 14, '10'))),))


def test_exact_three_columns_canonical_immutable_codec() -> None:
    original = snapshot((row('A', 2, '10.000'), row('A', 8, '-2.5')))
    raw = reader.encode_snapshot(original)
    decoded = reader.decode_snapshot(raw)
    assert decoded == original
    assert reader.encode_snapshot(decoded) == raw
    assert set(json.loads(raw)['rows'][0]) == reader.ROW_FIELDS
    assert json.loads(raw)['rows'][0]['max_captured_volume'] == '10.000'
    with pytest.raises(AttributeError):
        setattr(decoded, 'rows', ())


def test_captured_dates_per_key_not_calendar_days_and_no_same_day(populated: Fixture) -> None:
    result = populated.recover()
    assert dict(result.averages) == {'A': 9.0, 'B': 8.0}
    assert result.captured_dates['A'] == (date(2024, 1, 15), date(2024, 1, 12))
    assert result.captured_dates['B'] == (date(2024, 1, 14), date(2024, 1, 3))
    assert result.as_of_date == date(2024, 1, 16)
    assert result.known_at == KNOWN
    assert len(result.rows) == 7
    assert result.authenticated_declared_cut_verified
    for flag in ('complete_source_export_verified', 'native_sql_parity_verified', 'global_wired',
                 'physical_custody_verified', 'deletion_authority', 'historical_pit_verified',
                 'exchange_final_volume_verified'):
        assert getattr(result, flag) is False
    with pytest.raises(TypeError):
        result.averages['A'] = 1  # type: ignore[index]


def test_zeros_and_negatives_count_but_only_positive_mean_returned() -> None:
    f = fixture((snapshot((row('A', 2, '-10'), row('A', 3, '10'), row('B', 2, '0'),
                          row('B', 3, '0'))),))
    result = f.recover()
    assert dict(result.averages) == {}
    assert len(result.captured_dates['A']) == 2
    f = fixture((snapshot((row('A', 2, '0'), row('A', 3, '8'))),))
    assert f.recover().averages['A'] == 4


def test_empty_snapshot_is_declared_only_and_unknown_keys_are_not_zero() -> None:
    f = fixture((snapshot(()),))
    result = f.recover(instrument_keys=['missing'])
    assert dict(result.averages) == {}
    assert result.captured_dates['missing'] == ()
    assert result.rows == () and not result.complete_source_export_verified
    assert all(len(tier.reads) == 1 for tier in f.tiers)


def test_even_empty_query_requires_all_replicas(populated: Fixture) -> None:
    populated.tiers[1].fault = 'missing'
    with pytest.raises(ContractError):
        populated.recover(instrument_keys=[])


@pytest.mark.parametrize('delta', [-1, 1, 86400, -86400])
def test_no_earlier_or_later_pit_inference(populated: Fixture, delta: int) -> None:
    with pytest.raises(ContractError, match='ASOF_NOT_EXACT'):
        populated.recover(as_of_at=KNOWN + timedelta(seconds=delta))
    assert all(not tier.reads for tier in populated.tiers)


def test_utc_ist_exact_instant_and_naive_rejected(populated: Fixture) -> None:
    result = populated.recover(as_of_at=KNOWN.astimezone(reader.IST))
    assert result.as_of_date == date(2024, 1, 16)
    with pytest.raises(ContractError, match='CLOCK_INVALID'):
        populated.recover(as_of_at=KNOWN.replace(tzinfo=None))


@pytest.mark.parametrize('value', [None, True, 1, 1.5, 'NaN', 'Infinity', '-Infinity',
                                 '1e3', ' 2', '02', '', '1E+308'])
def test_null_boolean_nonfinite_and_exotic_numeric_fail(value: object) -> None:
    raw = reader.encode_snapshot(snapshot((row('A', 2, '1'),)))
    obj = json.loads(raw)
    obj['rows'][0]['max_captured_volume'] = value
    with pytest.raises(ContractError, match='NUMERIC_INVALID'):
        reader.decode_snapshot(canonical(obj))


def test_two_finite_huge_volumes_are_classified_before_aggregate() -> None:
    with pytest.raises(ContractError, match='NUMERIC_INVALID'):
        reader.encode_snapshot(snapshot((row('A', 2, '1e308'), row('A', 3, '1e308'))))


def test_aggregate_overflow_is_contract_failure(populated: Fixture, monkeypatch: pytest.MonkeyPatch) -> None:
    def overflow(values: object) -> float:
        raise OverflowError('not exposed')
    monkeypatch.setattr(math, 'fsum', overflow)
    with pytest.raises(ContractError, match='NONFINITE_AVERAGE'):
        populated.recover()


@pytest.mark.parametrize('damage', ['missing', 'extra', 'source', 'format', 'revision_bool',
    'revision_zero', 'date', 'future', 'earlier', 'noncanonical', 'row_extra', 'row_missing',
    'order', 'known_before_upper', 'utc_not_canonical'])
def test_schema_time_and_source_boundaries(damage: str) -> None:
    raw = reader.encode_snapshot(snapshot((row('A', 2, '1'), row('A', 3, '2'))))
    obj = json.loads(raw)
    if damage == 'missing':
        del obj['known_at']
    elif damage == 'extra':
        obj['availability'] = 'invented'
    elif damage in ('source', 'format'):
        obj[damage] = 'other'
    elif damage == 'revision_bool':
        obj['revision'] = True
    elif damage == 'revision_zero':
        obj['revision'] = 0
    elif damage == 'date':
        obj['rows'][0]['trade_date'] = '2024-1-2'
    elif damage == 'future':
        obj['rows'][1]['trade_date'] = '2024-01-17'
    elif damage == 'earlier':
        obj['rows'][0]['trade_date'] = '2023-12-31'
    elif damage == 'row_extra':
        obj['rows'][0]['available_at'] = 'invented'
    elif damage == 'row_missing':
        del obj['rows'][0]['trade_date']
    elif damage == 'order':
        obj['rows'].reverse()
    elif damage == 'known_before_upper':
        obj['known_at'] = '2024-01-01T00:00:00+00:00'
    elif damage == 'utc_not_canonical':
        obj['known_at'] = KNOWN.astimezone(reader.IST).isoformat()
    with pytest.raises(ContractError):
        reader.decode_snapshot(canonical(obj) + (b' ' if damage == 'noncanonical' else b''))


@pytest.mark.parametrize('raw', [b'', b'{', b'[]', b'null', b'{"a":1,"a":2}',
    b'\xff', b'[' * 1500 + b']' * 1500, b'x' * (reader.MAX_BYTES + 1)],
    ids=['empty', 'truncated', 'array', 'null', 'duplicate_key', 'utf8', 'deep', 'oversize'])
def test_malformed_and_byte_bounds(raw: bytes) -> None:
    with pytest.raises(ContractError):
        reader.decode_snapshot(raw)


@pytest.mark.parametrize('conflicting', [False, True])
def test_duplicate_rows_blocked_within_and_across_objects(conflicting: bool) -> None:
    first = row('A', 2, '1')
    second = row('A', 2, '2' if conflicting else '1')
    with pytest.raises(ContractError, match='DUPLICATE'):
        reader.encode_snapshot(snapshot((first, second)))
    f = fixture((snapshot((first,)), snapshot((second,), 'part_b')))
    with pytest.raises(ContractError, match='DUPLICATE'):
        f.recover()


@pytest.mark.parametrize('fault', ['failure', 'missing', 'partial', 'corrupt', 'oversize'])
def test_each_tier_must_pass_even_after_first_good_copy(populated: Fixture, fault: str) -> None:
    populated.tiers[1].fault = fault
    with pytest.raises(ContractError) as error:
        populated.recover()
    assert 'private' not in str(error.value)
    assert len(populated.tiers[0].reads) == 1
    assert len(populated.tiers[1].reads) == 1


def test_no_second_tier_read_after_proof(populated: Fixture) -> None:
    for tier in populated.tiers:
        tier.fault = 'changes_after_first_read'
    result = populated.recover(hot=populated.raw)
    assert result.averages['A'] == 9
    for tier in populated.tiers:
        assert tier.reads == [(populated.candidates[0].sha256, populated.candidates[0].size + 1)]


def test_hot_cold_exact_parity_and_whole_hot_cut_required(populated: Fixture) -> None:
    with pytest.raises(ContractError, match='HOT_WHOLE_CUT'):
        populated.recover(hot={})
    altered = dict(populated.raw)
    altered[populated.candidates[0].identity] += b' '
    with pytest.raises(ContractError, match='PARITY'):
        populated.recover(hot=altered)


def test_whole_authenticated_declaration_not_subset() -> None:
    f = fixture((snapshot((row('A', 2, '1'),)), snapshot((row('B', 3, '2'),), 'part_b')))
    with pytest.raises(ContractError, match='WHOLE_CUT_MISSING'):
        f.recover(candidates=f.candidates[:1])
    assert not f.tiers[0].reads
    result = f.recover()
    assert len(result.proofs) == 2 and len(result.rows) == 2
    no_declaration = fixture((snapshot(()),), declared=False)
    with pytest.raises(ContractError, match='WHOLE_CUT_MISSING'):
        no_declaration.recover()


def test_missing_catalog_branch_anywhere_blocks_full_cut() -> None:
    f = fixture((snapshot(()),), extra_catalog=150)
    leaves = [key for key, raw in f.pages.items() if json.loads(raw)['kind'] == 'leaf']
    assert len(leaves) > 1
    del f.pages[leaves[-1]]
    with pytest.raises(ContractError, match='FULL_CUT_FAILED'):
        f.recover()


def test_keys_receipt_and_cut_provenance(populated: Fixture) -> None:
    for keys in ({}, {'fixture': b'x'}, {'fixture': b'x' * 64}):
        with pytest.raises(ContractError):
            populated.recover(keys=keys)
    with pytest.raises(ContractError):
        populated.recover(cut=replace(populated.cut, signed=populated.cut.signed + b' '))
    with pytest.raises(ContractError, match='WHOLE_CUT_MISSING'):
        populated.recover(known_at=KNOWN + timedelta(seconds=1), as_of_at=KNOWN + timedelta(seconds=1))


def test_candidate_revision_mismatch_and_multiple_revisions_blocked(populated: Fixture) -> None:
    bad = replace(populated.candidates[0], revision=2)
    with pytest.raises(ContractError):
        populated.recover(candidates=(bad,))
    with pytest.raises(ContractError, match='SOURCE_OR_DUPLICATE'):
        reader.cut_declaration('whole_cut', KNOWN, (populated.candidates[0], bad))


@pytest.mark.parametrize('lookback', [0, -1, True, 401])
def test_query_bounds(populated: Fixture, lookback: int) -> None:
    with pytest.raises(ContractError, match='LOOKBACK_BOUND'):
        populated.recover(lookback=lookback)


def test_row_key_and_object_bounds() -> None:
    with pytest.raises(ContractError, match='ROWS_BOUND'):
        reader.encode_snapshot(snapshot(tuple(row('A', 2, '1') for _ in range(401))))
    many = tuple(row(f'k{i:03}', 2, '1') for i in range(129))
    with pytest.raises(ContractError, match='KEYS_BOUND'):
        reader.encode_snapshot(snapshot(many))
    f = fixture((snapshot(()),))
    with pytest.raises(ContractError, match='OBJECTS_BOUND'):
        f.recover(candidates=f.candidates * 17)
    with pytest.raises(ContractError, match='QUERY_KEYS_BOUND'):
        f.recover(instrument_keys=['A'] * 129)


def test_duplicate_tier_domain_rejected(populated: Fixture) -> None:
    populated.tiers[1].domain = 'online'
    with pytest.raises(ContractError, match='DOMAIN_DUPLICATE'):
        populated.recover()


def test_catalog_callback_exception_is_redacted_before_tier_reads(populated: Fixture) -> None:
    def failed(page_id: str) -> bytes | None:
        raise ValueError('private endpoint')
    with pytest.raises(ContractError) as error:
        populated.recover(pages=failed)
    assert str(error.value) == 'DAILY_VOLUME_CATALOG_GET_UNAVAILABLE'
    assert 'private endpoint' not in str(error.value)
    assert error.value.__suppress_context__
    assert all(not tier.reads for tier in populated.tiers)


def test_snapshot_declared_known_at_mismatch_blocks_even_authenticated_bytes() -> None:
    wrong_cut = replace(snapshot((row('A', 2, '1'),)), known_at=KNOWN + timedelta(seconds=1))
    f = fixture((wrong_cut,))
    with pytest.raises(ContractError, match='PROVENANCE_CUT_MISMATCH'):
        f.recover()


def test_missing_replica_of_later_object_is_not_shortened_history() -> None:
    f = fixture((snapshot((row('A', 2, '10'),)), snapshot((row('A', 12, '20'),), 'part_b')))
    del f.tiers[1].objects[f.candidates[1].sha256]
    with pytest.raises(ContractError, match='MISSING_PARTIAL'):
        f.recover()
    assert len(f.tiers[0].reads) == 2 and len(f.tiers[1].reads) == 2


def test_whole_cut_row_bound_never_returns_truncated_prefix() -> None:
    rows = tuple(row(f'k{i:03}', day, '1') for i in range(100) for day in range(1, 17))
    parts = tuple(snapshot(rows[offset:offset + 400], f'part_{offset}')
                  for offset in range(0, len(rows), 400))
    f = fixture(parts)
    assert len(f.recover(instrument_keys=[]).rows) == reader.MAX_TOTAL_ROWS
    excessive = fixture((*parts, snapshot((row('k100', 2, '1'),), 'part_extra')))
    with pytest.raises(ContractError, match='WHOLE_CUT_BOUND'):
        excessive.recover(instrument_keys=[])


def test_source_object_byte_bound_precedes_row_interpretation() -> None:
    oversized = snapshot(tuple(row('k' * 160, 2, '1000000000000000000') for _ in range(400)))
    with pytest.raises(ContractError, match='BYTES_BOUND'):
        reader.encode_snapshot(oversized)


@pytest.mark.parametrize('precision', [1, 9, 28, 50, 80])
@pytest.mark.parametrize('sign', ['', '-'])
def test_decimal_cap_is_exact_and_independent_of_context(precision: int, sign: str) -> None:
    with localcontext() as context:
        context.prec = precision
        for amount in ('1000000000000000000', '999999999999999999.99999999999'):
            value = sign + amount
            raw = reader.encode_snapshot(snapshot((row('A', 2, value),)))
            decoded = reader.decode_snapshot(raw)
            assert decoded.rows[0].max_captured_volume == Decimal(value)
            assert str(decoded.rows[0].max_captured_volume) == value
        for amount in ('1000000000000000000.00000000001', '1000000000000000001'):
            value = sign + amount
            with pytest.raises(ContractError, match='NUMERIC_INVALID'):
                reader.encode_snapshot(snapshot((row('A', 2, value),)))
            valid = json.loads(reader.encode_snapshot(snapshot((row('A', 2, '1'),))))
            valid['rows'][0]['max_captured_volume'] = value
            with pytest.raises(ContractError, match='NUMERIC_INVALID'):
                reader.decode_snapshot(canonical(valid))


@pytest.mark.parametrize('error_type', [ContractError, ValueError])
def test_later_replica_callback_errors_are_redacted(populated: Fixture,
                                                  error_type: type[Exception]) -> None:
    class FailingTier:
        domain = 'failing'
        reads = 0

        def read(self, sha256: str, limit: int) -> bytes | None:
            self.reads += 1
            raise error_type('private transport text')

    failing = FailingTier()
    with pytest.raises(ContractError) as error:
        populated.recover(tiers=(populated.tiers[0], failing))
    assert str(error.value) == 'DAILY_VOLUME_REPLICA_GET_UNAVAILABLE'
    assert 'private transport text' not in str(error.value)
    assert error.value.__suppress_context__
    assert len(populated.tiers[0].reads) == 1
    assert failing.reads == 1


@pytest.mark.parametrize('error_type', [ContractError, ValueError])
def test_replica_domain_callback_errors_are_redacted_without_reads(populated: Fixture,
                                                                  error_type: type[Exception]) -> None:
    class FailingIdentityTier:
        reads = 0

        @property
        def domain(self) -> str:
            raise error_type('private identity text')

        def read(self, sha256: str, limit: int) -> bytes | None:
            self.reads += 1
            raise AssertionError('read after failed identity')

    failing = FailingIdentityTier()
    with pytest.raises(ContractError) as error:
        populated.recover(tiers=(failing, populated.tiers[1]))
    assert str(error.value) == 'DAILY_VOLUME_REPLICA_IDENTITY_UNAVAILABLE'
    assert 'private identity text' not in str(error.value)
    assert error.value.__suppress_context__
    assert failing.reads == 0
    assert all(not tier.reads for tier in populated.tiers)
