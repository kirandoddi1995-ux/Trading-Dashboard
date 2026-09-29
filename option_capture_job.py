"""Run once per research slot on any host. No DB/account/order APIs or import I/O."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
import ssl
import time
from urllib.parse import urlsplit
import uuid

import requests

from derivative_contracts import digest, stamp
from drive_archive import DriveArchive, credentials
from option_capture import (CaptureError, VERSION, IST, SLOTS, policy, check_slot,
                            select_contracts, sample_identity, SnapshotBuffer, canonical)
from option_capture_archive import publish, resume, inspect_sample

MASTER = 'https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz'
GET_PATHS = {'/v2/market/status/NSE', '/v2/market-quote/quotes', '/v3/feed/market-data-feed/authorize'}


def now():
    return datetime.now(timezone.utc)


class MarketReader:
    def __init__(self, token, session):
        self.token, self.session = token, session

    def get(self, path, params=None):
        if path not in GET_PATHS:
            raise CaptureError('FORBIDDEN_ENDPOINT')
        with self.session.get('https://api.upstox.com'+path,
                headers={'Authorization': 'Bearer '+self.token, 'Accept': 'application/json'},
                params=params, timeout=(5, 20), allow_redirects=False, stream=True) as response:
            if response.status_code in (401, 403):
                raise CaptureError('AUTH_REQUIRED')
            if response.status_code == 429:
                raise CaptureError('RATE_LIMITED')
            if response.status_code != 200:
                raise CaptureError('MARKET_DATA_UNAVAILABLE')
            raw = bounded(response, 8*1024*1024)
            body = json.loads(raw)
            if body.get('status') != 'success' or 'data' not in body:
                raise CaptureError('INVALID_MARKET_RESPONSE')
            return body['data']

    def master(self):
        # Never send broker Authorization to the public instrument-master host.
        with self.session.get(MASTER, timeout=(5, 30), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise CaptureError('MASTER_UNAVAILABLE')
            packed = bounded(response, 16*1024*1024)
        with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
            unpacked = stream.read(96*1024*1024+1)
        if len(unpacked) > 96*1024*1024:
            raise CaptureError('MASTER_SIZE_EXCEEDED')
        rows = json.loads(unpacked)
        if not isinstance(rows, list):
            raise CaptureError('MASTER_SCHEMA_INVALID')
        return rows, hashlib.sha256(packed).hexdigest()


def bounded(response, limit):
    data = bytearray()
    for chunk in response.iter_content(65536):
        data.extend(chunk)
        if len(data) > limit:
            raise CaptureError('RESPONSE_SIZE_EXCEEDED')
    return bytes(data)


def websocket_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'wss' or not parsed.hostname or not parsed.hostname.endswith('.upstox.com')
            or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise CaptureError('UNTRUSTED_FEED_ENDPOINT')
    return value


def capture(reader, selected, config):
    # Use the SDK protobuf definition ONLY. Its installed streamer sets CERT_NONE;
    # do not instantiate it. websocket-client verifies certificates + hostnames.
    import websocket
    from google.protobuf.json_format import MessageToDict
    from upstox_client.feeder.proto.MarketDataFeedV3_pb2 import FeedResponse

    authorized = reader.get('/v3/feed/market-data-feed/authorize')
    url = websocket_url(authorized['authorized_redirect_uri'])
    buffer = SnapshotBuffer(selected, config)
    start = time.monotonic()
    connection = websocket.create_connection(url, timeout=5,
        sslopt={'cert_reqs': ssl.CERT_REQUIRED, 'check_hostname': True})
    try:
        connection.send_binary(canonical(dict(guid=uuid.uuid4().hex, method='sub',
                                              data={'instrumentKeys': sorted(selected), 'mode': 'full'})))
        while time.monotonic()-start < config['collection_seconds']:
            try:
                packet = connection.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not isinstance(packet, bytes) or not packet or len(packet) > 2*1024*1024:
                raise CaptureError('INVALID_FEED_PACKET')
            message = MessageToDict(FeedResponse.FromString(packet))
            buffer.ingest(message, now())
            report = buffer.snapshot(now())
            if report['status'] == 'CAPTURED':
                return report
        return buffer.snapshot(now())
    except Exception:
        # Retain observed fields if a stream fails; never reconnect/merge epochs
        # or expose an exception containing the signed WebSocket URL.
        result = buffer.snapshot(now())
        result.update(status='PARTIAL', transport_status='STREAM_FAILED')
        return result
    finally:
        try:
            connection.close()
        except Exception:
            pass  # Never expose a signed URL through a transport cleanup error.


def acquire(reader, config, day):
    status = reader.get('/v2/market/status/NSE').get('status')
    if status in {'CLOSED', 'NORMAL_CLOSE', 'CLOSING_END'}:
        return dict(status='SKIPPED_CLOSED', captured_at=now().isoformat(), rows=[],
                    mode='RESEARCH_ONLY', approval_eligible=False, market_status=status)
    if status not in {'OPEN', 'NORMAL_OPEN'}:
        raise CaptureError('SESSION_UNVERIFIED')
    master, master_hash = reader.master()
    master_received = now().isoformat()
    data = reader.get('/v2/market-quote/quotes', {'instrument_key': ','.join(config['underlyings'])})
    references = {q.get('instrument_token'): q.get('last_price') for q in data.values()}
    selected, inventory = select_contracts(master, references, config, day)
    result = capture(reader, selected, config)
    return dict(result, selection=inventory, master_source=MASTER, master_sha256=master_hash,
                master_received_at=master_received, expiry_semantics='RAW_MASTER_DATE_NOT_EXERCISE_CUTOFF')


def failure_record(drive, sample_id, code):
    """Best effort independent failure receipt; a failed Drive write stays a failed job."""
    record = dict(format=VERSION, mode='RESEARCH_ONLY', approval_eligible=False,
                  sample_id=sample_id, status=code, recorded_at=now().isoformat())
    content = canonical(record)
    ident = hashlib.sha256(content).hexdigest()
    file_id = drive.put('option-capture-health-'+ident+'.json', content, ident, 'manifest', 'application/json')
    if drive.download(file_id) != content:
        raise CaptureError('HEALTH_RECORD_UNVERIFIED')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--slot', choices=sorted(SLOTS), default='1015')
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--audit-today', action='store_true')
    args = parser.parse_args(argv)
    drive, session, sample = None, None, None
    try:
        config = policy(json.loads(os.environ.get('OPTION_CAPTURE_UNDERLYINGS_JSON', '["NSE_INDEX|Nifty 50"]')))
        if args.preview:
            print(json.dumps(dict(status='PREVIEW', policy=config, network_calls=0)))
            return 0
        if os.environ.get('OPTION_CAPTURE_ENABLED') != 'true':
            raise CaptureError('CAPTURE_DISABLED')
        if os.environ.get('OPTION_CAPTURE_LICENSE_ACK') != 'true':
            raise CaptureError('LICENSE_ACK_REQUIRED')
        day = now().astimezone(IST).date()
        sample = None if args.audit_today else sample_identity(config, day, args.slot)
        drive = DriveArchive(credentials(json.loads(os.environ.get('DRIVE_OAUTH_TOKEN_JSON', '{}'))),
                             os.environ.get('OPTION_CAPTURE_DRIVE_FOLDER_ID', ''))
        drive.check_folder()
        if args.audit_today:
            results = {slot: inspect_sample(drive, sample_identity(config, day, slot), digest(config))
                       for slot in SLOTS}
            good = all(s in {'CAPTURED', 'SKIPPED_CLOSED'} for s in results.values())
            print(json.dumps(dict(status='DAY_COMPLETE' if good else 'DAY_INCOMPLETE', slots=results)))
            return 0 if good else 1
        previous = resume(drive, sample, digest(config))
        if previous:
            print(json.dumps(dict(status='ALREADY_VERIFIED', sample_id=sample, capture_status=previous['status'])))
            return 0 if previous['status'] in {'CAPTURED', 'SKIPPED_CLOSED'} else 1
        # Restore an existing upload after its slot, never capture a later cut.
        check_slot(now(), args.slot)
        token = os.environ.get('UPSTOX_ANALYTICS_TOKEN', '').strip()
        try:
            expiry = stamp(os.environ.get('OPTION_CAPTURE_TOKEN_EXPIRES_AT'))
        except ValueError:
            raise CaptureError('AUTH_REQUIRED') from None
        if not token or expiry <= now():
            raise CaptureError('AUTH_REQUIRED')
        session = requests.Session()
        report = acquire(MarketReader(token, session), config, day)
        # A delayed run never claims an on-time capture. Keep its record for audit.
        try:
            if check_slot(now(), args.slot) != day:
                raise CaptureError('MISSED_SLOT')
        except CaptureError:
            report['status'] = 'LATE_CAPTURE'
        report.update(format=VERSION, sample_id=sample, policy_hash=digest(config), policy=config,
                      trading_date=day.isoformat(), slot=args.slot,
                      token_days_remaining=max(0, (expiry-now()).days))
        manifest = publish(drive, report)
        print(json.dumps(dict(status=report['status'], rows=manifest['rows'], sample_id=sample,
                              sha256=manifest['sha256'], token_days_remaining=report['token_days_remaining'])))
        return 0 if report['status'] in {'CAPTURED', 'SKIPPED_CLOSED'} else 1
    except Exception as exc:
        code = str(exc) if type(exc) is CaptureError else 'CAPTURE_FAILED'
        # CaptureError only originates from fixed strings in our modules.
        persisted = False
        if drive and sample:
            try:
                failure_record(drive, sample, code)
                persisted = True
            except Exception:
                pass
        print(json.dumps(dict(status=code, health_record_verified=persisted)))
        return 1
    finally:
        for resource in (session, drive):
            if resource:
                try:
                    resource.close()
                except Exception:
                    pass  # Cleanup failures must not leak credential-bearing errors.


if __name__ == '__main__':
    raise SystemExit(main())
