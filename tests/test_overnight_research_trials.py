"""Private temporary ledgers only; persistence, crash, tampering and failure tests."""
from pathlib import Path
from contextlib import closing
import sqlite3

import pytest

from overnight_research_dataset import ResearchError
from overnight_research_ml import Fold, ModelSpec
from overnight_research_trials import DurableTrialRegistry


def spec() -> ModelSpec:
    return ModelSpec('fixture', ('return',), 'LINEAR_RIDGE_RESEARCH',
        '{"alpha":1,"minimum_train_rows":2}', 'c'*64, '2026-10-12T08:00:00+05:30', 0)


def start(registry: DurableTrialRegistry, trial_id: str = 'trial-1') -> str:
    return registry.start(trial_id=trial_id, spec=spec(), dataset_sha256='d'*64,
        folds=[Fold(('a'*64, 'b'*64), ('e'*64,), (), 'READY_FOR_OFFLINE_VALIDATION',
                    '2026-10-13T10:00:00+05:30')], started_at='2026-10-13T16:00:00+05:30')


def test_restart_retains_started_crash_and_completed_trials(tmp_path: Path) -> None:
    path = tmp_path / 'overnight_research_trials.sqlite'
    registry = DurableTrialRegistry(path, create=True)
    first = start(registry)
    reopened = DurableTrialRegistry(path)
    assert reopened.unresolved_trials() == ('trial-1',)
    assert reopened.events()[0]['event_sha256'] == first
    finish = reopened.finish(trial_id='trial-1', completed_at='2026-10-13T16:01:00+05:30',
                             status='COMPLETED', metrics={'mae': 1.0})
    again = DurableTrialRegistry(path)
    assert again.unresolved_trials() == () and len(again.events()) == 2
    assert again.events()[1]['previous_sha256'] == first and again.events()[1]['event_sha256'] == finish
    with pytest.raises(ResearchError):
        again.finish(trial_id='trial-1', completed_at='2026-10-13T16:02:00+05:30',
                     status='COMPLETED', metrics={'mae': 2.0})


def test_failed_and_insufficient_trials_are_append_only(tmp_path: Path) -> None:
    path = tmp_path / 'overnight_research_trials.sqlite'
    registry = DurableTrialRegistry(path, create=True)
    start(registry)
    registry.finish(trial_id='trial-1', completed_at='2026-10-13T16:01:00+05:30',
                    status='FAILED', metrics={}, failure_code='FIT_FAILED')
    start(registry, 'trial-2')
    registry.finish(trial_id='trial-2', completed_at='2026-10-13T16:01:00+05:30',
                    status='INSUFFICIENT_DATA', metrics={})
    assert [event['state'] for event in registry.events()] == ['STARTED', 'FAILED', 'STARTED', 'INSUFFICIENT_DATA']
    with closing(sqlite3.connect(path)) as conn:
        for statement in ('DELETE FROM events', "UPDATE events SET sha='bad'"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(statement)
    with pytest.raises(ResearchError):
        start(registry)


def test_missing_or_corrupt_ledger_is_not_repaired(tmp_path: Path) -> None:
    path = tmp_path / 'overnight_research_trials.sqlite'
    registry = DurableTrialRegistry(path, create=True)
    start(registry)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('DROP TRIGGER events_no_update')
        conn.commit()
    with pytest.raises(ResearchError, match='GUARDS'):
        DurableTrialRegistry(path)
    path.unlink()
    with pytest.raises(ResearchError, match='MISSING'):
        registry.events()
    assert not path.exists()


def test_unsafe_path_and_unstarted_completion_block(tmp_path: Path) -> None:
    with pytest.raises(ResearchError):
        DurableTrialRegistry(Path('overnight_research_trials.sqlite'))
    registry = DurableTrialRegistry(tmp_path / 'overnight_research_trials.sqlite', create=True)
    with pytest.raises(ResearchError):
        registry.finish(trial_id='unknown', completed_at='2026-10-13T16:01:00+05:30', status='FAILED',
                        metrics={}, failure_code='FAILED')


def test_hash_tampering_survives_guard_recreation_as_failure(tmp_path: Path) -> None:
    path = tmp_path / 'overnight_research_trials.sqlite'
    registry = DurableTrialRegistry(path, create=True)
    start(registry)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('DROP TRIGGER events_no_update')
        conn.execute("UPDATE events SET sha='bad'")
        conn.execute("CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END")
        conn.commit()
    with pytest.raises(ResearchError, match='CORRUPT'):
        DurableTrialRegistry(path)


def test_missing_not_silently_new(tmp_path: Path) -> None:
    with pytest.raises(ResearchError, match='MISSING'):
        DurableTrialRegistry(tmp_path / 'overnight_research_trials.sqlite')


def test_noop_append_guards_block_reopen(tmp_path: Path) -> None:
    path = tmp_path / 'overnight_research_trials.sqlite'
    DurableTrialRegistry(path, create=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('DROP TRIGGER events_no_delete')
        connection.execute('CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT 1; END')
        connection.commit()
    with pytest.raises(ResearchError, match='GUARDS'):
        DurableTrialRegistry(path)
