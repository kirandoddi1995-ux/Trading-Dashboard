"""Synthetic restart admission, not real state or hosted custody."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import recovery_bundle as bundle
import recovery_export as export
import recovery_proposal as proposal
from test_recovery_export import contract, prepare, commit, AUTH
from test_local_state_recovery import source as _source_fixture, KEY, KEY_ID

source = _source_fixture


def reload(directory: Path, custody: Path, parent: Path, **changes: Any) -> proposal.ReloadedProposal:
    args: dict[str, Any] = dict(trusted_previous=bundle.genesis(contract()),
        contract=contract(), keys={'auth': AUTH}, original_keys={KEY_ID: KEY}, spool_parent=parent)
    args.update(changes)
    return proposal.reload(directory, custody, **args)


def test_restart_before_and_after_commit(source: Path, tmp_path: Path) -> None:
    generated = prepare(source, tmp_path / 'generation')
    custody = tmp_path / 'custody.sqlite'
    export.create_custody(custody, contract=contract())
    recovered = reload(generated.directory, custody, tmp_path)
    assert recovered.status == 'PROPOSAL_READY_FOR_LOCAL_CAS'
    assert str(generated.directory) not in repr(recovered)
    result = proposal.resume(custody, recovered, contract=contract(), keys={'auth': AUTH},
                             original_keys={KEY_ID: KEY}, spool_parent=tmp_path)
    assert result['approval_authority'] is False
    del generated, recovered
    recovered = reload(tmp_path / 'generation', custody, tmp_path)
    assert recovered.status == 'PROPOSAL_ALREADY_LOCALLY_COMMITTED'
    assert proposal.resume(custody, recovered, contract=contract(), keys={'auth': AUTH},
        original_keys={KEY_ID: KEY}, spool_parent=tmp_path)['status'] == 'CUSTODY_EXACT_RETRY'


@pytest.mark.parametrize('damage', ['partial', 'manifest', 'image', 'custody', 'key', 'original_key', 'predecessor', 'extra'])
def test_invalid_restart_keeps_head_and_files(source: Path, tmp_path: Path, damage: str) -> None:
    generated = prepare(source, tmp_path / 'generation')
    custody = tmp_path / 'custody.sqlite'
    export.create_custody(custody, contract=contract())
    changes: dict[str, Any] = {}
    if damage == 'partial':
        (generated.directory / export.MANIFEST).unlink()
    elif damage == 'manifest':
        (generated.directory / export.MANIFEST).write_bytes(b'{}')
    elif damage == 'image':
        (generated.directory / export.IMAGE).write_bytes(b'broken synthetic image')
    elif damage == 'custody':
        custody.unlink()
    elif damage == 'key':
        changes['keys'] = {}
    elif damage == 'original_key':
        changes['original_keys'] = {}
    elif damage == 'predecessor':
        changes['trusted_previous'] = generated.signed.checkpoint.current
    else:
        (generated.directory / 'unexpected').write_bytes(b'x')
    with pytest.raises(proposal.ProposalError):
        reload(generated.directory, custody, tmp_path, **changes)
    assert generated.directory.is_dir()
    if custody.exists():
        assert export.read_head(custody, contract=contract()) == bundle.genesis(contract())


def test_race_after_reload_is_rechecked(source: Path, tmp_path: Path) -> None:
    custody = tmp_path / 'custody.sqlite'
    export.create_custody(custody, contract=contract())
    first = prepare(source, tmp_path / 'first')
    recovered = reload(first.directory, custody, tmp_path)
    competing = prepare(source, tmp_path / 'competing',
        bundle_id='00000000-0000-4000-8000-000000000003')
    commit(custody, competing, tmp_path)
    with pytest.raises(export.ExportError, match='STALE_PREDECESSOR'):
        proposal.resume(custody, recovered, contract=contract(), keys={'auth': AUTH},
                        original_keys={KEY_ID: KEY}, spool_parent=tmp_path)
    with pytest.raises(proposal.ProposalError, match='STALE_OR_CONFLICTING'):
        reload(first.directory, custody, tmp_path)


def test_admission_is_not_committed_restore_authority(source: Path, tmp_path: Path) -> None:
    generated = prepare(source, tmp_path / 'generation')
    signed = bundle.admit_proposal(generated.signed.data, previous=bundle.genesis(contract()),
                                  contract=contract(), keyring={'auth': AUTH})
    assert signed == generated.signed
    with pytest.raises(bundle.BundleError):
        bundle.admit_proposal(signed.data, previous=signed.checkpoint.current,
                              contract=contract(), keyring={'auth': AUTH})


def test_second_generation_needs_retained_predecessor(source: Path, tmp_path: Path) -> None:
    custody = tmp_path / 'custody.sqlite'
    export.create_custody(custody, contract=contract())
    first = prepare(source, tmp_path / 'first')
    commit(custody, first, tmp_path)
    second = prepare(source, tmp_path / 'second', previous=first.signed.checkpoint.current,
        bundle_id='00000000-0000-4000-8000-000000000003')
    with pytest.raises(proposal.ProposalError):
        reload(second.directory, custody, tmp_path)
    assert reload(second.directory, custody, tmp_path,
        trusted_previous=first.signed.checkpoint.current).status == 'PROPOSAL_READY_FOR_LOCAL_CAS'
