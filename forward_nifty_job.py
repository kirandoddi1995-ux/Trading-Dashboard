"""Portable one-poll research producer. Preview is offline; capture needs consent."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Any, Callable, cast
import uuid

from automated_development_checks import write_once
from drive_archive import DriveArchive, credentials
from equity_runtime_health import clock_error, measure_clock
from forward_nifty_archive import Drive, publish
from forward_nifty_producer import ROOT, Producer, prepare_config, validate_config
from research_input_archive import InputArchive
from research_integrity import IntegrityError
from research_replay_comparison import instant

URL = 'https://api.upstox.com/v3/historical-candle/intraday/NSE_INDEX%7CNifty%2050/minutes/5'


def read_current(session: Any, token: str) -> list[list[Any]]:
    """Only fixed current-day NIFTY GET; verified HTTPS, no redirect or orders."""
    with session.get(URL, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'},
                     timeout=(5, 20), allow_redirects=False, stream=True, verify=True) as response:
        if response.status_code in (401, 403):
            raise IntegrityError('AUTH_REQUIRED')
        if response.status_code != 200:
            raise IntegrityError('MARKET_DATA_UNAVAILABLE')
        raw = bytearray()
        for block in response.iter_content(65536):
            raw.extend(block)
            if len(raw) > 2 * 1024 * 1024:
                raise IntegrityError('RESPONSE_TOO_LARGE')
        body = json.loads(raw)
        if not isinstance(body, dict) or body.get('status') != 'success' or not isinstance(body.get('data'), dict):
            raise IntegrityError('MARKET_RESPONSE_INVALID')
        candles = body['data'].get('candles')
        if not isinstance(candles, list):
            raise IntegrityError('MARKET_RESPONSE_INVALID')
        return candles


def main(argv: list[str] | None = None) -> int:
    """Owner invokes each supervised poll; no cron, looping or automatic token refresh."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--state', required=True, type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--confirm-run', action='store_true')
    modes.add_argument('--prepare', action='store_true')
    modes.add_argument('--backup-only', action='store_true')
    parser.add_argument('--trading-date')
    parser.add_argument('--previous-close', type=float)
    parser.add_argument('--previous-close-source-sha256')
    args = parser.parse_args(argv)
    try:
        if any(path.resolve().is_relative_to(ROOT) for path in (args.config, args.state)):
            raise IntegrityError('PRIVATE_STATE_OUTSIDE_REPOSITORY_REQUIRED')
        if args.prepare:
            if not args.trading_date or args.previous_close is None or not args.previous_close_source_sha256:
                raise IntegrityError('PREPARATION_ARGUMENTS_REQUIRED')
            prepared = prepare_config(args.trading_date, args.previous_close, args.previous_close_source_sha256,
                                      datetime.now(timezone.utc).isoformat())
            args.config.parent.mkdir(parents=True, exist_ok=True)
            write_once(args.config, prepared)
            print(json.dumps({'status': 'CONFIG_PREPARED', 'network_calls': 0, 'approval_authority': False}))
            return 0
        config = json.loads(args.config.read_bytes())
        identity = validate_config(config, ROOT)
        if not args.confirm_run and not args.backup_only:
            print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'spec_hash': identity,
                              'approval_authority': False}))
            return 0
        if os.environ.get('FORWARD_CAPTURE_LICENSE_ACK') != 'true':
            raise IntegrityError('LICENSE_ACK_REQUIRED')
        if args.backup_only and not (args.state / 'observations.sqlite').is_file():
            raise IntegrityError('EXISTING_CAPTURE_STATE_REQUIRED')
        if args.backup_only:
            producer = Producer(config, args.state / 'observations.sqlite', InputArchive(args.state / 'inputs'))
            oauth = cast(Callable[[Any], Any], credentials)(json.loads(os.environ.get('DRIVE_OAUTH_TOKEN_JSON', '{}')))
            drive = cast(Callable[..., Any], DriveArchive)(oauth, os.environ.get('OPTION_CAPTURE_DRIVE_FOLDER_ID', ''))
            try:
                drive.check_folder()
                result = producer.bundle('BACKUP_ONLY', producer.context())
                acknowledgement = publish(cast(Drive, drive), result)
                write_once(args.state / ('receipt-' + uuid.uuid4().hex + '.json'), acknowledgement)
            finally:
                drive.close()
            print(json.dumps({'status': 'REMOTE_VERIFIED', 'capture_status': 'BACKUP_ONLY',
                              'recorded_decisions': result['recorded_decisions'],
                              'missing_decisions': result['missing_decisions'], 'approval_authority': False}))
            return 0
        token = os.environ.get('UPSTOX_ANALYTICS_TOKEN', '').strip()
        expiry = os.environ.get('FORWARD_TOKEN_EXPIRES_AT')
        now = datetime.now(timezone.utc)
        try:
            valid_expiry = expiry is not None and instant(expiry) > now
        except (ValueError, TypeError):
            valid_expiry = False
        if not token or not valid_expiry:
            raise IntegrityError('AUTH_REQUIRED')
        opening, closing = instant(config['session_open']), instant(config['session_close'])
        if not opening <= now <= closing + timedelta(minutes=15):
            raise IntegrityError('OUTSIDE_COLLECTION_SESSION')
        probe = cast(Callable[[], dict[str, Any]], measure_clock)()
        problem = cast(Callable[..., str | None], clock_error)(probe, now=datetime.now(timezone.utc), maximum_offset=1.0)
        if problem:
            raise IntegrityError('CLOCK_UNVERIFIED')
        producer = Producer(config, args.state / 'observations.sqlite', InputArchive(args.state / 'inputs'))
        # Validate credential config before collection; scope stays drive.file.
        oauth = cast(Callable[[Any], Any], credentials)(json.loads(os.environ.get('DRIVE_OAUTH_TOKEN_JSON', '{}')))
        drive = cast(Callable[..., Any], DriveArchive)(oauth, os.environ.get('OPTION_CAPTURE_DRIVE_FOLDER_ID', ''))
        import requests
        try:
            with requests.Session() as session:
                bars = read_current(session, token)
            result = producer.record_poll(bars, received_at=datetime.now(timezone.utc).isoformat(),
                                          computed_clock=lambda: datetime.now(timezone.utc))
            drive.check_folder()  # Inputs/journal already durable if Drive is down.
            acknowledgement = publish(cast(Drive, drive), result)
            write_once(args.state / ('receipt-' + uuid.uuid4().hex + '.json'), acknowledgement)
        finally:
            drive.close()
        print(json.dumps({'status': 'REMOTE_VERIFIED', 'capture_status': result['status'], 'recorded_decisions': result['recorded_decisions'],
                          'missing_decisions': result['missing_decisions'], 'approval_authority': False}))
        return 0
    except Exception as error:
        # No transport body, URL, token, private path or raw exception escapes.
        code = str(error) if isinstance(error, IntegrityError) and str(error) in {
            'AUTH_REQUIRED', 'CLOCK_UNVERIFIED', 'LICENSE_ACK_REQUIRED', 'OUTSIDE_COLLECTION_SESSION'} else 'FORWARD_CAPTURE_FAILED'
        if (args.confirm_run or args.backup_only) and not args.state.resolve().is_relative_to(ROOT):
            try:
                args.state.mkdir(parents=True, exist_ok=True)
                write_once(args.state / ('failure-' + uuid.uuid4().hex + '.json'),
                           {'status': 'BLOCKED', 'code': code, 'at': datetime.now(timezone.utc).isoformat(),
                            'approval_authority': False, 'fill_evidence': False})
            except Exception:
                pass  # Exit remains failed even if local failure receipt cannot commit.
        print(json.dumps({'status': 'BLOCKED', 'code': code, 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
