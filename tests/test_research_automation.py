"""Synthetic-only research integrity checks; never open private market data."""
from copy import deepcopy
from pathlib import Path
import json
import sqlite3
import subprocess
import sys

import pytest

import automated_development_checks as checks
from research_integrity import DevelopmentManifest, IntegrityError, TrialLedger, canonical, digest, hash_value

ROOT = Path(__file__).resolve().parents[1]


def synthetic_report():
    trades = [{'entry_at': f'2022-01-{day:02d}T10:00:00+05:30',
               'exit_at': f'2022-01-{day:02d}T15:30:00+05:30',
               'directional_return_pct': .03, 'mae_pct': -.1, 'mfe_pct': .1,
               'reason': 'SESSION_END_CLOSE_REFERENCE'} for day in (3, 4)]
    return {'mode': 'DIRECTIONAL_RESEARCH', 'approval_authority': False,
            'fill_evidence': False, 'option_pnl': None, 'accepted_sessions': 2,
            'excluded_sessions': [],
            'decisions': [{'session_open': f'2022-01-{day:02d}T09:15:00+05:30'} for day in (3, 4)],
            'variants': {name: {'episodes': 2, 'trades': deepcopy(trades)} for name in checks.VARIANTS}}


def setup_case(tmp_path, report=None):
    payload = canonical(report if report is not None else synthetic_report())
    (tmp_path / 'development.json').write_bytes(payload)
    spec = {'version': checks.VERSION, 'purpose': 'PARKED_BENCHMARK_DIAGNOSTICS',
            'manifest': {'relative_path': 'development.json', 'sha256': digest(payload),
                         'start': '2022-01-01', 'end': '2024-12-31'},
            'environment': checks.environment(ROOT)}
    ledger = TrialLedger(tmp_path / 'trials.sqlite')
    fingerprint = hash_value(spec)
    ledger.append({'kind': 'REGISTERED', 'identity': fingerprint, 'spec_hash': fingerprint})
    return spec, ledger


def execute(spec, ledger, tmp_path):
    return checks.run(spec, source_root=ROOT, data_root=tmp_path, ledger=ledger)


