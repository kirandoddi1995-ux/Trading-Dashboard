"""Offline capture contracts: no broker, Drive or database calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import ssl
from unittest.mock import Mock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from derivative_contracts import digest
import option_capture as core
import option_capture_archive as archive
import option_capture_job as job

NOW = datetime(2026, 9, 29, 4, 45, tzinfo=timezone.utc)
SPOT = 'NSE_INDEX|Nifty 50'
CONFIG = core.policy([SPOT])


def master():
    result = []
    for days in (2, 9):
        for strike in range(90, 112, 2):
            for kind in ('CE', 'PE'):
                result.append(dict(instrument_key=f'NSE_FO|{days}-{strike}-{kind}',
                    underlying_key=SPOT, exchange='NSE', segment='NSE_FO',
                    instrument_type=kind, expiry=int((NOW+timedelta(days=days)).timestamp()*1000),
                    strike_price=strike, lot_size=65, tick_size=5, weekly=True))
        result.append(dict(instrument_key=f'NSE_FO|{days}-FUT', underlying_key=SPOT,
            exchange='NSE', segment='NSE_FO', instrument_type='FUT', lot_size=65, tick_size=5,
            expiry=int((NOW+timedelta(days=days)).timestamp()*1000)))
    return result


def selected():
    return {SPOT: dict(instrument_key=SPOT, underlying_key=SPOT, role='SPOT'),
            'NSE_FO|F': dict(instrument_key='NSE_FO|F', underlying_key=SPOT, role='FUTURE'),
            'NSE_FO|C': dict(instrument_key='NSE_FO|C', underlying_key=SPOT, role='OPTION')}


def message():
    market = dict(ltpc={'ltp': 100, 'ltt': str(int(NOW.timestamp()*1000))},
                  marketLevel={'bidAskQuote': [dict(bidP=99, askP=101, bidQ=65, askQ=130)]},
                  iv=20, oi=1000, vtt='100',
                  optionGreeks=dict(delta=0.5, gamma=0.01, theta=-2, vega=4))
    return dict(currentTs=str(int(NOW.timestamp()*1000)),
                marketInfo={'segmentStatus': {'NSE_EQ': 'NORMAL_OPEN', 'NSE_FO': 'NORMAL_OPEN'}},
                feeds={SPOT: {'fullFeed': {'indexFF': {'ltpc': market['ltpc']}}},
                       'NSE_FO|F': {'fullFeed': {'marketFF': deepcopy(market)}},
                       'NSE_FO|C': {'fullFeed': {'marketFF': deepcopy(market)}}})


def report():
    buffer = core.SnapshotBuffer(selected(), CONFIG)
    buffer.ingest(message(), NOW)
    result = buffer.snapshot(NOW)
    result.update(format=core.VERSION, sample_id=core.sample_identity(CONFIG, NOW.date(), '1015'),
                  policy_hash=digest(CONFIG), policy=CONFIG, trading_date=str(NOW.date()), slot='1015')
    result.update(core.timing_evidence(result, NOW.date(), '1015'))
    return result


@pytest.mark.parametrize('bad', [[], [SPOT]*2, ['BSE_INDEX|SENSEX'], [['nested']], None,
                                   ['NSE_EQ|A', 'NSE_EQ|B', 'NSE_EQ|C', 'NSE_EQ|D']])
def test_universe_is_bounded_and_nse_only(bad):
    with pytest.raises(core.CaptureError):
        core.policy(bad)


def test_selection_preserves_master_metadata_and_snapshot_identity():
    contracts, inventory = core.select_contracts(master(), {SPOT: 100}, CONFIG, NOW.date())
    assert len(contracts) == 47
    assert len(inventory[0]['option_expiries']) == 2
    assert contracts['NSE_FO|2-100-CE']['lot_size'] == 65
    assert contracts['NSE_FO|2-100-CE']['tick_size'] == 5
    assert contracts['NSE_FO|2-100-CE']['weekly'] is True
    assert core.sample_identity(CONFIG, NOW.date(), '1015') != core.sample_identity(CONFIG, NOW.date(), '1145')


@pytest.mark.parametrize('change', ['pair', 'terms', 'key', 'future'])
def test_bad_master_cannot_create_plausible_complete_capture(change):
    rows = master()
    if change == 'pair':
        rows.pop(0)
    elif change == 'terms':
        rows[0]['lot_size'] = None
    elif change == 'key':
        rows[1]['instrument_key'] = rows[0]['instrument_key']
    else:
        rows = [r for r in rows if r['instrument_type'] != 'FUT']
    with pytest.raises(core.CaptureError):
        core.select_contracts(rows, {SPOT: 100}, CONFIG, NOW.date())


def test_slot_uses_ist_and_never_backdates_late_capture():
    assert core.check_slot(NOW, '1015') == NOW.date()
    assert core.check_slot(NOW+timedelta(minutes=10), '1015') == NOW.date()
    for when in (NOW-timedelta(seconds=1), NOW+timedelta(minutes=10, seconds=1), NOW+timedelta(days=4)):
        with pytest.raises(core.CaptureError, match='MISSED_SLOT'):
            core.check_slot(when, '1015')


def test_aligned_capture_retains_raw_units_and_unknown_conventions():
    result = report()
    assert result['status'] == 'CAPTURED'
    assert result['approval_eligible'] is False and result['mode'] == 'RESEARCH_ONLY'
    assert result['rate'] is None and result['dividend_yield'] is None
    option = next(r for r in result['rows'] if r['role'] == 'OPTION')
    assert option['iv_raw'] == 20  # No percent/decimal guessing.
    assert option['exchange_at'] is None and option['greek_calculated_at'] is None
    assert option['provider']['feed'] == message()['feeds']['NSE_FO|C']


@pytest.mark.parametrize('bad', ['missing_greek', 'missing_book', 'crossed', 'session', 'missing_key', 'stale'])
def test_incomplete_data_is_retained_but_never_passed(bad):
    msg = message()
    option = msg['feeds']['NSE_FO|C']['fullFeed']['marketFF']
    if bad == 'missing_greek':
        del option['optionGreeks']['gamma']
    elif bad == 'missing_book':
        option['marketLevel']['bidAskQuote'][0]['bidQ'] = 0
    elif bad == 'crossed':
        option['marketLevel']['bidAskQuote'][0]['bidP'] = 102
    elif bad == 'session':
        msg['marketInfo']['segmentStatus']['NSE_FO'] = 'CLOSED'
    elif bad == 'missing_key':
        del msg['feeds']['NSE_FO|C']
    buffer = core.SnapshotBuffer(selected(), CONFIG)
    buffer.ingest(msg, NOW)
    result = buffer.snapshot(NOW+timedelta(seconds=6) if bad == 'stale' else NOW)
    assert result['status'] == 'PARTIAL'
    assert any(r['reasons'] for r in result['rows'])


def test_explicit_zero_is_preserved_but_omitted_zero_is_unknown_and_no_merge():
    msg = message()
    msg['feeds']['NSE_FO|C']['fullFeed']['marketFF']['optionGreeks']['gamma'] = 0
    buffer = core.SnapshotBuffer(selected(), CONFIG)
    buffer.ingest(msg, NOW)
    assert buffer.snapshot(NOW)['status'] == 'CAPTURED'
    buffer.ingest(dict(currentTs=msg['currentTs'], feeds={'NSE_FO|C': {'ltpc': {'ltp': 100}}}), NOW)
    row = next(r for r in buffer.snapshot(NOW)['rows'] if r['role'] == 'OPTION')
    assert row['greeks_raw'] is None and row['bid'] is None
    assert 'MISSING_GAMMA' in row['reasons']


def test_cross_instrument_skew():
    msg = message()
    buffer = core.SnapshotBuffer(selected(), CONFIG)
    buffer.ingest(msg, NOW)
    msg['currentTs'] = str(int((NOW+timedelta(seconds=3)).timestamp()*1000))
    msg['feeds'] = {'NSE_FO|C': msg['feeds']['NSE_FO|C']}
    buffer.ingest(msg, NOW+timedelta(seconds=3))
    assert all('CROSS_INSTRUMENT_SKEW' in r['reasons'] for r in buffer.snapshot(NOW+timedelta(seconds=3))['rows'])


class MemoryDrive:
    folder_id = 'test-folder'

    def __init__(self):
        self.files, self.keys = {}, {}

    def put(self, name, data, batch, kind, mime):
        key = batch, kind
        if key not in self.keys:
            ident = str(len(self.files))
            self.keys[key], self.files[ident] = ident, data
        return self.keys[key]

    def download(self, ident):
        return self.files[ident]

    def check_folder(self):
        pass

    def close(self):
        pass


@pytest.fixture
def drive(monkeypatch):
    value = MemoryDrive()
    monkeypatch.setattr(archive, 'lookup', lambda d, sample, kind: d.keys.get((sample, kind)))
    return value


def test_verified_archive_roundtrip_resume_and_daily_audit(drive):
    r = report()
    manifest = archive.publish(drive, r)
    assert manifest['rows'] == 3
    assert archive.verify(drive.download(manifest['data_file_id']), r['sample_id'], r['policy_hash']) == r
    assert archive.resume(drive, r['sample_id'], r['policy_hash']) == manifest
    assert archive.inspect_sample(drive, r['sample_id'], r['policy_hash']) == 'CAPTURED'
    assert len(drive.files) == 2


def test_orphan_upload_recovers_without_new_market_capture(drive):
    r = report()
    drive.put('orphan', archive.encode(r), r['sample_id'], 'data', 'parquet')
    assert archive.resume(drive, r['sample_id'], r['policy_hash'])['rows'] == 3
    assert len(drive.files) == 2


def test_same_slot_different_payload_is_not_overwritten(drive):
    r = report()
    archive.publish(drive, r)
    r['rows'][0]['bid'] = 200
    with pytest.raises(core.CaptureError, match='CHECKSUM_CONFLICT'):
        archive.publish(drive, r)


def test_tampered_analytical_column_and_identity_rejected():
    r = report()
    data = archive.encode(r)
    table = pq.read_table(io.BytesIO(data))
    idx = table.schema.get_field_index('bid')
    table = table.set_column(idx, table.schema.field(idx), pa.array(['999']*3))
    sink = io.BytesIO()
    pq.write_table(table, sink)
    with pytest.raises(core.CaptureError, match='COLUMN_MISMATCH'):
        archive.verify(sink.getvalue(), r['sample_id'], r['policy_hash'])
    with pytest.raises(core.CaptureError, match='IDENTITY_MISMATCH'):
        archive.verify(data, '0'*64, r['policy_hash'])


def test_tampered_manifest_fails_daily_audit(drive):
    r = report()
    archive.publish(drive, r)
    ident = drive.keys[r['sample_id'], 'manifest']
    bad = json.loads(drive.files[ident])
    bad['rows'] = 0
    drive.files[ident] = core.canonical(bad)
    with pytest.raises(core.CaptureError, match='MANIFEST_VERIFICATION_FAILED'):
        archive.inspect_sample(drive, r['sample_id'], r['policy_hash'])


def test_preview_never_authenticates_or_calls_network(monkeypatch, capsys):
    monkeypatch.delenv('OPTION_CAPTURE_UNDERLYINGS_JSON', raising=False)
    monkeypatch.setattr(job, 'DriveArchive', Mock(side_effect=AssertionError('network')))
    assert job.main(['--preview']) == 0
    assert json.loads(capsys.readouterr().out)['network_calls'] == 0


def setup_job(monkeypatch, drive):
    for key, value in {'OPTION_CAPTURE_ENABLED': 'true', 'OPTION_CAPTURE_LICENSE_ACK': 'true',
                       'OPTION_CAPTURE_TOKEN_EXPIRES_AT': '2027-01-01T00:00:00Z',
                       'UPSTOX_ANALYTICS_TOKEN': 'SECRET-ACCESS-TOKEN',
                       'OPTION_CAPTURE_UNDERLYINGS_JSON': json.dumps([SPOT])}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(job, 'now', lambda: NOW)
    monkeypatch.setattr(job, 'credentials', lambda value: object())
    monkeypatch.setattr(job, 'DriveArchive', lambda *a: drive)


@pytest.mark.parametrize('failure', ['expired', 'missing', 'provider', 'cleanup'])
def test_secrets_never_printed_and_auth_is_explicit(monkeypatch, capsys, drive, failure):
    setup_job(monkeypatch, drive)
    if failure == 'expired':
        monkeypatch.setenv('OPTION_CAPTURE_TOKEN_EXPIRES_AT', '2020-01-01T00:00:00Z')
    elif failure == 'missing':
        monkeypatch.delenv('UPSTOX_ANALYTICS_TOKEN')
    monkeypatch.setattr(job, 'acquire', Mock(side_effect=RuntimeError('SECRET-ACCESS-TOKEN raw credential JSON')))
    if failure == 'cleanup':
        monkeypatch.setattr(drive, 'close', Mock(side_effect=RuntimeError('SECRET-ACCESS-TOKEN')))
    assert job.main(['--slot', '1015']) == 1
    output = capsys.readouterr()
    assert 'SECRET' not in output.out+output.err
    assert json.loads(output.out)['status'] == ('AUTH_REQUIRED' if failure in {'expired', 'missing'} else 'CAPTURE_FAILED')
    assert json.loads(output.out)['health_record_verified'] is True


def test_closed_market_records_skip_without_downloading_master():
    reader = Mock()
    reader.get.return_value = {'status': 'CLOSED'}
    assert job.acquire(reader, CONFIG, NOW.date())['status'] == 'SKIPPED_CLOSED'
    reader.master.assert_not_called()


def test_endpoint_allowlist_and_signed_url_restrictions():
    reader = job.MarketReader('SECRET', Mock())
    with pytest.raises(core.CaptureError, match='FORBIDDEN_ENDPOINT'):
        reader.get('/v2/order/place')
    reader.session.get.assert_not_called()
    for url in ('http://api.upstox.com/x', 'wss://evil.com/x', 'wss://user:pass@api.upstox.com/x'):
        with pytest.raises(core.CaptureError):
            job.websocket_url(url)


def test_real_protobuf_decode_and_tls_verification(monkeypatch):
    import websocket
    from google.protobuf.json_format import ParseDict
    from upstox_client.feeder.proto.MarketDataFeedV3_pb2 import FeedResponse
    packet = ParseDict(message(), FeedResponse()).SerializeToString()
    connection = Mock()
    connection.getstatus.return_value = 101
    connection.recv.return_value = packet
    connect = Mock(return_value=connection)
    monkeypatch.setattr(websocket, 'create_connection', connect)
    monkeypatch.setattr(job, 'now', lambda: NOW)
    reader = Mock()
    reader.get.return_value = {'authorized_redirect_uri': 'wss://feed.upstox.com/signed'}
    assert job.capture(reader, selected(), CONFIG)['status'] == 'CAPTURED'
    assert connect.call_args.kwargs['sslopt'] == {'cert_reqs': ssl.CERT_REQUIRED, 'check_hostname': True}
    connection.close.assert_called_once()


def test_audit_flags_absent_slots_without_broker_access(monkeypatch, capsys, drive):
    setup_job(monkeypatch, drive)
    monkeypatch.setattr(job, 'acquire', Mock(side_effect=AssertionError('broker access')))
    assert job.main(['--audit-today']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'DAY_INCOMPLETE'


def test_after_slot_retry_repairs_manifest_but_cannot_capture_new_data(monkeypatch, capsys, drive):
    setup_job(monkeypatch, drive)
    r = report()
    drive.put('orphan', archive.encode(r), r['sample_id'], 'data', 'parquet')
    monkeypatch.setattr(job, 'now', lambda: NOW+timedelta(hours=2))
    acquire = Mock(side_effect=AssertionError('no later capture'))
    monkeypatch.setattr(job, 'acquire', acquire)
    assert job.main(['--slot', '1015']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'ALREADY_VERIFIED'
    drive.files.clear()
    drive.keys.clear()
    assert job.main(['--slot', '1015']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'MISSED_SLOT'
    acquire.assert_not_called()


def test_stream_disconnect_preserves_partial_without_leaking_signed_url(monkeypatch):
    import websocket
    connection = Mock()
    connection.getstatus.return_value = 101
    connection.recv.side_effect = RuntimeError('SECRET signed URL')
    monkeypatch.setattr(websocket, 'create_connection', Mock(return_value=connection))
    monkeypatch.setattr(job, 'now', lambda: NOW)
    reader = Mock()
    reader.get.return_value = {'authorized_redirect_uri': 'wss://feed.upstox.com/signed'}
    result = job.capture(reader, selected(), CONFIG)
    assert result['status'] == 'PARTIAL' and result['transport_status'] == 'STREAM_FAILED'
    assert 'SECRET' not in core.canonical(result).decode()
    connection.close.assert_called_once()


@pytest.mark.parametrize('seconds,quality,eligible', [(0, 'ON_TIME', True), (60, 'ON_TIME', True),
    (61, 'DELAYED', False), (599, 'DELAYED', False), (601, 'OUTSIDE_WINDOW', False)])
def test_timing_strata_never_relabel_delayed_capture(seconds, quality, eligible):
    r = report()
    r['captured_at'] = (NOW+timedelta(seconds=seconds)).isoformat()
    result = core.timing_evidence(r, NOW.date(), '1015')
    assert result['timing_quality'] == quality
    assert result['same_time_comparison_eligible'] is eligible
    assert result['capture_delay_seconds'] == seconds


def test_forged_timing_metadata_is_rejected():
    r = report()
    r['captured_at'] = (NOW+timedelta(minutes=3)).isoformat()
    with pytest.raises(core.CaptureError, match='TIMING_MISMATCH'):
        archive.verify(archive.encode(r), r['sample_id'], r['policy_hash'])


def test_legacy_files_are_not_assumed_timing_eligible(drive):
    r = report()
    for key in core.timing_evidence(r, NOW.date(), '1015'):
        del r[key]
    archive.publish(drive, r)
    result = archive.inspect_sample(drive, r['sample_id'], r['policy_hash'], details=True)
    assert result['timing_quality'] == 'UNVERIFIED'
    assert result['same_time_comparison_eligible'] is False


def test_early_wait_does_not_capture_before_target(monkeypatch):
    readings = iter([NOW-timedelta(seconds=2), NOW-timedelta(seconds=1), NOW])
    monkeypatch.setattr(job, 'now', lambda: next(readings))
    sleep = Mock()
    monkeypatch.setattr(job.time, 'sleep', sleep)
    job.wait_for_slot('1015')
    assert sleep.call_count == 2
    monkeypatch.setattr(job, 'now', lambda: NOW-timedelta(minutes=11))
    with pytest.raises(core.CaptureError, match='OUTSIDE_EARLY_START_WINDOW'):
        job.wait_for_slot('1015')


def test_delayed_completed_day_is_flagged_not_silently_aligned(monkeypatch, capsys, drive):
    setup_job(monkeypatch, drive)
    monkeypatch.setattr(job, 'inspect_sample', lambda *a, **kw:
                        dict(status='CAPTURED', same_time_comparison_eligible=False, timing_quality='DELAYED'))
    assert job.main(['--audit-today']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'DAY_INCOMPLETE'


def test_workflow_is_disabled_by_default_and_has_no_database_secret():
    root = Path(__file__).resolve().parents[1]
    text = (root/'.github/workflows/option-research-capture.yml').read_text()
    assert "vars.OPTION_CAPTURE_ENABLED == 'true'" in text
    assert 'default: preview' in text and 'cancel-in-progress: false' in text
    assert 'DATABASE_URL' not in text and 'contents: read' in text
    assert 'upload-artifact' not in text and '--audit-today' in text
    for script in text.split("python - <<'PY'\n")[1:]:
        assert '${{' not in script.split('          PY', 1)[0]
    for name in ('option_capture.py', 'option_capture_archive.py', 'option_capture_job.py'):
        source = (root/name).read_text()
        assert 'import app' not in source and 'import derivative_preflight' not in source
