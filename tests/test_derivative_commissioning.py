"""Offline pilot policy and actual collection provenance regression checks."""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from derivative_commissioning import assess, authorised, validate_source, validate_pilot_scope
from derivative_repository import collect, main
from derivative_contracts import FoundationError


@pytest.mark.parametrize('event,confirmation,allowed', [
    ('workflow_dispatch', 'true', True), ('workflow_dispatch', 'false', False),
    ('workflow_dispatch', True, False), ('workflow_dispatch', 'TRUE', False),
    ('schedule', 'true', False), ('push', 'true', False), ('', '', False)])
def test_manual_only(event, confirmation, allowed):
    assert authorised('pilot', event=event, confirmation=confirmation) is allowed
    assert not authorised('check', event=event, confirmation=confirmation)
    assert not authorised('preview', event=event, confirmation=confirmation)


@pytest.mark.parametrize('cluster,derivatives', [(None, 0), (True, 0), (0, 0),
                                                (100, -1), (100, 101), (100.0, 0)])
def test_unknown_sizes_block(cluster, derivatives):
    with pytest.raises(ValueError):
        assess(cluster, derivatives)


def test_storage_boundaries():
    assert assess(476_000_000, 6_000_000)['pilot_storage_allowed']
    assert not assess(476_000_001, 0)['pilot_storage_allowed']
    assert not assess(471_936_147, 6_000_001)['pilot_storage_allowed']
    assert assess(471_936_147, 0)['approval_authority'] is False


@pytest.mark.parametrize('raw', [b'', b'x' * 1_048_577], ids=['empty', 'oversized'])
def test_source_bound(raw):
    with pytest.raises(ValueError):
        validate_source(raw)


def test_source_limit():
    validate_source(b'x' * 1_048_576)


@pytest.mark.parametrize('stamp,day,keys', [
    ('2026-10-02T03:00:00+00:00', date(2026, 10, 2), ['NSE_INDEX|Nifty 50']),
    ('2026-10-03T03:00:00+00:00', date(2026, 10, 3), ['NSE_INDEX|Nifty 50']),
    ('2026-02-01T03:00:00+00:00', date(2026, 2, 1), ['NSE_INDEX|Nifty 50']),
    ('2027-10-05T03:00:00+00:00', date(2027, 10, 5), ['NSE_INDEX|Nifty 50']),
    ('2026-10-05T03:00:00', date(2026, 10, 5), ['NSE_INDEX|Nifty 50']),
    ('2026-10-05T20:00:00+00:00', date(2026, 10, 5), ['NSE_INDEX|Nifty 50']),
    ('2026-10-05T03:00:00+00:00', date(2026, 10, 5), ['NSE_INDEX|Nifty Bank']),
    ('2026-10-05T03:00:00+00:00', None, []),
])
def test_pilot_date_scope_and_calendar_fail_closed(stamp, day, keys):
    with pytest.raises(ValueError):
        validate_pilot_scope(day, keys, datetime.fromisoformat(stamp))


def test_pilot_current_ist_date():
    validate_pilot_scope(date(2026, 10, 6), ['NSE_INDEX|Nifty 50'],
                         datetime(2026, 10, 5, 20, tzinfo=timezone.utc))


def test_preview_offline(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['derivative_repository.py'])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)['network_calls'] == 0


def test_pilot_without_confirmation_no_connection(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['derivative_repository.py', '--mode', 'pilot'])
    monkeypatch.delenv('DERIVATIVE_PILOT_CONFIRMATION', raising=False)
    import psycopg
    monkeypatch.setattr(psycopg, 'connect', lambda *a, **k: pytest.fail('Unexpected connection'))
    assert main() == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'FAILED'


