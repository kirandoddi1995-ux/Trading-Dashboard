"""One-time Windows/local Desktop OAuth consent. Never run in CI or Streamlit.

Install requirements-archive.txt, download a Desktop OAuth client to
client_secret.json, then run: python authorize_drive.py
"""
from __future__ import annotations

import base64
import csv
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

import requests
from google.auth.transport.requests import AuthorizedSession

from drive_archive import API, ArchiveError, SCOPE, TOKEN_URI, credentials


def save_private_token(path, token):
    """Refuse overwrite; restrict ACL BEFORE writing secret bytes on Windows."""
    path = Path(path)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        if os.name == 'nt':
            result = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'],
                                    capture_output=True, text=True, check=True)
            sid = next(csv.reader(io.StringIO(result.stdout.strip())))[1]
            subprocess.run(['icacls', str(path.resolve()), '/inheritance:r',
                            '/grant:r', f'*{sid}:(F)'],
                           capture_output=True, text=True, check=True)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            descriptor = None
            json.dump(token, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        path.unlink(missing_ok=True)  # Only the new, incomplete token file.
        raise


def get_authorization_code(client_id, state, verifier):
    received = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Callback URLs contain authorization codes: never log them.

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            valid = (parsed.path == '/oauth2callback'
                     and len(query.get('state', [])) == 1
                     and secrets.compare_digest(query['state'][0], state))
            if valid:
                received['code'] = query.get('code', [None])[0]
                received['error'] = bool(query.get('error'))
            self.send_response(200 if valid else 400)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b'You may close this tab and return to the authorization script.'
                             if valid else b'Invalid authorization callback.')

    class LoopbackServer(HTTPServer):
        def get_request(self):
            sock, address = super().get_request()
            sock.settimeout(5)
            return sock, address

        def handle_error(self, *_args):
            pass  # Do not print requests or error bodies.

    with LoopbackServer(('127.0.0.1', 0), Callback) as server:
        redirect = f'http://127.0.0.1:{server.server_port}/oauth2callback'
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': client_id, 'redirect_uri': redirect, 'response_type': 'code',
            'scope': SCOPE, 'state': state, 'access_type': 'offline',
            'prompt': 'consent select_account', 'code_challenge': challenge,
            'code_challenge_method': 'S256',
        })
        print('Opening Google consent. Choose the dedicated archive Gmail account.')
        if not webbrowser.open(url, new=1):
            raise ArchiveError('BROWSER_DID_NOT_OPEN')
        server.timeout = 1
        deadline = time.monotonic() + 600
        while not received and time.monotonic() < deadline:
            server.handle_request()
        if received.get('error') or not received.get('code'):
            raise ArchiveError('CONSENT_DENIED_OR_TIMED_OUT')
        return received['code'], redirect


def main():
    try:
        if Path('token.json').exists():
            raise ArchiveError('TOKEN_FILE_EXISTS_MOVE_IT_PRIVATELY_BEFORE_REAUTHORIZING')
        client = json.loads(Path('client_secret.json').read_text(encoding='utf-8'))['installed']
        if not client.get('client_id') or not client.get('client_secret'):
            raise ArchiveError('DESKTOP_OAUTH_CLIENT_REQUIRED')
        print('Before proceeding: enable Drive API and publish the OAuth app to Production.')
        print('Testing-mode refresh tokens for Drive expire after 7 days.')
        if input('Type YES when that setup is complete: ').strip() != 'YES':
            return 1
        verifier = secrets.token_urlsafe(64)
        code, redirect = get_authorization_code(client['client_id'], secrets.token_urlsafe(32), verifier)
        response = requests.post(TOKEN_URI, data={
            'client_id': client['client_id'], 'client_secret': client['client_secret'],
            'code': code, 'code_verifier': verifier, 'redirect_uri': redirect,
            'grant_type': 'authorization_code',
        }, timeout=(10, 60))
        if response.status_code != 200:
            raise ArchiveError('OAUTH_TOKEN_EXCHANGE_FAILED')
        result = response.json()
        if not result.get('refresh_token') or set(result.get('scope', '').split()) != {SCOPE}:
            raise ArchiveError('OFFLINE_TOKEN_OR_NARROW_SCOPE_MISSING')
        token = {'type': 'authorized_user', 'client_id': client['client_id'],
                 'client_secret': client['client_secret'], 'refresh_token': result['refresh_token'],
                 'token_uri': TOKEN_URI, 'scopes': [SCOPE]}
        # Creating the folder with this OAuth app makes it reachable with only
        # drive.file. A manually created folder would require Picker authorization.
        with AuthorizedSession(credentials(token)) as session:
            folder = session.post(API, params={'fields': 'id'}, json={
                'name': 'Trading Dashboard Verified Archives',
                'mimeType': 'application/vnd.google-apps.folder',
            }, timeout=(10, 60))
            if folder.status_code not in (200, 201):
                raise ArchiveError('ARCHIVE_FOLDER_CREATION_FAILED')
            token['archive_folder_id'] = folder.json()['id']
        save_private_token('token.json', token)
        print('Saved token.json with private file permissions. Never upload this file to GitHub.')
        print('Copy its FULL contents to the Actions secret DRIVE_OAUTH_TOKEN_JSON.')
        print('Copy archive_folder_id from that file to DRIVE_ARCHIVE_FOLDER_ID.')
        print('Keep client_secret.json and token.json in private, backed-up storage.')
        return 0
    except Exception as exc:
        print('Authorization failed: ' + (str(exc) if isinstance(exc, ArchiveError) else type(exc).__name__))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
