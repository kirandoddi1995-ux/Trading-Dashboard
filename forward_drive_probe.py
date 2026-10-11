"""Owner-run Drive folder check: offline preview, explicit read-only network check."""
from __future__ import annotations

import argparse
import json
from typing import Any, Callable, cast

from drive_archive import DriveArchive, credentials
from forward_capture_diagnostics import close_drive, failure_category
from forward_windows_credentials import read_secret


def main(argv: list[str] | None = None) -> int:
    """Use only two named OS credentials; never capture, upload or reveal values."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if not args.check:
        print(json.dumps({'status': 'PREVIEW', 'credential_reads': 0, 'network_calls': 0,
                          'writes': 0, 'approval_authority': False}))
        return 0
    stage = 'PRIVATE_CREDENTIAL_READ'
    try:
        info = json.loads(read_secret('DRIVE_OAUTH_TOKEN_JSON'))
        folder = read_secret('OPTION_CAPTURE_DRIVE_FOLDER_ID')
        stage = 'DRIVE_CONFIGURATION'
        configure_credentials: Callable[[Any], Any] = credentials
        oauth = configure_credentials(info)
        drive = cast(Callable[..., Any], DriveArchive)(oauth, folder)
        try:
            stage = 'DRIVE_FOLDER_CHECK'
            drive.check_folder()
            stage = 'DRIVE_CLOSE'
        finally:
            close_drive(drive)
        print(json.dumps({'status': 'DRIVE_FOLDER_CHECK_PASSED', 'writes': 0,
                          'market_network_calls': 0, 'remote_bundle_verified': False,
                          'approval_authority': False}))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'BLOCKED', 'stage': stage,
                          'category': failure_category(error), 'writes': 0,
                          'market_network_calls': 0, 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