def test_collection_uses_receipt_not_start():
    now = datetime(2026, 10, 6, 3, 15, tzinfo=timezone.utc)
    calls = []
    repo = SimpleNamespace(mark_pending=lambda *a: None,
                           ingest_master=lambda *a, **k: calls.append(k),
                           ingest_ban=lambda *a, **k: calls.append(k))
    record = {'underlying_key': 'NSE_INDEX|Nifty 50', 'segment': 'NSE_FO'}
    responses = iter([json.dumps([record]).encode(), b'ban fixture'])
    client = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(
        content=next(responses), url='https://example.org/ban', raise_for_status=lambda: None))
    receipts = iter([now + timedelta(seconds=2), now + timedelta(seconds=5)])
    assert collect(repo, client, trading_date=now.date(), underlyings=['NSE_INDEX|Nifty 50'],
                   now=now, clock=lambda: next(receipts)) == {'NSE': 1}
    assert [c['received_at'] for c in calls] == [now + timedelta(seconds=2), now + timedelta(seconds=5)]


def test_clock_backwards_blocks_publication():
    now = datetime(2026, 10, 6, tzinfo=timezone.utc)
    repo = SimpleNamespace(mark_pending=lambda *a: None,
                           ingest_master=lambda *a, **k: pytest.fail('Published with bad clock'))
    client = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(content=b'[]', raise_for_status=lambda: None))
    with pytest.raises(FoundationError, match='backwards'):
        collect(repo, client, trading_date=now.date(), underlyings=['NSE_INDEX|Nifty 50'],
                now=now, clock=lambda: now - timedelta(seconds=1))


def test_workflow_scheduled_read_only_and_no_push():
    text = (Path(__file__).resolve().parents[1] / '.github/workflows/derivative-references.yml').read_text()
    assert "inputs.mode || 'check'" in text
    assert "inputs.confirm_pilot == true" in text
    assert 'default: false' in text
    assert 'contents: read' in text
    assert '  push:' not in text and '  pull_request:' not in text


@pytest.mark.parametrize('role,tables,sizes,expected', [
    (('quant_derivative_ingestor', False, False, False, False, False), (9, True), (471_936_147, 0), 0),
    (('quant_derivative_ingestor', False, False, False, False, False), (9, True), (499_000_000, 0), 1),
    (('postgres', True, True, True, True, False), (9, True), (471_936_147, 0), 1),
    (('quant_derivative_ingestor', False, False, False, False, True), (9, True), (471_936_147, 0), 1),
    (('quant_derivative_ingestor', False, False, False, False, False), (8, True), (471_936_147, 0), 1),
    (('quant_derivative_ingestor', False, False, False, False, False), (9, False), (471_936_147, 0), 1),
])
def test_check_actual_cli_read_only(monkeypatch, capsys, role, tables, sizes, expected):
    import psycopg
    import requests
    from derivative_commissioning import TABLES_SQL, STORAGE_SQL
    options = []
    queries = []
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def close(self):
            pass
        def execute(self, sql):
            queries.append(sql)
            value = tables if sql == TABLES_SQL else sizes if sql == STORAGE_SQL else role
            return SimpleNamespace(fetchone=lambda: value)
    def connect(*a, **k):
        options.append(k['options'])
        return Connection()
    monkeypatch.setattr(psycopg, 'connect', connect)
    monkeypatch.setattr(requests, 'Session', lambda: pytest.fail('Provider accessed during check'))
    monkeypatch.setenv('DERIVATIVE_REFERENCE_DATABASE_URL', 'private-test-value-not-printed')
    monkeypatch.setattr('sys.argv', ['derivative_repository.py', '--mode', 'check'])
    assert main() == expected
    output = capsys.readouterr().out
    assert 'private-test-value' not in output
    assert 'default_transaction_read_only=on' in options[0]
    assert 'statement_timeout=10000' in options[0]
    assert all(q.lstrip().startswith(('SELECT', 'WITH')) for q in queries)
    if expected == 0:
        assert json.loads(output)['pilot_storage_allowed'] is (sizes[0] < 476_000_001)
