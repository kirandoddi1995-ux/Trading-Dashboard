"""Real synthetic six-table copies/restores; never private state or credentials."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

import pytest

import catalog_receipts as receipts
import recovery_custody_rehearsal as custody
import recovery_export as export
import recovery_replica_audit as audit
import recovery_materialization as restore
from test_recovery_six_export import contract, initialize, prepare, source as _source_fixture
from test_recovery_export import AUTH
from test_local_state_recovery import KEY, KEY_ID

source = _source_fixture
NOW = datetime(2026, 10, 12, 20, tzinfo=timezone.utc)


def inputs(source: Path, parent: Path) -> dict[str, Any]:
    initialize(source)
    generation = prepare(source, parent / 'generation')
    for name in ('drive', 'external_disk'):
        shutil.copytree(generation.directory, parent / name)
    return dict(source=generation,
        copies=tuple(audit.ExtractedCopy(n, parent / n) for n in ('drive', 'external_disk')),
        targets={n: parent / ('restore_' + n) for n in ('drive', 'external_disk')},
        checkpoint=generation.signed.checkpoint, contract=contract(),
        keys={'auth': AUTH}, original_keys={KEY_ID: KEY}, spool_parent=parent,
        previous_report=receipts.genesis(custody.SCOPE), at=NOW, key_id='auth', key=AUTH)


def verified(result: custody.Rehearsal, args: dict[str, Any], **changes: Any) -> bytes:
    options = dict(trusted_report=result.signed.anchor, previous_report=args['previous_report'],
        checkpoint=args['checkpoint'], keyring=args['keys'],
        trusted_bundle_sha256=hashlib.sha256(args['source'].signed.data).hexdigest())
    options.update(changes)
    return custody.verify_report(result, **options)


def test_both_restores_authenticated_but_not_independent_custody(source: Path, tmp_path: Path) -> None:
    args = inputs(source, tmp_path)
    before = source.read_bytes()
    result = custody.rehearse(**args)
    report = json.loads(verified(result, args))
    assert report['restores_verified'] == 2
    assert report['six_table_image_verified'] is True
    for name in ('encryption_verified', 'physical_independence_verified',
                 'trusted_checkpoint_durability_verified', 'application_recovery_verified',
                 'hot_deletion_authority', 'approval_authority'):
        assert report[name] is False
    for target in args['targets'].values():
        assert (target / export.IMAGE).read_bytes() == (args['source'].directory / export.IMAGE).read_bytes()
    assert source.read_bytes() == before
    assert str(tmp_path) not in result.report.decode()
    assert 'secret' not in repr(result)


def test_ist_report_time_normalized(source: Path, tmp_path: Path) -> None:
    args = inputs(source, tmp_path)
    args['at'] = NOW.astimezone(timezone(timedelta(hours=5, minutes=30)))
    result = custody.rehearse(**args)
    assert json.loads(verified(result, args))['at'] == NOW.isoformat()


@pytest.mark.parametrize('damage', ['missing', 'image', 'sixth', 'extra', 'key', 'original_key', 'pin'])
def test_bad_replica_blocks_before_any_restore(source: Path, tmp_path: Path, damage: str) -> None:
    args = inputs(source, tmp_path)
    replica = tmp_path / 'external_disk'
    if damage == 'missing':
        (replica / export.IMAGE).unlink()
    elif damage in ('image', 'sixth'):
        (replica / (export.IMAGE if damage == 'image' else export.SIX_WITNESS)).write_bytes(b'broken')
    elif damage == 'extra':
        (replica / 'unexpected').write_bytes(b'x')
    elif damage == 'pin':
        args['checkpoint'] = replace(args['checkpoint'], current=args['checkpoint'].previous)
    else:
        args['keys' if damage == 'key' else 'original_keys'] = {}
    with pytest.raises(custody.RehearsalError):
        custody.rehearse(**args)
    assert all(not p.exists() for p in args['targets'].values())


@pytest.mark.parametrize('damage', ['same_target', 'nested_target', 'existing', 'one_copy', 'naive', 'scope', 'short_key'])
def test_preflight_no_restore_writes(source: Path, tmp_path: Path, damage: str) -> None:
    args = inputs(source, tmp_path)
    if damage == 'same_target':
        args['targets']['drive'] = args['targets']['external_disk']
    elif damage == 'nested_target':
        args['targets']['drive'] = args['copies'][0].directory / 'restore'
    elif damage == 'existing':
        args['targets']['drive'].mkdir()
    elif damage == 'one_copy':
        args['copies'] = args['copies'][:1]
    elif damage == 'naive':
        args['at'] = NOW.replace(tzinfo=None)
    elif damage == 'scope':
        args['previous_report'] = receipts.genesis('wrong:scope')
    else:
        args['key'] = b'short'
    with pytest.raises(custody.RehearsalError):
        custody.rehearse(**args)
    assert not args['targets']['external_disk'].exists()


def test_partial_restore_error_is_classified_and_retained(source: Path, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    args = inputs(source, tmp_path)
    real = restore.materialize
    def fail(generation: export.PreparedGeneration, target: Path, **options: Any) -> export.PreparedGeneration:
        if target.name.endswith('external_disk'):
            target.mkdir()
            (target / 'partial').write_bytes(b'x')
            raise RuntimeError('secret url and private driver text')
        return real(generation, target, **options)
    monkeypatch.setattr(restore, 'materialize', fail)
    with pytest.raises(custody.RehearsalError, match='RESTORE_EXTERNAL_DISK_BLOCKED') as error:
        custody.rehearse(**args)
    assert 'secret' not in str(error.value)
    assert (args['targets']['drive'] / export.IMAGE).exists()
    assert (args['targets']['external_disk'] / 'partial').exists()


@pytest.mark.parametrize('damage', ['report', 'signature', 'pin', 'generation', 'key', 'bundle_hash'])
def test_signed_report_requires_independent_pins(source: Path, tmp_path: Path, damage: str) -> None:
    args = inputs(source, tmp_path)
    result = custody.rehearse(**args)
    changes: dict[str, Any] = {}
    if damage == 'report':
        result = replace(result, report=result.report + b' ')
    elif damage == 'signature':
        result = replace(result, signed=replace(result.signed, data=b'{}'))
    elif damage == 'pin':
        changes['trusted_report'] = args['previous_report']
    elif damage == 'generation':
        changes['checkpoint'] = replace(args['checkpoint'], current=args['checkpoint'].previous)
    elif damage == 'key':
        changes['keyring'] = {}
    else:
        changes['trusted_bundle_sha256'] = 'f' * 64
    with pytest.raises(custody.RehearsalError):
        verified(result, args, **changes)
