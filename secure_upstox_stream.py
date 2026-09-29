"""Application-owned TLS boundary around the pinned SDK's V3 protocol helpers.

Never call the SDK feeder's connect(): 2.29.0 disables certificate verification.
No global monkeypatch, insecure retry, broker I/O at import, or credential logging.
"""
import ssl
import threading
from urllib.parse import urlsplit

import requests
import websocket
from upstox_client.feeder.market_data_feeder_v3 import MarketDataFeederV3
from upstox_client.feeder.market_data_streamer_v3 import MarketDataStreamerV3


class StreamSecurityError(RuntimeError):
    pass


def safe_error(error):
    # Inspect only for classification. Never propagate provider text/URLs/headers.
    if isinstance(error, (ssl.SSLError, requests.exceptions.SSLError)):
        return 'TLS_VERIFICATION_FAILED'
    status = getattr(error, 'status_code', None)
    if status in (401, 403):
        return 'AUTH_REQUIRED'
    if type(error) is StreamSecurityError:
        return str(error)
    return 'STREAM_CONNECTION_FAILED'


def authorized_url(token):
    if not isinstance(token, str) or not token.strip():
        raise StreamSecurityError('AUTH_REQUIRED')
    try:
        with requests.get('https://api.upstox.com/v3/feed/market-data-feed/authorize',
                headers={'Authorization': 'Bearer '+token, 'Accept': 'application/json'},
                timeout=(5, 15), verify=True, allow_redirects=False, stream=True) as response:
            if response.status_code in (401, 403):
                raise StreamSecurityError('AUTH_REQUIRED')
            if response.status_code != 200:
                raise StreamSecurityError('STREAM_AUTHORIZATION_FAILED')
            raw = bytearray()
            for chunk in response.iter_content(4096):
                raw.extend(chunk)
                if len(raw) > 65536:
                    raise StreamSecurityError('STREAM_AUTHORIZATION_FAILED')
            import json
            body = json.loads(raw)
            if body.get('status') != 'success':
                raise StreamSecurityError('STREAM_AUTHORIZATION_FAILED')
            url = body['data']['authorized_redirect_uri']
            parsed = urlsplit(url)
            if (parsed.scheme != 'wss' or not parsed.hostname or not parsed.hostname.endswith('.upstox.com')
                    or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
                raise StreamSecurityError('UNTRUSTED_FEED_ENDPOINT')
            return url
    except Exception as exc:
        raise StreamSecurityError(safe_error(exc)) from None


class VerifiedFeeder(MarketDataFeederV3):
    def connect(self):
        if self.ws and self.ws.sock:
            return
        self._stop = threading.Event()
        url = authorized_url(self.api_client.configuration.access_token)
        # Authorization occurred over verified HTTPS. No bearer header is sent
        # to the signed WebSocket URL; redirects are rejected, not followed.

        def run():
            try:
                self.ws = websocket.create_connection(url, timeout=5, redirect_limit=0,
                    sslopt={'cert_reqs': ssl.CERT_REQUIRED, 'check_hostname': True})
                if self.ws.getstatus() != 101:
                    raise StreamSecurityError('STREAM_HANDSHAKE_REJECTED')
                if not self._stop.is_set() and self.on_open:
                    self.on_open(self.ws)
                while not self._stop.is_set():
                    try:
                        opcode, payload = self.ws.recv_data()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if opcode == websocket.ABNF.OPCODE_CLOSE:
                        break
                    if opcode != websocket.ABNF.OPCODE_BINARY:
                        raise StreamSecurityError('STREAM_DECODE_FAILED')
                    if self.on_message:
                        self.on_message(self.ws, payload)
            except Exception as exc:
                if not self._stop.is_set() and self.on_error:
                    self.on_error(self.ws, StreamSecurityError(safe_error(exc)))
            finally:
                if self.ws:
                    try:
                        self.ws.close()
                    except Exception:
                        pass
                if self.on_close:
                    self.on_close(self.ws, None, None)

        self.connection_thread = threading.Thread(target=run, name='verified-upstox-feed', daemon=True)
        self.connection_thread.start()

    def disconnect(self):
        self._stop.set()
        if self.ws:
            self.ws.close(status=1000)


class VerifiedMarketDataStreamer(MarketDataStreamerV3):
    def __init__(self, api_client):
        super().__init__(api_client)
        # The application's backoff owns reconnects, including auth failures.
        self.enable_auto_reconnect = False

    def connect(self):
        self.feeder = VerifiedFeeder(api_client=self.api_client, instrumentKeys=self.instrumentKeys,
            mode=self.mode, on_open=self.handle_open, on_message=self.handle_message,
            on_error=self.handle_error, on_close=self.handle_close)
        self.feeder.connect()

    def handle_error(self, ws, error):
        self.emit(self.Event['ERROR'], safe_error(error))

    def handle_close(self, ws, close_status_code, close_msg):
        self.emit(self.Event['CLOSE'], close_status_code, None)

    def handle_message(self, ws, message):
        try:
            super().handle_message(ws, message)
        except Exception:
            self.emit(self.Event['ERROR'], 'STREAM_DECODE_FAILED')
            if self.feeder:
                self.feeder.disconnect()
