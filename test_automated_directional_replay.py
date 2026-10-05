"""Synthetic replay recipes and causal golden checks; no real sealed files."""
from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path

import pytest

import automated_directional_replay as automation
from intraday_directional_replay import decisions, replay_session, validate
from research_integrity import IntegrityError, TrialLedger, canonical, digest, hash_value, recorded_trial

ROOT = Path(__file__).resolve().parents[1]


def pack(tmp_path, days=5, mutate=None):
    sessions, records = [], []
    for day in range(days):
        opening = datetime.fromisoformat('2022-01-03T09:15:00+05:30') + timedelta(days=day)
        sessions.append({'open': opening.isoformat(), 'close': (opening + timedelta(minutes=375)).isoformat(),
                         'previous_close': 24900 + day * 150, 'source': 'SYNTHETIC_ONLY',
                         'availability_basis': 'historical_final_assumed_bar_end',
                         'kind': 'REGULAR', 'replay_eligible': True, 'exclusion_reason': None})
        for bar in range(75):
            stamp = opening + timedelta(minutes=5 * bar)
            price = 25000 + day * 150 + bar * 2
            records.append({'timestamp': stamp.isoformat(), 'Open': price, 'High': price + 3,
                            'Low': price - 2, 'Close': price + 1,
                            'available_at': (stamp + timedelta(minutes=5)).isoformat()})
    if mutate:
        mutate(records, sessions)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=['timestamp', 'Open', 'High', 'Low', 'Close', 'available_at'])
    writer.writeheader()
    writer.writerows(records)
    bars, calendar = output.getvalue().encode(), canonical(sessions)
    (tmp_path / 'bars.csv').write_bytes(bars)
    (tmp_path / 'sessions.json').write_bytes(calendar)
    spec = {'version': automation.VERSION, 'purpose': automation.PURPOSE,
            'environment': automation.replay_environment(ROOT),
            'manifests': {name: {'relative_path': relative, 'sha256': digest(raw),
                                'start': '2022-01-01', 'end': '2024-12-31'}
                          for name, relative, raw in [('bars', 'bars.csv', bars),
                                                     ('sessions', 'sessions.json', calendar)]}}
    ledger = TrialLedger(tmp_path / 'trials.sqlite')
    h = hash_value(spec)
    ledger.append({'kind': 'REGISTERED', 'identity': h, 'spec_hash': h})
    return spec, ledger


def execute(spec, ledger, tmp_path):
    return automation.run(spec, source_root=ROOT, data_root=tmp_path, ledger=ledger)


def test_frozen_engine_repeats_without_authority(tmp_path):
    spec, ledger = pack(tmp_path)
    first = execute(spec, ledger, tmp_path)
    assert execute(spec, ledger, tmp_path) == first
    assert first['accepted_sessions'] == 5
    assert first['approval_authority'] is False and first['fill_evidence'] is False
    assert first['option_pnl'] is None
    assert first['automation']['input_hashes'] == {k: v['sha256'] for k, v in spec['manifests'].items()}
    assert all(trade['entry_at'][:10] == trade['exit_at'][:10]
               for variant in first['variants'].values() for trade in variant['trades'])
    # Reviewed characterization of the full indicator → decision → episode chain.
    # Fixed 5-session synthetic prices; expected first entries are not regenerated.
    for name, first_bar, later_bar in [('C_single_bar_no_volume', 60, 3),
                                       ('C_persistent_no_volume', 61, 4)]:
        trades = first['variants'][name]['trades']
        assert len(trades) == 5
        for day, trade in enumerate(trades):
            opening = datetime.fromisoformat('2022-01-03T09:15:00+05:30') + timedelta(days=day)
            offset = first_bar if day == 0 else later_bar
            entry, exit_price = 25000 + 150 * day + 2 * offset, 25149 + 150 * day
            assert trade['direction'] == 1
            assert trade['entry_at'] == (opening + timedelta(minutes=5 * offset)).astimezone(timezone.utc).isoformat()
            assert trade['exit_at'] == (opening + timedelta(minutes=375)).astimezone(timezone.utc).isoformat()
            assert trade['entry_reference'] == entry and trade['exit_reference'] == exit_price
            assert trade['reason'] == 'SESSION_END_CLOSE_REFERENCE'
            assert trade['directional_return_pct'] == pytest.approx(100 * (exit_price / entry - 1))
            assert trade['mae_pct'] == pytest.approx(-200 / entry)
            assert trade['mfe_pct'] == pytest.approx(100 * ((exit_price + 2) / entry - 1))


