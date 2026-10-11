"""Hidden-label folder comparison and owner-confirmed read-only Drive checks."""
from __future__ import annotations

import argparse
import getpass
import hmac
import json
import re
import sys
from typing import Any, Callable, cast

from drive_archive import DriveArchive, credentials
from forward_capture_diagnostics import close_drive, failure_category
from forward_windows_credentials import read_secret
from research_integrity import IntegrityError

LABELS = ('A', 'B', 'C')


def folder_id(value: str) -> str:
    """Accept only a bounded ID, not a URL, whitespace, control text or a name."""
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value) is None:
        raise IntegrityError('FOLDER_COMPARISON_INPUT_INVALID')
    return value


def main(argv: list[str] | None = None) -> int:
    """No writes; candidate IDs enter hidden prompts, never argv or output."""
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--compare', action='store_true')
    modes.add_argument('--check-candidate', choices=LABELS)
    args = parser.parse_args(argv)
    if not args.compare and args.check_candidate is None:
        print(json.dumps({'status': 'PREVIEW', 'credential_reads': 0, 'network_calls': 0,
                          'writes': 0, 'approval_authority': False}))
        return 0
    stage = 'HIDDEN_INPUT'
    try:
        if not sys.stdin.isatty():
            raise IntegrityError('INTERACTIVE_PRIVATE_PROMPT_REQUIRED')
        if args.compare:
            candidates = {label: folder_id(getpass.getpass('Folder ' + label + ' ID (hidden): '))
                          for label in LABELS}
            if len(set(candidates.values())) != len(LABELS):
                raise IntegrityError('FOLDER_COMPARISON_INPUT_INVALID')
            stage = 'PRIVATE_FOLDER_READ'
            stored = folder_id(read_secret('OPTION_CAPTURE_DRIVE_FOLDER_ID'))
            matches = [label for label, candidate in candidates.items()
                       if hmac.compare_digest(stored, candidate)]
            print(json.dumps({'status': 'FOLDER_COMPARISON_COMPLETE',
                              'stored_folder_match': matches[0] if matches else 'NONE',
                              'credential_reads': 1, 'network_calls': 0, 'writes': 0,
                              'approval_authority': False}))
            return 0
        candidate = folder_id(getpass.getpass('Folder ' + args.check_candidate + ' ID (hidden): '))
        stage = 'PRIVATE_OAUTH_READ'
        info = json.loads(read_secret('DRIVE_OAUTH_TOKEN_JSON'))
        stage = 'DRIVE_CONFIGURATION'
        configure: Callable[[Any], Any] = credentials
        oauth = configure(info)
        drive = cast(Callable[..., Any], DriveArchive)(oauth, candidate)
        try:
            stage = 'DRIVE_FOLDER_CHECK'
            drive.check_folder()
            stage = 'DRIVE_CLOSE'
        finally:
            close_drive(drive)
        print(json.dumps({'status': 'CANDIDATE_FOLDER_CHECK_PASSED',
                          'candidate': args.check_candidate, 'credential_type': 'AUTHORIZED_USER',
                          'writes': 0, 'market_network_calls': 0,
                          'remote_bundle_verified': False, 'approval_authority': False}))
        return 0
    except Exception as error:
        category = failure_category(error)
        if isinstance(error, IntegrityError) and str(error) in {
                'INTERACTIVE_PRIVATE_PROMPT_REQUIRED', 'FOLDER_COMPARISON_INPUT_INVALID'}:
            category = str(error)
        print(json.dumps({'status': 'BLOCKED', 'stage': stage, 'category': category,
                          'candidate': args.check_candidate, 'writes': 0,
                          'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
