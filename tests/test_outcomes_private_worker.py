"""Synthetic reconstruction only; no real outcomes or archive data."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import errno
import stat
from types import SimpleNamespace
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


@pytest.mark.parametrize('readonly,denial,changed,accepted', [
    (True, errno.EROFS, False, True), (True, errno.EACCES, False, True),
    (False, errno.EACCES, False, False), (False, errno.EROFS, False, False),
    (True, errno.EPERM, False, False), (True, errno.ENOENT, False, False),
    (True, None, False, False), (True, errno.EACCES, True, False)])
def test_readonly_probe_needs_independent_mount_proof(monkeypatch: pytest.MonkeyPatch,
        readonly: bool, denial: int | None, changed: bool, accepted: bool) -> None:
    def info(ino: int = 7) -> Any:
        return SimpleNamespace(st_mode=stat.S_IFREG, st_dev=3, st_ino=ino, st_size=20, st_mtime_ns=1, st_ctime_ns=1)
    opened: list[int] = []
    def open_file(path: str, flags: int, mode: int = 0) -> int:
        opened.append(flags)
        if flags & w.os.O_WRONLY:
            if denial is not None:
                raise OSError(denial, 'SYNTHETIC_PRIVATE_ERROR_NOT_FOR_OUTPUT')
            return 43
        return 42
    with monkeypatch.context() as patch:
        patch.setattr(w.os, 'open', open_file)
        patch.setattr(w.os, 'close', lambda _: None)
        patch.setattr(w.os, 'fstat', lambda _: info())
        patch.setattr(w.os, 'stat', lambda *a, **kw: info(8 if changed else 7))
        patch.setattr(w, 'mount_view', lambda *a: (True, readonly))
        patch.setattr(w, '_descriptor_mount_id', lambda _: '42')
        detail = w.readonly_probe('/inputs/catalog.json')
    assert w.readonly_detail_passes(detail) is accepted
    assert set(detail) == w.PROBE_FIELDS
    assert not opened[1] & (w.os.O_TRUNC | w.os.O_CREAT)
    assert 'SYNTHETIC_PRIVATE_ERROR' not in str(detail)


@pytest.mark.parametrize('change', ['', 'rw-options', 'rw-flag', 'wrong-target', 'duplicate', 'missing-id', 'wrong-id'])
def test_descriptor_mount_id_and_flags_are_both_required(monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    line = '42 1 0:10 / /inputs/catalog.json ro,nosuid - ext4 SYNTHETIC rw\n'
    if change == 'rw-options':
        line = line.replace('ro,nosuid', 'rw,nosuid')
    if change == 'wrong-target':
        line = line.replace('/inputs/catalog.json', '/another-file')
    if change == 'duplicate':
        line += line
    if change == 'wrong-id':
        line = line.replace('42 1 ', '99 1 ')
    monkeypatch.setattr(w, '_bounded_proc', lambda path, limit: ('other: 42\n' if change == 'missing-id' else 'mnt_id:\t42\n')
        if 'fdinfo' in path else line)
    monkeypatch.setattr(w.os, 'fstatvfs', lambda _: SimpleNamespace(f_flag=0 if change == 'rw-flag' else 1), raising=False)
    monkeypatch.setattr(w.os, 'ST_RDONLY', 1, raising=False)
    bound, readonly = w.mount_view(42, '/inputs/catalog.json')
    assert (bound and readonly) is (not change)


def test_private_readonly_admission_never_performs_a_write_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    info = SimpleNamespace(st_mode=stat.S_IFREG, st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4, st_ctime_ns=5)
    with monkeypatch.context() as patch:
        patch.setattr(w.os, 'fstat', lambda _: info)
        patch.setattr(w.os, 'stat', lambda *a, **kw: info)
        patch.setattr(w, 'mount_view', lambda *a: (True, False))
        patch.setattr(w.os, 'open', lambda *a, **kw: pytest.fail('Private mount admission attempted to open/write'))
        with pytest.raises(ValueError, match='PRIVATE_INPUT_MOUNT_NOT_READONLY'):
            w.require_private_readonly(42, '/inputs/catalog.json')


@pytest.mark.parametrize('change', ['st_size', 'st_mtime_ns', 'st_ctime_ns', 'mount_id'])
def test_private_read_retains_pre_read_identity(monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    info = SimpleNamespace(st_mode=stat.S_IFREG, st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4, st_ctime_ns=5)
    mount_id = '42'
    with monkeypatch.context() as patch:
        patch.setattr(w.os, 'fstat', lambda _: info)
        patch.setattr(w.os, 'stat', lambda *a, **kw: info)
        patch.setattr(w, 'mount_view', lambda *a: (True, True))
        patch.setattr(w, '_descriptor_mount_id', lambda _: mount_id)
        before = w.require_private_readonly(42, '/inputs/catalog.json')
        if change == 'mount_id':
            mount_id = '43'
        else:
            setattr(info, change, getattr(info, change) + 1)
        with pytest.raises(ValueError, match='PRIVATE_INPUT_MOUNT_NOT_READONLY'):
            w.require_private_readonly(42, '/inputs/catalog.json', before)


def test_root_readonly_admission_is_required_before_codec_or_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    with monkeypatch.context() as patch:
        patch.setattr(w, 'kernel_checks', lambda: dict.fromkeys(w.KERNEL_FIELDS, True))
        patch.setattr(w.os, 'open', lambda path, flags: calls.append(flags) or 42)
        patch.setattr(w.os, 'close', lambda _: None)
        patch.setattr(w.os, 'fstat', lambda _: SimpleNamespace(st_mode=stat.S_IFDIR))
        patch.setattr(w, 'mount_view', lambda *a: (True, False))
        with pytest.raises(ValueError, match='KERNEL_ROOT_READONLY_UNVERIFIED'):
            w.require_kernel()
    assert calls and not any(flags & w.os.O_WRONLY for flags in calls)
