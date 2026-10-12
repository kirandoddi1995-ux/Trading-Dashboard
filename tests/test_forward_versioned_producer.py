"""Synthetic version-aware producer integration; no live data or credentials."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Any, Callable, cast

import pytest

import forward_versioned_producer as versioned
from forward_nifty_producer import prepare_config, ROOT
from research_integrity import IntegrityError, canonical
from test_forward_nifty_producer import candles as _candles

def candles(config: dict[str, Any], count: int) -> list[list[Any]]:
    return cast(Callable[[dict[str, Any], int], list[list[Any]]], _candles)(config, count)


@pytest.fixture
def config() -> dict[str, Any]:
    return prepare_config('2022-01-03', 24900, 'a'*64, '2022-01-03T08:45:00+05:30')


def make(tmp_path: Path, config: dict[str, Any]) -> versioned.Producer:
    frozen = versioned.recipe(config, '2022-01-03T09:00:00+05:30')
    return versioned.Producer(config, frozen, tmp_path / 'versioned-v1' / 'journal.sqlite')


def poll(producer: versioned.Producer, bars: list[list[Any]], minutes: int) -> dict[str, Any]:
    at = datetime.fromisoformat(producer.config['session_open']) + timedelta(minutes=minutes, seconds=30)
    return producer.record_poll(bars, received_at=at.isoformat(), computed_clock=lambda: at+timedelta(seconds=1))


def test_provider_close_revision_does_not_stop_next_observation_or_rewrite_first(tmp_path: Path,
                                                                               config: dict[str, Any]) -> None:
    producer = make(tmp_path, config)
    first = poll(producer, candles(config, 1), 5)['_versioned_bundle']
    original = deepcopy(first['polls'][0])
    revised = candles(config, 2)
    revised[0][4] += 1
    second = poll(producer, revised, 10)['_versioned_bundle']
    assert second['recorded_decisions'] == 2
    assert second['polls'][0] == original
    assert second['polls'][1]['decision']['projection']['revision_annotations'][0]['changed_fields'] == ['close']
    assert second['polls'][1]['decision']['projection']['bars'][0]['values'][3] == revised[0][4]
    assert second['polls'][0]['source']['closed_bars'][0]['values'][3] != revised[0][4]
    assert make(tmp_path, config).bundle() == second
    assert second['training_eligible'] is False
    assert first['polls'][0]['decision']['observation']['available'] is False


def test_first_late_poll_records_only_one_and_missing_prefix_stays_visible(tmp_path: Path,
                                                                        config: dict[str, Any]) -> None:
    producer = make(tmp_path, config)
    result = poll(producer, candles(config, 3)[1:], 15)
    assert result['status'] == 'VERSIONED_INPUT_BLOCKED'
    assert result['recorded_decisions'] == 0
    assert len(result['_versioned_bundle']['polls']) == 1
    later = poll(producer, candles(config, 4), 20)
    assert later['recorded_decisions'] == 1 and later['missing_decisions'] == 74
    assert later['_versioned_bundle']['polls'][0]['decision'] is None


@pytest.mark.parametrize('kind', ['duplicate_slot', 'naive', 'clock_backwards', 'forming', 'bad_ohlc', 'offgrid'])
def test_bad_poll_never_commits_partial(tmp_path: Path, config: dict[str, Any], kind: str) -> None:
    producer = make(tmp_path, config)
    poll(producer, candles(config, 1), 5)
    before = producer.bundle()
    bars = candles(config, 2)
    at = datetime.fromisoformat(config['session_open']) + timedelta(minutes=10, seconds=30)
    if kind == 'duplicate_slot':
        at -= timedelta(minutes=5)
        at += timedelta(seconds=1)
    elif kind == 'naive':
        at = at.replace(tzinfo=None)
    elif kind == 'forming':
        bars = candles(config, 1)
    elif kind == 'bad_ohlc':
        bars[-1][2] = 1
    elif kind == 'offgrid':
        bars[-1][0] = '2022-01-03T09:21:00+05:30'
    clock = lambda: at-timedelta(seconds=1) if kind == 'clock_backwards' else at
    if kind == 'forming':
        result = producer.record_poll(bars, received_at=at.isoformat(), computed_clock=clock)
        assert result['status'] == 'VERSIONED_INPUT_BLOCKED'
        assert result['recorded_decisions'] == 1
    else:
        with pytest.raises(IntegrityError):
            producer.record_poll(bars, received_at=at.isoformat(), computed_clock=clock)
        assert producer.bundle() == before


@pytest.mark.parametrize('kind', ['at_open', 'after_open', 'wrong_policy', 'wrong_sources', 'namespace', 'lock'])
def test_freeze_and_namespace_guards(tmp_path: Path, config: dict[str, Any], kind: str) -> None:
    frozen = versioned.recipe(config, '2022-01-03T09:00:00+05:30')
    path = tmp_path / 'versioned-v1' / 'journal.sqlite'
    if kind in ('at_open', 'after_open'):
        at = config['session_open'] if kind == 'at_open' else '2022-01-03T09:16:00+05:30'
        with pytest.raises(IntegrityError):
            versioned.recipe(config, at)
        return
    if kind == 'wrong_policy':
        frozen['policy']['training_eligible'] = True
    elif kind == 'wrong_sources':
        frozen['sources'] = {}
    elif kind == 'namespace':
        path = tmp_path / 'observations.sqlite'
    elif kind == 'lock':
        path.parent.mkdir()
        path.with_suffix('.producer-lock').write_bytes(b'owner-held')
    with pytest.raises(IntegrityError):
        versioned.Producer(config, frozen, path)
    if kind == 'lock':
        assert path.with_suffix('.producer-lock').read_bytes() == b'owner-held'


def test_sql_append_only_and_corrupt_restart_block(tmp_path: Path, config: dict[str, Any]) -> None:
    producer = make(tmp_path, config)
    poll(producer, candles(config, 1), 5)
    with sqlite3.connect(producer.path) as conn:
        for statement in ('DELETE FROM polls', "UPDATE polls SET sha='wrong'", 'DELETE FROM metadata'):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(statement)
        conn.execute('DROP TRIGGER polls_no_update')
        conn.execute("UPDATE polls SET sha='wrong'")
    with pytest.raises(IntegrityError, match='JOURNAL_CORRUPT'):
        make(tmp_path, config)


def test_archive_replays_actual_inputs_and_catches_changed_decision(tmp_path: Path,
                                                                 config: dict[str, Any]) -> None:
    producer = make(tmp_path, config)
    result = poll(producer, candles(config, 61), 305)
    bundle = result['_versioned_bundle']
    assert bundle['recorded_decisions'] == 1
    assert bundle['polls'][0]['decision']['observation']['available'] is True
    assert versioned.verify(deepcopy(bundle)) == bundle
    broken = deepcopy(bundle)
    broken['polls'][0]['decision']['observation']['direction'] = -1
    with pytest.raises(IntegrityError, match='REPLAY_MISMATCH'):
        versioned.verify(broken)


@pytest.mark.parametrize('damage', ['data', 'manifest'])
def test_remote_readback_mismatch_never_acknowledged(tmp_path: Path, config: dict[str, Any], damage: str) -> None:
    result = poll(make(tmp_path, config), candles(config, 1), 5)
    class Drive:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {}
        def put(self, name: str, raw: bytes, batch: str, kind: str, mime: str) -> str:
            self.objects[kind] = raw
            return kind
        def download(self, identity: str) -> bytes:
            return b'bad' if identity == damage else self.objects[identity]
    with pytest.raises(IntegrityError):
        versioned.publish(Drive(), result)


def test_original_journal_never_touched(tmp_path: Path, config: dict[str, Any]) -> None:
    original = tmp_path / 'observations.sqlite'
    original.write_bytes(b'private original remains unchanged')
    producer = make(tmp_path, config)
    poll(producer, candles(config, 1), 5)
    assert original.read_bytes() == b'private original remains unchanged'
    assert producer.root == ROOT


def test_missing_journal_not_recreated_and_missing_guard_blocks(tmp_path: Path, config: dict[str, Any]) -> None:
    producer = make(tmp_path, config)
    producer.path.unlink()
    with pytest.raises(IntegrityError, match='MISSING_OR_UNSAFE'):
        producer.bundle()
    assert not producer.path.exists()
    producer = make(tmp_path, config)
    with sqlite3.connect(producer.path) as conn:
        conn.execute('DROP TRIGGER polls_no_delete')
    with pytest.raises(IntegrityError, match='APPEND_GUARDS_MISSING'):
        producer.bundle()


def test_remote_failure_keeps_commit_next_generation_contains_both(tmp_path: Path, config: dict[str, Any]) -> None:
    producer = make(tmp_path, config)
    first = poll(producer, candles(config, 1), 5)
    class Drive:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {}
        def put(self, name: str, raw: bytes, batch: str, kind: str, mime: str) -> str:
            self.objects[kind] = raw
            return kind
        def download(self, identity: str) -> bytes:
            return self.objects[identity]
    drive = Drive()
    acknowledgement = versioned.publish(drive, first)
    assert acknowledgement['status'] == 'REMOTE_VERIFIED'
    assert producer.bundle() == first['_versioned_bundle']
    second = poll(producer, candles(config, 2), 10)
    assert versioned.publish(drive, second)['recorded_decisions'] == 2
    assert second['_versioned_bundle']['polls'][0] == first['_versioned_bundle']['polls'][0]


def test_full_session_bounds_and_asof_replay(tmp_path: Path, config: dict[str, Any]) -> None:
    producer = make(tmp_path, config)
    for slot in range(1, 76):
        result = poll(producer, candles(config, slot), slot*5)
    bundle = result['_versioned_bundle']
    assert bundle['recorded_decisions'] == 75 and bundle['missing_decisions'] == 0
    assert len(canonical(bundle)) < versioned.MAX_BUNDLE_BYTES
    assert versioned.verify(bundle) == bundle
    with pytest.raises(IntegrityError):
        poll(producer, candles(config, 75), 380)
    assert producer.bundle() == bundle
