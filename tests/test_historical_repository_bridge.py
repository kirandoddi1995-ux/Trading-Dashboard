"""Staged public-main repository bridge, never the unrelated dirty root draft."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from ledger_historical_views import LedgerHistoricalViews

pytest_plugins = ('test_ledger_historical_views',)
ROOT = Path(__file__).resolve().parents[1]


def reviewed(name: str) -> ModuleType:
    staged = ROOT / 'staged_historical_repository' / (name + '.py')
    source = staged if staged.is_file() else ROOT / (name + '.py')
    spec = importlib.util.spec_from_file_location('reviewed_' + name, source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repository(module: Any, view: LedgerHistoricalViews) -> Any:
    result = module.ProductionRepository('postgresql://synthetic/db', schema_mode='validate',
                                        enforce_restricted_role=True, historical_views=view)
    result._schema_ready = True  # Routing test only; native role/schema proof is separate.
    return result


def test_all_historical_read_methods_delegate_without_a_hot_connection(make: Any, monkeypatch: Any) -> None:
    view, source = make(outcomes=2)
    module = reviewed('production_repository')
    repo = repository(module, view)
    monkeypatch.setattr(repo, 'connect', lambda: pytest.fail('hot-only fallback forbidden'))
    assert len(repo.events('one')) == 3
    assert repo.verify_evidence_ledger_continuity()['events'] == 3
    readiness = repo.decision_outcome_records()
    assert len(readiness) == 1 and readiness[0]['outcome'] == 'TARGET'
    frame = repo.matured_decision_dataset(strategy_id='frozen', target_version='synthetic-v1', horizon_sessions=1)
    assert frame['target_before_stop'].tolist() == [1, 0]
    assert str(frame['target_before_stop'].dtype) == 'Int8'
    assert frame.attrs['production_evidence'] is False and frame.attrs['approval_authority'] is False
    assert source.calls == 4  # one verified cut per public read, no second dataset audit


def test_unknown_nullable_label_and_source_failure_never_become_hot_only_success(make: Any, monkeypatch: Any) -> None:
    import pandas as pd  # type: ignore[import-untyped]
    view, source = make(outcome_change={'outcome': 'UNKNOWN'})
    module = reviewed('production_repository')
    repo = repository(module, view)
    monkeypatch.setattr(repo, 'connect', lambda: pytest.fail('hot-only fallback forbidden'))
    frame = repo.matured_decision_dataset(strategy_id='frozen', target_version='synthetic-v1', horizon_sessions=1)
    assert pd.isna(frame['target_before_stop'].iloc[0])
    assert frame.attrs['unknown_target_stop_labels'] == 1
    source.fail = True
    with pytest.raises(ValueError):
        repo.events('one')


@pytest.mark.parametrize('schema,role', [('migrate', True), ('validate', False), ('validate', 'true')])
def test_historical_mode_requires_validate_and_exact_restricted_flag(schema: str, role: Any, make: Any) -> None:
    view, _ = make()
    module = reviewed('production_repository')
    with pytest.raises(module.RepositoryUnavailable, match='EXPLICIT_READ_ONLY_CONFIG_REQUIRED'):
        module.ProductionRepository('postgresql://synthetic/db', schema_mode=schema,
                                    enforce_restricted_role=role, historical_views=view)


@pytest.mark.parametrize('url', [None, '', 'not-a-database'])
def test_historical_mode_does_not_discover_a_url_from_environment(url: Any, make: Any) -> None:
    view, _ = make()
    module = reviewed('production_repository')
    with pytest.raises(module.RepositoryUnavailable, match='EXPLICIT_READ_ONLY_CONFIG_REQUIRED'):
        module.ProductionRepository(url, schema_mode='validate', enforce_restricted_role=True, historical_views=view)


def test_historical_constructor_never_reads_a_writer_secret(make: Any, monkeypatch: Any) -> None:
    view, _ = make()
    module = reviewed('production_repository')
    original = module.os.environ.get
    def forbid(key: str, *args: Any) -> Any:
        if key in ('DATABASE_URL', 'EVIDENCE_LEDGER_SIGNING_KEY'):
            pytest.fail('historical factory discovered a credential')
        return original(key, *args)
    monkeypatch.setattr(module.os.environ, 'get', forbid)
    repo = repository(module, view)
    assert repo._evidence_signing_key == b'' and repo._evidence_key_id == 'unsigned'


def test_append_rejected_even_with_a_borrowed_connection(make: Any, monkeypatch: Any) -> None:
    view, _ = make()
    module = reviewed('production_repository')
    repo = repository(module, view)
    monkeypatch.setattr(repo, 'ensure_schema', lambda: pytest.fail('append did any database work'))
    with pytest.raises(module.RepositoryUnavailable, match='HISTORICAL_REPOSITORY_READ_ONLY'):
        repo.append_evidence_event(aggregate_id='one', event_type='EXAMPLE', payload={}, _connection=object())


def test_same_connection_marked_read_only_and_closed(make: Any, monkeypatch: Any) -> None:
    view, _ = make()
    module = reviewed('production_repository')
    repo = repository(module, view)
    class Connection:
        read_only = False
        closed = False
        def close(self) -> None:
            self.closed = True
    connection = Connection()
    monkeypatch.setattr(module.psycopg, 'connect', lambda *args, **kwargs: connection)
    with repo.connect() as bound:
        assert bound is connection and connection.read_only is True
    assert connection.closed is True


def test_old_default_factory_has_no_historical_activation(monkeypatch: Any) -> None:
    module = reviewed('production_repository')
    repo = module.ProductionRepository('postgresql://synthetic/db', evidence_signing_key=b'fixture')
    assert repo._historical_views is None and repo._schema_mode == 'migrate'
    class Connection:
        read_only = False
        def close(self) -> None:
            pass
    connection = Connection()
    monkeypatch.setattr(module.psycopg, 'connect', lambda *args, **kwargs: connection)
    with repo.connect():
        assert connection.read_only is False


def test_explicit_factory_binds_source_to_same_read_only_repository_without_connecting(
        make: Any, tmp_path: Path, monkeypatch: Any) -> None:
    import sys
    module = reviewed('production_repository')
    monkeypatch.setitem(sys.modules, 'production_repository', module)
    monkeypatch.setattr(module.psycopg, 'connect', lambda *args, **kwargs: pytest.fail('factory construction connected'))
    spec = importlib.util.spec_from_file_location('reviewed_factory', ROOT / 'ledger_historical_repository.py')
    assert spec is not None and spec.loader is not None
    factory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(factory)
    class Objects:
        def get(self, kind: str, sha256: str) -> bytes | None:
            pytest.fail('factory construction fetched objects')
    repo = factory.read_only_repository(database_url='postgresql://synthetic/db', objects=Objects(),
                                        event_keys={}, seal_key=b'fixture', receipt_keys={}, private_parent=tmp_path)
    assert repo._historical_views is not None and repo._schema_mode == 'validate'
    proxy = repo._historical_views._history._source
    assert proxy.reader.connect == repo.connect
    assert repo._enforce_restricted_role is True and repo._evidence_signing_key == b''


def test_candidate_fingerprint_manifest_covers_transitive_read_library_sources() -> None:
    module = reviewed('equity_runtime_health')
    required = {'ledger_historical_views.py', 'ledger_historical_repository.py',
                'ledger_history_consumers.py', 'ledger_history_stream.py', 'ledger_runtime_reader.py',
                'ledger_read_contract.py', 'ledger_source_capture.py', 'ledger_cold_store.py',
                'ledger_segments.py', 'cold_catalog.py', 'catalog_receipts.py'}
    assert required <= set(cast(tuple[str, ...], module.RELEASE_FILES))
    assert len(module.RELEASE_FILES) == len(set(module.RELEASE_FILES))


def test_actual_release_artifact_seeds_include_every_fingerprinted_optional_source() -> None:
    health = reviewed('equity_runtime_health')
    packaging = reviewed('package_release')
    members = set(packaging.release_members(ROOT, packaging.FILES))
    assert set(health.RELEASE_FILES) <= members


@pytest.mark.parametrize('method', ['events', 'verify_evidence_ledger_continuity',
                                   'decision_outcome_records', 'matured_decision_dataset'])
def test_every_read_failure_is_propagated_without_a_hot_fallback(
        method: str, make: Any, monkeypatch: Any) -> None:
    view, source = make()
    source.fail = True
    repo = repository(reviewed('production_repository'), view)
    monkeypatch.setattr(repo, 'connect', lambda: pytest.fail('failed cold read used hot fallback'))
    kwargs = ({'strategy_id': 'frozen', 'target_version': 'synthetic-v1', 'horizon_sessions': 1}
              if method == 'matured_decision_dataset' else {})
    args = ('one',) if method == 'events' else ()
    with pytest.raises(ValueError) as caught:
        getattr(repo, method)(*args, **kwargs)
    assert 'private endpoint' not in str(caught.value)


def test_read_only_setup_failure_closes_connection_without_yielding(make: Any, monkeypatch: Any) -> None:
    view, _ = make()
    module = reviewed('production_repository')
    repo = repository(module, view)
    class Connection:
        closed = False
        @property
        def read_only(self) -> bool:
            return False
        @read_only.setter
        def read_only(self, value: bool) -> None:
            raise RuntimeError('synthetic setup failure')
        def close(self) -> None:
            self.closed = True
    connection = Connection()
    monkeypatch.setattr(module.psycopg, 'connect', lambda *args, **kwargs: connection)
    with pytest.raises(RuntimeError, match='synthetic setup failure'):
        with repo.connect():
            pytest.fail('unprotected connection was yielded')
    assert connection.closed is True
