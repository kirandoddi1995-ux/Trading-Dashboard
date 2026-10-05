"""Only synthetic mixed partitions; never inspect actual sealed datasets."""
import csv
import io
import json

import pytest

import export_development_inputs as exporter
from research_integrity import IntegrityError, canonical, digest
from test_automated_directional_replay import pack


def fixture(tmp_path, *, missing=False):
    def mutation(records, sessions):
        if missing:
            records.pop(10)
    pack(tmp_path, days=1, mutate=mutation)
    source = tmp_path / 'bars.csv'
    # Deliberately invalid later numeric data must never reach numeric parsing.
    with source.open('a') as stream:
        stream.write('2025-01-02T09:15:00+05:30,SEALED,SEALED,SEALED,SEALED,SEALED\n')
    sessions = tmp_path / 'sessions.json'
    rows = json.loads(sessions.read_bytes())
    rows.append({'open': '2025-01-02T09:15:00+05:30', 'previous_close': 'SEALED_INVALID_NUMBER'})
    sessions.write_bytes(canonical(rows))
    quality = tmp_path / 'quality.json'
    quality.write_bytes(canonical({'replay_ready': True, 'calendar_reviewed': True,
        'source_csv_sha256': digest(source.read_bytes()),
        'days': [{'date': '2022-01-03', 'status': 'REGULAR_COMPLETE', 'count': 74 if missing else 75},
                 {'date': '2025-01-02', 'status': 'REGULAR_COMPLETE', 'count': 1}]}))
    return dict(source_csv=source, sessions_path=sessions, quality_path=quality,
                quality_sha256=digest(quality.read_bytes()), sessions_sha256=digest(sessions.read_bytes()),
                output=tmp_path / 'development')


def test_export_preserves_source_and_never_interprets_sealed_numeric_values(tmp_path):
    kwargs = fixture(tmp_path)
    originals = {name: kwargs[name].read_bytes() for name in ('source_csv', 'sessions_path', 'quality_path')}
    result = exporter.export(**kwargs)
    assert result['rows'] == 75 and result['accepted_sessions'] == 1
    assert result['approval_authority'] is False and result['fill_evidence'] is False
    for name, raw in originals.items():
        assert kwargs[name].read_bytes() == raw
    assert b'SEALED' not in (kwargs['output'] / 'bars.csv').read_bytes()
    assert len(json.loads((kwargs['output'] / 'sessions.json').read_bytes())) == 1
    assert json.loads((kwargs['output'] / 'export.json').read_bytes()) == result


def test_missing_bars_are_preserved_and_session_excluded(tmp_path):
    kwargs = fixture(tmp_path, missing=True)
    result = exporter.export(**kwargs)
    assert result['rows'] == 74 and result['accepted_sessions'] == 0 and result['excluded_sessions'] == 1


@pytest.mark.parametrize('field', ['quality_sha256', 'sessions_sha256'])
def test_hash_mismatch_publishes_nothing(tmp_path, field):
    kwargs = fixture(tmp_path)
    kwargs[field] = 'a' * 64
    with pytest.raises(IntegrityError, match='HASH_MISMATCH'):
        exporter.export(**kwargs)
    assert not kwargs['output'].exists()


def test_no_overwrite(tmp_path):
    kwargs = fixture(tmp_path)
    exporter.export(**kwargs)
    original = (kwargs['output'] / 'export.json').read_bytes()
    with pytest.raises(IntegrityError, match='NEW_EXPORT'):
        exporter.export(**kwargs)
    assert (kwargs['output'] / 'export.json').read_bytes() == original


@pytest.mark.parametrize('mutation', ['readiness', 'sourcehash', 'coverage', 'badprice', 'unsorted'])
def test_bad_readiness_and_development_content_block(tmp_path, mutation):
    kwargs = fixture(tmp_path)
    quality = json.loads(kwargs['quality_path'].read_bytes())
    if mutation == 'readiness':
        quality['replay_ready'] = False
    elif mutation == 'sourcehash':
        quality['source_csv_sha256'] = 'a' * 64
    elif mutation == 'coverage':
        quality['days'][0]['count'] = 76
    else:
        rows = list(csv.DictReader(io.StringIO(kwargs['source_csv'].read_text())))
        if mutation == 'badprice':
            rows[0]['Open'] = 'WRONG'
        else:
            rows[0], rows[1] = rows[1], rows[0]
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=exporter.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
        kwargs['source_csv'].write_text(text.getvalue())
        quality['source_csv_sha256'] = digest(kwargs['source_csv'].read_bytes())
    kwargs['quality_path'].write_bytes(canonical(quality))
    kwargs['quality_sha256'] = digest(kwargs['quality_path'].read_bytes())
    with pytest.raises((IntegrityError, ValueError)):
        exporter.export(**kwargs)
    assert not kwargs['output'].exists()


def test_changed_source_during_export_is_not_published(tmp_path, monkeypatch):
    kwargs = fixture(tmp_path)
    original = exporter.file_hash
    calls = 0
    def changed(path):
        nonlocal calls
        if path == kwargs['source_csv']:
            calls += 1
            if calls == 2:
                return 'a' * 64
        return original(path)
    monkeypatch.setattr(exporter, 'file_hash', changed)
    with pytest.raises(IntegrityError, match='CHANGED_DURING'):
        exporter.export(**kwargs)
    assert not kwargs['output'].exists()
