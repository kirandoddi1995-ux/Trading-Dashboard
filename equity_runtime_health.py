"""Equity-only measured runtime evidence. No credentials or raw errors in results."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import socket
import struct
import threading
import time
from equity_scan_profiling import call as profile_call

UTC = dt.timezone.utc
MAX_AGE_SECONDS = 60
_NTP_EPOCH = 2208988800
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="equity-clock")
_lock = threading.Lock()
_pending = None
RELEASE_FILES = (
    "app.py", "app_runtime.py", "live_governance.py", "live_evidence.py",
    "equity_runtime_health.py", "equity_runtime_evidence.py", "equity_execution_policy.py",
    "equity_manual_review.py", "equity_order_records.py", "equity_scan_repository.py",
    "equity_observation_capture.py", "continuous_evolution.py", "trade_contracts.py",
    "production_readiness.py", "resilience_control_plane.py", "quant_foundation.py",
    "calibration_artifacts.py", "model_registry.py", "artifact_security.py",
    "runtime_evidence_store.py", "evidence_ledger.py", "decision_evidence.py",
    "evidence_tiers.py", "point_in_time.py", "feature_store.py", "prediction_validation.py",
    "production_repository.py", "scan_jobs.py", "scanner_funnel.py", "technical_indicators.py",
    "equity_scan_profiling.py",
    "equity_evidence_delivery.py",
    "equity_checkpoint_delivery.py",
)


def release_fingerprint(root, *, names=RELEASE_FILES):
    """Hash the explicit decision/recovery source manifest, not local scratch files."""
    root = Path(root)
    digest = hashlib.sha256()
    paths = [root / name for name in sorted(names)]
    if not paths:
        raise ValueError("Release sources unavailable")
    for path in paths:
        if not path.is_file():
            raise ValueError("Required release source unavailable: " + path.name)
        # Windows upload and Linux checkout must identify the same source.
        data = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(path.name.encode() + b"\0" + data + b"\0")
    return digest.hexdigest()


def _stamp(value):
    seconds = value + _NTP_EPOCH
    return struct.pack("!II", int(seconds), int((seconds % 1) * 2**32))


def decode_measurement(packet, origin, t1, t4, elapsed, source):
    if len(packet) < 48 or packet[0] >> 6 == 3 or packet[0] & 7 != 4:
        raise ValueError("Invalid clock response")
    if (packet[0] >> 3) & 7 not in (3, 4) or not 1 <= packet[1] <= 15:
        raise ValueError("Unsynchronized clock response")
    if packet[24:32] != origin or abs((t4 - t1) - elapsed) > .01:
        raise ValueError("Clock exchange mismatch")
    def stamp_at(start):
        seconds, fraction = struct.unpack("!II", packet[start:start + 8])
        if not seconds:
            raise ValueError("Missing server timestamp")
        return seconds - _NTP_EPOCH + fraction / 2**32
    t2, t3 = stamp_at(32), stamp_at(40)
    delay = (t4 - t1) - (t3 - t2)
    if t3 < t2 or delay < -.001 or abs(t3 - t4) > 86400:
        raise ValueError("Invalid clock timing")
    root_delay = struct.unpack("!i", packet[4:8])[0] / 65536
    dispersion = struct.unpack("!I", packet[8:12])[0] / 65536
    return {"status": "MEASURED", "source": source,
            "measured_at": dt.datetime.fromtimestamp(t4, UTC).isoformat(),
            "offset_seconds": ((t2 - t1) + (t3 - t4)) / 2,
            "uncertainty_seconds": max(delay, 0) / 2 + max(root_delay, 0) / 2 + dispersion}


def _probe(host):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2)
        sock.connect((host, 123))
        t1, start = time.time(), time.monotonic()
        origin = _stamp(t1)
        sock.send(b"\x23" + bytes(39) + origin)
        packet = sock.recv(512)
        t4, elapsed = time.time(), time.monotonic() - start
    return decode_measurement(packet, origin, t1, t4, elapsed, host)


def measure_clock(host="time.cloudflare.com"):
    """Bound caller wait including DNS; a stuck probe cannot spawn more workers."""
    global _pending
    with _lock:
        if _pending is not None and not _pending.done():
            return {"status": "UNAVAILABLE", "reason": "CLOCK_PROBE_BUSY"}
        _pending = _pool.submit(_probe, host)
        future = _pending
    try:
        return future.result(timeout=3)
    except TimeoutError:
        return {"status": "UNAVAILABLE", "reason": "CLOCK_PROBE_TIMEOUT"}
    except Exception:
        return {"status": "UNAVAILABLE", "reason": "CLOCK_PROBE_FAILED"}


def clock_error(evidence, *, now, maximum_offset):
    try:
        if not evidence or evidence.get("status") != "MEASURED":
            return "CLOCK_MEASUREMENT_UNAVAILABLE"
        measured = dt.datetime.fromisoformat(evidence["measured_at"])
        if measured.tzinfo is None or not 0 <= (now - measured).total_seconds() <= MAX_AGE_SECONDS:
            return "CLOCK_MEASUREMENT_STALE"
        offset = float(evidence["offset_seconds"])
        uncertainty = float(evidence["uncertainty_seconds"])
        if not evidence.get("source") or not all(map(math.isfinite, (offset, uncertainty))) or uncertainty < 0:
            return "CLOCK_MEASUREMENT_INVALID"
        if abs(offset) + uncertainty > maximum_offset:
            return "CLOCK_OFFSET_OR_UNCERTAINTY_EXCESSIVE"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "CLOCK_MEASUREMENT_INVALID"
    return None


def recovery_health(repository, ledger):
    """Read existing state only. A first empty installation is not proven healthy."""
    try:
        checkpoint = profile_call("recovery_checkpoint_health", repository.recovery_health)
        integrity = profile_call("ledger_verification", ledger.verify)
        outbox = profile_call("ledger_outbox_health", ledger.outbox_stats)
        valid = (checkpoint.get("status") == "PASS" and integrity.get("valid") is True
                 and integrity.get("events_checked", 0) > 0)
        return {"status": "PASS" if valid else "UNAVAILABLE",
                "observed_at": dt.datetime.now(UTC).isoformat(),
                "checkpoint": checkpoint, "ledger_valid": integrity.get("valid"),
                "events_checked": integrity.get("events_checked"), "outbox": outbox}
    except Exception:
        return {"status": "UNAVAILABLE", "reason": "RECOVERY_STORAGE_CHECK_FAILED"}


def recovery_error(evidence, *, now):
    try:
        if not evidence or evidence.get("status") != "PASS":
            return "RECOVERY_HEALTH_UNAVAILABLE"
        at = dt.datetime.fromisoformat(evidence["observed_at"])
        if at.tzinfo is None or not 0 <= (now - at).total_seconds() <= MAX_AGE_SECONDS:
            return "RECOVERY_HEALTH_STALE"
        if evidence.get("ledger_valid") is not True or evidence.get("events_checked", 0) <= 0:
            return "RECOVERY_LEDGER_UNVERIFIED"
        if evidence.get("checkpoint", {}).get("status") != "PASS":
            return "RECOVERY_CHECKPOINT_UNVERIFIED"
        stats = evidence["outbox"]
        for key in ("pending", "oldest_pending_seconds"):
            value = float(stats[key])
            if not math.isfinite(value) or value < 0:
                return "RECOVERY_OUTBOX_INVALID"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "RECOVERY_HEALTH_INVALID"
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    report = {"EXPECTED_EQUITY_CODE_SHA256": release_fingerprint(root),
              "RESILIENCE_POLICY_SHA256": hashlib.sha256((root / "resilience_policy.json").read_bytes()).hexdigest()}
    if args.probe:
        report["clock"] = measure_clock()
        policy = json.loads((root / "resilience_policy.json").read_text())
        report["clock_check"] = clock_error(report["clock"], now=dt.datetime.now(UTC),
            maximum_offset=float(policy['clock']['maximum_ntp_offset_seconds'])) or "PASS"
    print(json.dumps(report, indent=2))
