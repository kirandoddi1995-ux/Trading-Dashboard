import datetime as dt
from concurrent.futures import Future

import pytest

import equity_runtime_health as health

NOW = dt.datetime(2026, 9, 13, 5, tzinfo=dt.timezone.utc)


def measured(**changes):
    return {"status": "MEASURED", "source": "fixture", "measured_at": NOW.isoformat(),
            "offset_seconds": 0.0, "uncertainty_seconds": .01, **changes}


def recovered(**changes):
    return {"status": "PASS", "observed_at": NOW.isoformat(), "ledger_valid": True,
            "events_checked": 1, "checkpoint": {"status": "PASS"},
            "outbox": {"pending": 0, "oldest_pending_seconds": 0}, **changes}


@pytest.mark.parametrize("evidence,code", [
    (None, "UNAVAILABLE"), ({"status": "UNAVAILABLE"}, "UNAVAILABLE"),
    (measured(measured_at=(NOW - dt.timedelta(seconds=61)).isoformat()), "STALE"),
    (measured(measured_at=(NOW + dt.timedelta(seconds=1)).isoformat()), "STALE"),
    (measured(measured_at="bad"), "INVALID"),
    (measured(offset_seconds=float('nan')), "INVALID"),
    (measured(uncertainty_seconds=-1), "INVALID"),
    (measured(offset_seconds=.24, uncertainty_seconds=.02), "EXCESSIVE"),
    (measured(offset_seconds=-.3), "EXCESSIVE"),
])
def test_clock_missing_invalid_stale_and_uncertain_fail(evidence, code):
    assert code in health.clock_error(evidence, now=NOW, maximum_offset=.25)


def test_real_zero_is_valid_not_a_default():
    assert health.clock_error(measured(), now=NOW, maximum_offset=.25) is None
    missing = measured()
    del missing['offset_seconds']
    assert health.clock_error(missing, now=NOW, maximum_offset=.25)


def packet_fixture():
    t1 = NOW.timestamp()
    packet = bytearray(48)
    packet[0], packet[1] = 0x24, 2
    origin = health._stamp(t1)
    packet[24:32] = origin
    packet[32:40] = health._stamp(t1 + .03)
    packet[40:48] = health._stamp(t1 + .04)
    return packet, origin, t1


def test_ntp_arithmetic_uses_four_real_timestamps_and_uncertainty():
    packet, origin, t1 = packet_fixture()
    result = health.decode_measurement(packet, origin, t1, t1 + .05, .05, 'fixture')
    assert result['offset_seconds'] == pytest.approx(.01, abs=1e-6)
    assert result['uncertainty_seconds'] == pytest.approx(.02, abs=1e-6)


@pytest.mark.parametrize("kind", ['origin', 'unsynchronized', 'mode', 'stratum', 'short', 'wall_jump'])
def test_ntp_rejects_invalid_responses(kind):
    packet, origin, t1 = packet_fixture()
    if kind == 'origin': packet[24:32] = bytes(8)
    if kind == 'unsynchronized': packet[0] |= 0xc0
    if kind == 'mode': packet[0] = 0x23
    if kind == 'stratum': packet[1] = 0
    if kind == 'short': packet = packet[:30]
    with pytest.raises(ValueError):
        health.decode_measurement(packet, origin, t1, t1 + .05,
                                  1 if kind == 'wall_jump' else .05, 'fixture')


def test_probe_socket_flow(monkeypatch):
    packet, origin, t1 = packet_fixture()
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def settimeout(self, value): assert value == 2
        def connect(self, address): assert address == ('fixture', 123)
        def send(self, request): assert request[40:48] == origin
        def recv(self, size): return packet
    monkeypatch.setattr(health.socket, 'socket', lambda *a: Socket())
    values = iter([t1, t1 + .05])
    ticks = iter([10., 10.05])
    monkeypatch.setattr(health.time, 'time', lambda: next(values))
    monkeypatch.setattr(health.time, 'monotonic', lambda: next(ticks))
    assert health._probe('fixture')['status'] == 'MEASURED'


@pytest.mark.parametrize('failure', [OSError('password=DO_NOT_PRINT'), TimeoutError('private')])
def test_probe_failure_redacted(monkeypatch, failure):
    future = Future()
    future.set_exception(failure)
    class Pool:
        def submit(self, *a): return future
    monkeypatch.setattr(health, '_pool', Pool())
    monkeypatch.setattr(health, '_pending', None)
    result = health.measure_clock()
    assert result['status'] == 'UNAVAILABLE'
    assert 'private' not in str(result) and 'DO_NOT_PRINT' not in str(result)


def test_busy_probe_does_not_launch_unbounded_threads(monkeypatch):
    monkeypatch.setattr(health, '_pending', Future())
    assert health.measure_clock()['reason'] == 'CLOCK_PROBE_BUSY'


@pytest.mark.parametrize('evidence', [None, recovered(status='UNAVAILABLE'),
    recovered(ledger_valid=False), recovered(events_checked=0),
    recovered(checkpoint={}), recovered(outbox={}),
    recovered(observed_at=(NOW - dt.timedelta(seconds=61)).isoformat())])
def test_recovery_is_fail_closed(evidence):
    assert health.recovery_error(evidence, now=NOW)


def test_recovery_builder_requires_actual_readback_and_existing_ledger():
    class Repo:
        def recovery_health(self): return {'status': 'PASS'}
    class Ledger:
        def verify(self): return {'valid': True, 'events_checked': 1}
        def outbox_stats(self): return {'pending': 0, 'oldest_pending_seconds': 0}
    result = health.recovery_health(Repo(), Ledger())
    assert health.recovery_error(result, now=dt.datetime.now(dt.timezone.utc)) is None
    assert health.recovery_health(None, Ledger())['status'] == 'UNAVAILABLE'


def test_release_changes_detected_and_line_endings_normalized(tmp_path):
    source = tmp_path / 'app.py'
    source.write_bytes(b'x = 1\r\n')
    first = health.release_fingerprint(tmp_path, names=('app.py',))
    source.write_bytes(b'x = 1\n')
    assert health.release_fingerprint(tmp_path, names=('app.py',)) == first
    source.write_bytes(b'x = 2\n')
    assert health.release_fingerprint(tmp_path, names=('app.py',)) != first
    (tmp_path / 'new_module.py').write_text('x = 3')
    assert health.release_fingerprint(tmp_path, names=('app.py', 'new_module.py')) != first
    with pytest.raises(ValueError, match='unavailable'):
        health.release_fingerprint(tmp_path)
