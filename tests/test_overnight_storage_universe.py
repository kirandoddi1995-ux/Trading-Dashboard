"""Synthetic exact-schema universe projection; no private data or DB IO."""
from dataclasses import replace
from typing import Any

import pytest

import overnight_storage_universe as universe


def row(*, version: bool = True, snapshot: str = 'a' * 64,
        key: str = 'NSE_EQ|SYNTHETIC', payload: dict[str, Any] | None = None) -> bytes:
    data: dict[str, Any] = {name: None for name in universe.COMMON}
    data.update(instrument_key=key, trading_symbol='SYNTHETIC', source='SYNTHETIC_BOD',
                observed_at='2022-01-03T09:00:00+05:30', raw=payload or {'name': 'परीक्षण', 'value': 'x' * 800})
    data['snapshot_id' if version else 'snapshot_date'] = snapshot if version else '2022-01-03'
    return universe.canonical(data)


def shadow() -> universe.UniverseShadow:
    return universe.build_shadow([row(), row(snapshot='b' * 64)],
        table='quant_app.universe_membership_versions', generation_sha256='c' * 64)


def test_payload_shared_but_snapshot_identity_and_originals_preserved() -> None:
    result = shadow()
    assert len(result.members) == 2 and len(result.objects) == 1
    assert universe.restore_shadow(result) == (row(), row(snapshot='b' * 64))
    assert result.shadow_wire_bytes < result.original_wire_bytes
    assert not result.database_reclaim_verified and not result.custody_verified and not result.deletion_authority


def test_canonical_membership_ist_unicode_round_trip() -> None:
    original = row(version=False)
    result = universe.build_shadow([original], table='quant_app.universe_membership', generation_sha256='c' * 64)
    assert universe.restore_shadow(result) == (original,)


def test_different_raw_payloads_never_merged() -> None:
    first, second = row(), row(snapshot='b' * 64, payload={'price': 1})
    result = universe.build_shadow([first, second], table='quant_app.universe_membership_versions', generation_sha256='c' * 64)
    assert len(result.objects) == 2
    assert set(universe.restore_shadow(result)) == {first, second}


@pytest.mark.parametrize('rows', [[], [row(), row()], [b'{}'], [bytearray(row())], [row() + b' ']])
def test_invalid_or_duplicate_rows_fail_closed(rows: Any) -> None:
    with pytest.raises(universe.UniverseError):
        universe.build_shadow(rows, table='quant_app.universe_membership_versions', generation_sha256='c' * 64)


@pytest.mark.parametrize('field,value', [('observed_at', '2022-01-03T09:00:00'),
    ('snapshot_id', 'wrong'), ('raw', None), ('raw', []), ('instrument_key', ''),
    ('source', True), ('unknown', 'extra')])
def test_schema_failures_redacted(field: str, value: Any) -> None:
    import json
    data = json.loads(row())
    data[field] = value
    with pytest.raises(universe.UniverseError, match='UNIVERSE_ROW_INVALID'):
        universe.build_shadow([universe.canonical(data)],
            table='quant_app.universe_membership_versions', generation_sha256='c' * 64)


def test_duplicate_json_fields_rejected() -> None:
    original = row().replace(b'"source":"SYNTHETIC_BOD"', b'"source":"bad","source":"SYNTHETIC_BOD"')
    with pytest.raises(universe.UniverseError):
        universe.build_shadow([original], table='quant_app.universe_membership_versions', generation_sha256='c' * 64)


@pytest.mark.parametrize('field,value', [('witness_sha256', 'd' * 64),
    ('generation_sha256', 'wrong'), ('original_wire_bytes', 1), ('shadow_wire_bytes', 1),
    ('deletion_authority', True), ('custody_verified', True), ('database_reclaim_verified', True)])
def test_forged_claim_or_binding_blocked(field: str, value: Any) -> None:
    with pytest.raises(universe.UniverseError, match='UNIVERSE_SHADOW_RESTORE_BLOCKED'):
        universe.restore_shadow(replace(shadow(), **{field: value}))


def test_missing_corrupt_duplicate_and_unreferenced_objects_blocked() -> None:
    result = shadow()
    for objects in ((), ((result.objects[0][0], b'{}'),), result.objects * 2,
                    result.objects + (('d' * 64, b'{}'),)):
        with pytest.raises(universe.UniverseError):
            universe.restore_shadow(replace(result, objects=objects))


def test_unknown_fields_cannot_be_overwritten_by_payload() -> None:
    original = row(payload={'source': 'RAW_FIELD', 'snapshot_id': 'RAW_ONLY'})
    result = universe.build_shadow([original], table='quant_app.universe_membership_versions', generation_sha256='c' * 64)
    assert universe.restore_shadow(result) == (original,)


def test_input_and_object_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(universe, 'MAX_BYTES', 1)
    with pytest.raises(universe.UniverseError, match='UNIVERSE_INPUT_LIMIT'):
        shadow()
    monkeypatch.setattr(universe, 'MAX_BYTES', 64 * 1024 * 1024)
    monkeypatch.setattr(universe, 'MAX_RAW', 1)
    with pytest.raises(universe.UniverseError, match='UNIVERSE_ROW_INVALID'):
        shadow()


def test_order_determinism_and_old_shadow_unchanged() -> None:
    old = shadow()
    reversed_shadow = universe.build_shadow([row(snapshot='b' * 64), row()],
        table='quant_app.universe_membership_versions', generation_sha256='c' * 64)
    assert old == reversed_shadow
    assert universe.restore_shadow(old) == (row(), row(snapshot='b' * 64))
