"""No network in preview/refusal, mandatory exact fixture identity."""
from __future__ import annotations

import pytest

import overnight_storage_native_acceptance as acceptance
import storage_native_conformance as native
from overnight_storage_contracts import ContractError


def test_preview_and_refusal_never_connect(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        pytest.fail('preview attempted connection')
    monkeypatch.setattr(native, 'connect_fixture', forbidden)
    assert acceptance.main([]) == 0
    assert acceptance.main(['--execute']) == 2
    assert acceptance.main(['--execute', '--confirm-disposable', '--port', '55432']) == 2
    assert 'PREVIEW' in capsys.readouterr().out
    with pytest.raises(ContractError, match='EXACT_LOOPBACK'):
        with acceptance.disposable(55432):
            pytest.fail('unexpected connection')
