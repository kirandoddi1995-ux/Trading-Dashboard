"""Opt-in official OI capture or explicit private context export. No import I/O."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from market_context import ContextError, MAX_BYTES


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='Offline configuration summary, no credential reads')
    parser.add_argument('--input', type=Path, help='Optional local context JSON; otherwise fetch today\'s official NSE OI')
    args = parser.parse_args(argv)
    if args.preview:
        print(json.dumps(dict(status='PREVIEW', mode='CONTEXT_ONLY', max_bytes=MAX_BYTES,
                              source='LOCAL_FILE' if args.input else 'OFFICIAL_NSE_PARTICIPANT_OI', database_writes=0)))
        return 0
    drive = None
    try:
        if (os.environ.get('MARKET_CONTEXT_ARCHIVE_ENABLED') != 'true'
                or os.environ.get('MARKET_CONTEXT_LICENSE_ACK') != 'true'):
            raise ContextError('CONTEXT_ARCHIVE_DISABLED_OR_LICENSE_UNCONFIRMED')
        from drive_archive import DriveArchive, credentials
        from market_context_archive import archive_context
        from market_context_sources import collect_participant_oi
        import requests
        folder = os.environ.get('MARKET_CONTEXT_DRIVE_FOLDER_ID', '').strip()
        if not folder:
            raise ContextError('CONTEXT_FOLDER_REQUIRED')
        creds = credentials(json.loads(os.environ.get('DRIVE_OAUTH_TOKEN_JSON', '{}')))
        if args.input:
            with args.input.open('rb') as stream:
                data = stream.read(MAX_BYTES+1)
            if len(data) > MAX_BYTES:
                raise ContextError('CONTEXT_ARCHIVE_TOO_LARGE')
            packet = json.loads(data)
        else:
            with requests.Session() as client:
                packet = collect_participant_oi(client, datetime.now(ZoneInfo('Asia/Kolkata')).date())
        drive = DriveArchive(creds, folder)
        print(json.dumps(archive_context(drive, packet)))
        return 0
    except Exception:
        # Neither HTTP response bodies nor credential/exception strings belong in CI logs.
        print(json.dumps(dict(status='CONTEXT_CAPTURE_FAILED', mode='CONTEXT_ONLY',
                             action='Check enablement, source availability/schema, OAuth and folder access; no database changes')))
        return 1
    finally:
        if drive is not None:
            drive.close()


if __name__ == '__main__':
    raise SystemExit(main())