def test_analytic_golden_trade_list_and_excursions():
    import pandas as pd
    start = pd.Timestamp('2022-01-03T09:15:00+05:30')
    index = pd.date_range(start, periods=5, freq='5min')
    frame = pd.DataFrame({'Open': [100, 100, 102, 101, 99],
                          'High': [101, 103, 104, 102, 100],
                          'Low': [99, 99, 101, 98, 97],
                          'Close': [100, 102, 103, 100, 98]}, index=index)
    rows = [{'direction': value, 'available': True} for value in [1, -1, -1, 0, 0]]
    trades = replay_session(frame, rows, 1)
    # Hand-derived: enter after signal, reverse next open, no simultaneous flip.
    expected = [
        (1, '2022-01-03T09:20:00+05:30', '2022-01-03T09:25:00+05:30', 100, 102,
         'REVERSAL_NEXT_OPEN_REFERENCE', 2, -1, 3),
        (-1, '2022-01-03T09:30:00+05:30', '2022-01-03T09:40:00+05:30', 101, 98,
         'SESSION_END_CLOSE_REFERENCE', 300 / 101, -100 / 101, 400 / 101)]
    assert len(trades) == len(expected)
    for trade, row in zip(trades, expected):
        keys = ('direction', 'entry_at', 'exit_at', 'entry_reference', 'exit_reference', 'reason')
        assert tuple(trade[key] for key in keys) == row[:6]
        assert [trade[key] for key in ('directional_return_pct', 'mae_pct', 'mfe_pct')] == pytest.approx(row[6:])
    assert not replay_session(frame, [{'direction': 0, 'available': True}] * 4 + [rows[0]], 1)


def test_prefix_invariance_including_prior_sessions(tmp_path):
    import pandas as pd
    pack(tmp_path)
    frame = pd.read_csv(tmp_path / 'bars.csv')
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop('timestamp'), utc=True))
    sessions = json.loads((tmp_path / 'sessions.json').read_bytes())
    full = decisions(validate(frame, sessions)[0])
    prefix = decisions(validate(frame.iloc[:225], sessions[:3])[0])
    assert full[:3][0][2] == prefix[0][2]
    assert [item[2] for item in full[:3]] == [item[2] for item in prefix]


@pytest.mark.parametrize('field', ['timestamp', 'available_at', 'open', 'close', 'out_of_session_bars'])
@pytest.mark.parametrize('year', [2025, 2026])
def test_content_sealed_dates_block(tmp_path, field, year):
    def mutate(records, sessions):
        value = f'{year}-01-03T10:00:00+05:30'
        if field in ('timestamp', 'available_at'):
            records[0][field] = value
        else:
            sessions[0][field] = [value] if field == 'out_of_session_bars' else value
    spec, ledger = pack(tmp_path, mutate=mutate)
    with pytest.raises(IntegrityError, match='SEALED_OR_OUTSIDE'):
        execute(spec, ledger, tmp_path)
    assert ledger.events()[-1]['kind'] == 'FAILED'


@pytest.mark.parametrize('problem', ['duplicate', 'forming', 'naive', 'invalid_ohlc', 'empty',
                                   'eligibility', 'contradiction', 'special_eligible', 'boundary'])
def test_invalid_inputs_never_succeed(tmp_path, problem):
    def mutate(records, sessions):
        if problem == 'duplicate':
            records.insert(0, deepcopy(records[0]))
        elif problem == 'forming':
            records[0]['available_at'] = records[0]['timestamp']
        elif problem == 'naive':
            records[0]['timestamp'] = '2022-01-03T09:15:00'
        elif problem == 'invalid_ohlc':
            records[0]['Low'] = 99999
        elif problem == 'empty':
            records.clear()
        elif problem == 'eligibility':
            sessions[0]['replay_eligible'] = 'false'
        elif problem == 'contradiction':
            sessions[0]['exclusion_reason'] = 'MISSING_CLOSE'
        elif problem == 'special_eligible':
            sessions[0]['kind'] = 'SPECIAL'
        else:
            sessions[0]['close'] = sessions[0]['open']
    spec, ledger = pack(tmp_path, mutate=mutate)
    with pytest.raises(ValueError):
        execute(spec, ledger, tmp_path)
    assert ledger.events()[-1]['kind'] == 'FAILED'