def test_golden_repeated_result_and_no_execution_authority(tmp_path, monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError('Network forbidden')

    monkeypatch.setattr(socket, 'create_connection', forbidden)
    spec, ledger = setup_case(tmp_path)
    first = execute(spec, ledger, tmp_path)
    assert execute(spec, ledger, tmp_path) == first
    assert [item['kind'] for item in ledger.events()] == [
        'REGISTERED', 'STARTED', 'SUCCEEDED', 'STARTED', 'SUCCEEDED']
    assert first['approval_authority'] is False
    assert first['fill_evidence'] is False
    assert first['futures_pnl'] is None and first['option_pnl'] is None
    for value in first['variants'].values():
        case = value['hypothetical_cost_sensitivity'][3]
        assert case['reference_mean_minus_hurdle_pct'] == '-0.02'
        assert case['reference_ci95_minus_hurdle_pct'] == ['-0.02', '-0.02']
        assert case['screen'] == 'UPPER_INTERVAL_BELOW_ASSUMED_HURDLE'


@pytest.mark.parametrize('year', [2025, 2026])
@pytest.mark.parametrize('location', ['declared', 'accepted', 'excluded', 'entry', 'exit'])
def test_sealed_years_never_produce_results(tmp_path, year, location):
    raw = synthetic_report()
    instant = f'{year}-01-03T10:00:00+05:30'
    if location == 'accepted':
        raw['decisions'][0]['session_open'] = instant
    elif location == 'excluded':
        raw['excluded_sessions'] = [{'open': instant}]
    elif location in ('entry', 'exit'):
        raw['variants']['C_single_bar_no_volume']['trades'][0][location + '_at'] = instant
    spec, ledger = setup_case(tmp_path, raw)
    if location == 'declared':
        spec['manifest']['end'] = f'{year}-12-31'
        ledger = TrialLedger(tmp_path / 'sealed.sqlite')
        h = hash_value(spec)
        ledger.append({'kind': 'REGISTERED', 'identity': h, 'spec_hash': h})
    with pytest.raises(IntegrityError):
        execute(spec, ledger, tmp_path)
    assert ledger.events()[-1]['kind'] == 'FAILED'


@pytest.mark.parametrize('relative', ['../report.json', '/report.json', 'C:/report.json', 'dir\\report.json', ''])
def test_unsafe_paths_rejected_before_read(tmp_path, relative):
    manifest = DevelopmentManifest(relative, 'a' * 64, '2022-01-01', '2024-12-31')
    with pytest.raises(IntegrityError, match='UNSAFE_DATA_PATH'):
        manifest.load(tmp_path)


@pytest.mark.parametrize('mutation', ['missing', 'hash', 'environment', 'variants', 'period', 'naive'])
def test_bad_inputs_block_and_record_failures(tmp_path, mutation):
    raw = synthetic_report()
    if mutation == 'variants':
        raw['variants'] = {}
    if mutation == 'naive':
        raw['decisions'][0]['session_open'] = '2022-01-03T09:15:00'
    spec, ledger = setup_case(tmp_path, raw)
    if mutation == 'missing':
        (tmp_path / 'development.json').unlink()
    elif mutation == 'hash':
        (tmp_path / 'development.json').write_text('{}')
    elif mutation == 'environment':
        spec['environment']['python'] = '0'
    elif mutation == 'period':
        spec['manifest']['start'] = '2022-02-01'
        ledger = TrialLedger(tmp_path / 'period.sqlite')
        h = hash_value(spec)
        ledger.append({'kind': 'REGISTERED', 'identity': h, 'spec_hash': h})
    with pytest.raises(IntegrityError):
        execute(spec, ledger, tmp_path)
    assert ledger.events()[-1]['kind'] == ('REGISTERED' if mutation == 'environment' else 'FAILED')


def test_empty_evidence_stays_missing(tmp_path):
    raw = synthetic_report()
    for variant in raw['variants'].values():
        variant.update(episodes=0, trades=[])
    spec, ledger = setup_case(tmp_path, raw)
    result = execute(spec, ledger, tmp_path)
    for variant in result['variants'].values():
        for case in variant['hypothetical_cost_sensitivity']:
            assert case['reference_mean_minus_hurdle_pct'] is None
            assert case['screen'] == 'INSUFFICIENT_EVIDENCE'


def test_ledger_preserves_incomplete_attempt_and_enforces_terminal_identity(tmp_path):
    ledger = TrialLedger(tmp_path / 'trials.sqlite')
    h = 'a' * 64
    with pytest.raises(IntegrityError):
        ledger.append({'kind': 'REGISTERED', 'identity': 'wrong', 'spec_hash': h})
    ledger.append({'kind': 'REGISTERED', 'identity': h, 'spec_hash': h})
    ledger.append({'kind': 'STARTED', 'identity': 'run', 'spec_hash': h})
    assert TrialLedger(ledger.path).events()[-1]['kind'] == 'STARTED'
    with pytest.raises(IntegrityError, match='TRIAL_SPEC_MISMATCH'):
        ledger.append({'kind': 'FAILED', 'identity': 'run', 'spec_hash': 'b' * 64})
    ledger.append({'kind': 'FAILED', 'identity': 'run', 'spec_hash': h})
    with pytest.raises(IntegrityError, match='TRIAL_NOT_ACTIVE'):
        ledger.append({'kind': 'FAILED', 'identity': 'run', 'spec_hash': h})
    with ledger.connect() as connection:
        for statement in ('DELETE FROM research_events', "UPDATE research_events SET event_json='{}'"):
            with pytest.raises(sqlite3.IntegrityError, match='APPEND_ONLY'):
                connection.execute(statement)


def test_changed_result_for_same_spec_blocks(tmp_path, monkeypatch):
    spec, ledger = setup_case(tmp_path)
    execute(spec, ledger, tmp_path)
    original = checks.screen

    def changed(raw):
        result = original(raw)
        result['unexpected'] = True
        return result

    monkeypatch.setattr(checks, 'screen', changed)
    with pytest.raises(IntegrityError, match='REPRODUCIBILITY_MISMATCH'):
        execute(spec, ledger, tmp_path)
    assert ledger.events()[-1]['kind'] == 'FAILED'


def test_atomic_publication_never_overwrites(tmp_path, monkeypatch):
    target = tmp_path / 'result.json'
    checks.write_once(target, {'ok': True})
    with pytest.raises(FileExistsError):
        checks.write_once(target, {'ok': False})
    assert json.loads(target.read_text()) == {'ok': True}
    assert list(tmp_path.iterdir()) == [target]

    def fail(*args):
        raise OSError('synthetic publication failure')

    monkeypatch.setattr(checks.os, 'link', fail)
    with pytest.raises(OSError):
        checks.write_once(tmp_path / 'absent.json', {})
    assert list(tmp_path.iterdir()) == [target]


def test_prepare_register_run_cli_and_sanitized_failure(tmp_path, capsys):
    raw = canonical(synthetic_report())
    (tmp_path / 'development.json').write_bytes(raw)
    spec = tmp_path / 'spec.json'
    base = ['--spec', str(spec), '--data-root', str(tmp_path), '--ledger', str(tmp_path / 'trials.sqlite')]
    assert checks.main(base + ['--prepare', '--report-relative', 'development.json',
                               '--report-sha256', digest(raw)]) == 0
    assert checks.main(base + ['--register']) == 0
    assert checks.main(base + ['--output', str(tmp_path / 'result.json')]) == 0
    assert checks.main(base + ['--output', str(tmp_path / 'result.json')]) == 2
    output = capsys.readouterr().out
    assert str(tmp_path) not in output
    assert 'directional_return_pct' not in output
    assert all(json.loads(line)['approval_authority'] is False for line in output.splitlines())


def test_timezone_boundary_is_checked_in_ist(tmp_path):
    raw = synthetic_report()
    raw['excluded_sessions'] = [{'open': '2024-12-31T20:00:00+00:00'}]
    spec, ledger = setup_case(tmp_path, raw)
    with pytest.raises(IntegrityError, match='REPORT_OUTSIDE_DECLARED_PERIOD'):
        execute(spec, ledger, tmp_path)


def test_declared_sealed_period_is_rejected_before_file_open(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Sealed file was opened')

    monkeypatch.setattr(Path, 'open', forbidden)
    with pytest.raises(IntegrityError, match='SEALED_OR_UNSUPPORTED_PARTITION'):
        DevelopmentManifest('private.json', 'a' * 64, '2025-01-01', '2025-12-31').load(tmp_path)


@pytest.mark.parametrize('payload', [b'', b'null', b'[]', b'\xff'])
def test_invalid_or_empty_payload_cannot_supply_evidence(tmp_path, payload):
    (tmp_path / 'data.json').write_bytes(payload)
    manifest = DevelopmentManifest('data.json', digest(payload), '2022-01-01', '2024-12-31')
    with pytest.raises(IntegrityError):
        manifest.load(tmp_path)


def test_size_limit_and_invalid_dates(tmp_path, monkeypatch):
    import research_integrity
    (tmp_path / 'data.json').write_bytes(b'{}')
    with pytest.raises(IntegrityError, match='INVALID_DATA_PERIOD'):
        DevelopmentManifest('data.json', 'a' * 64, 'invalid', '2024-12-31').load(tmp_path)
    monkeypatch.setattr(research_integrity, 'MAX_INPUT_BYTES', 1)
    with pytest.raises(IntegrityError, match='DATA_TOO_LARGE'):
        DevelopmentManifest('data.json', digest(b'{}'), '2022-01-01', '2024-12-31').load(tmp_path)


def test_parallel_trial_chain_is_serialized(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    ledger = TrialLedger(tmp_path / 'ledger.sqlite')
    h = 'a' * 64
    ledger.append({'kind': 'REGISTERED', 'identity': h, 'spec_hash': h})

    def attempt(number):
        identity = str(number)
        ledger.append({'kind': 'STARTED', 'identity': identity, 'spec_hash': h})
        ledger.append({'kind': 'SUCCEEDED', 'identity': identity, 'spec_hash': h, 'result_hash': 'b' * 64})

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(attempt, range(8)))
    assert len(ledger.events()) == 17


def test_chain_corruption_is_rejected(tmp_path):
    spec, ledger = setup_case(tmp_path)
    with ledger.connect() as connection:
        connection.execute('DROP TRIGGER research_no_update')
        connection.execute("UPDATE research_events SET event_json='{}'")
    with pytest.raises(IntegrityError, match='TRIAL_LEDGER_CORRUPT'):
        execute(spec, ledger, tmp_path)


def test_cli_never_accepts_repository_state(capsys):
    assert checks.main(['--spec', str(ROOT / 'unsafe.json'), '--data-root', str(ROOT),
                        '--ledger', str(ROOT / 'unsafe.sqlite')]) == 2
    assert str(ROOT) not in capsys.readouterr().out
    assert not (ROOT / 'unsafe.sqlite').exists()


def test_import_foundation_with_external_io_denied(tmp_path):
    script = '''
import sys
def deny(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo', 'socket.sendto', 'subprocess.Popen', 'os.system'):
        raise RuntimeError('External I/O forbidden')
sys.addaudithook(deny)
import research_integrity
import automated_development_checks
import automated_directional_replay
import research_replay_comparison
import automation_health
import research_input_archive
import archived_directional_replay
import research_replay_check
import export_development_inputs
import forward_nifty_producer
import forward_nifty_archive
import forward_nifty_job
import nifty_previous_close
import forward_windows_credentials
import forward_nifty_schedule
print('OFFLINE_IMPORT_OK')
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'OFFLINE_IMPORT_OK'
