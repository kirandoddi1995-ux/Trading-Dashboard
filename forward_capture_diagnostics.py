"""Redacted capture diagnostics; import never reads credentials or connects."""
from __future__ import annotations

import sys
from typing import Any

from drive_archive import ArchiveError
from research_integrity import IntegrityError


def failure_category(error: Exception) -> str:
    """Return fixed diagnostics only; never serialize provider bodies or messages."""
    from google.auth.exceptions import RefreshError, TransportError
    from requests.exceptions import ConnectionError, SSLError, Timeout
    if isinstance(error, RefreshError):
        return 'DRIVE_AUTH_REFRESH_FAILED'
    if isinstance(error, SSLError):
        return 'TLS_FAILED'
    if isinstance(error, Timeout):
        return 'TRANSPORT_TIMEOUT'
    if isinstance(error, (ConnectionError, TransportError)):
        return 'TRANSPORT_FAILED'
    if isinstance(error, ArchiveError):
        code = str(error)
        if code in {'INVALID_OAUTH_CONFIGURATION', 'INVALID_DRIVE_FOLDER',
                    'DRIVE_FOLDER_NOT_WRITABLE', 'DUPLICATE_DRIVE_BATCH_REVIEW_REQUIRED',
                    'REMOTE_ARCHIVE_TOO_LARGE', 'DRIVE_HTTP_401', 'DRIVE_HTTP_403',
                    'DRIVE_HTTP_404', 'DRIVE_HTTP_429', 'DRIVE_HTTP_500',
                    'DRIVE_HTTP_502', 'DRIVE_HTTP_503', 'DRIVE_HTTP_504'}:
            return code
    if isinstance(error, IntegrityError) and str(error) in {
            'FORWARD_REMOTE_VERIFICATION_FAILED', 'FORWARD_MANIFEST_VERIFICATION_FAILED',
            'FORWARD_ARCHIVE_SIZE_INVALID', 'FORWARD_ARCHIVE_EXPANSION_EXCEEDED',
            'FORWARD_ARCHIVE_IDENTITY_INVALID', 'FORWARD_ARCHIVE_PREFIX_MISMATCH'}:
        return str(error)
    return 'UNCLASSIFIED_FAILURE'


def close_drive(drive: Any) -> None:
    """Preserve an active primary failure if transport cleanup also fails."""
    primary_failed = sys.exc_info()[0] is not None
    try:
        drive.close()
    except Exception:
        if not primary_failed:
            raise