@pytest.mark.parametrize('problem', ['missing_bar', 'special', 'closed', 'delayed'])
def test_exclusions_are_visible_and_reset_warmup(tmp_path, problem):
    def mutate(records, sessions):
        if problem == 'missing_bar':
            del records[90]
        elif problem == 'delayed':
            records[90]['available_at'] = '2022-01-04T10:36:00+05:30'
        else:
            sessions[1].update(kind=problem.upper(), replay_eligible=False, exclusion_reason=problem.upper())
            if problem == 'closed':
                records[:] = [row for row in records if not row['timestamp'].startswith('2022-01-04')]
    spec, ledger = pack(tmp_path, mutate=mutate)
    result = execute(spec, ledger, tmp_path)
    assert result['accepted_sessions'] == 4 and len(result['excluded_sessions']) == 1
    assert result['decisions'][1]['rows'][0]['detail']['decision_reason'] == 'INDICATOR_OR_SESSION_TREND_WARMUP'


def test_tuning_or_environment_change_is_rejected(tmp_path):
    spec, ledger = pack(tmp_path)
    spec['confirmations'] = 3
    with pytest.raises(IntegrityError, match='FROZEN_REPLAY_SPEC_MISMATCH'):
        execute(spec, ledger, tmp_path)
    assert ledger.events()[-1]['kind'] == 'REGISTERED'


def test_trial_cannot_claim_execution_authority(tmp_path):
    spec, ledger = pack(tmp_path)
    with pytest.raises(IntegrityError, match='RESEARCH_AUTHORITY_REQUIRED'):
        recorded_trial(ledger, hash_value(spec), lambda: {'approval_authority': True, 'fill_evidence': False})
    assert ledger.events()[-1]['kind'] == 'FAILED'


def test_cli_preparation_register_execution_and_no_private_output(tmp_path, capsys, monkeypatch):
    spec, _ = pack(tmp_path)
    args = ['--spec', str(tmp_path / 'recipe.json'), '--data-root', str(tmp_path),
            '--ledger', str(tmp_path / 'cli.sqlite')]
    prepare = ['--prepare']
    for name, manifest in spec['manifests'].items():
        prepare.extend([f'--{name}-relative', manifest['relative_path'], f'--{name}-sha256', manifest['sha256']])
    assert automation.main(args + prepare) == 0
    assert automation.main(args + ['--register']) == 0
    assert automation.main(args + ['--output', str(tmp_path / 'result.json')]) == 0
    assert automation.main(args + ['--output', str(tmp_path / 'result.json')]) == 2
    def failed_csv(*args, **kwargs):
        raise csv.Error('sensitive-synthetic-parser-detail')
    monkeypatch.setattr(automation, 'run', failed_csv)
    assert automation.main(args + ['--output', str(tmp_path / 'other.json')]) == 2
    output = capsys.readouterr().out
    assert str(tmp_path) not in output
    assert 'entry_reference' not in output
    assert 'sensitive-synthetic-parser-detail' not in output
    assert all(json.loads(line)['approval_authority'] is False for line in output.splitlines())


def test_opt_in_self_check_reuses_quality_without_credentials():
    # Exact small configuration contract, not a general-purpose YAML validator.
    # No extra test dependency is imposed on promotion/rollback test environments.
    workflow = (ROOT / '.github/workflows/research-self-check.yml').read_text()
    quality = (ROOT / '.github/workflows/quality.yml').read_text()
    active = '\n'.join(line for line in workflow.splitlines() if not line.lstrip().startswith('#'))
    assert 'on:\n  schedule:' in active and '\n  workflow_dispatch:' in active
    assert '\n  push:' not in active and '\n  pull_request:' not in active
    assert '\npermissions:\n  contents: read\n' in active
    assert 'cancel-in-progress: false' in active
    assert 'uses: ./.github/workflows/quality.yml' in active
    assert "if: github.event_name == 'workflow_dispatch' || (github.event_name == 'schedule' && vars.AUTOMATED_SELF_CHECK_ENABLED == 'true')" in active
    assert '  workflow_call:' in quality and 'timeout-minutes: 25' in quality
    assert 'secrets:' not in active and 'secrets.' not in active and 'secrets.' not in quality
    assert 'steps:' not in active and 'run:' not in active and 'write' not in active
