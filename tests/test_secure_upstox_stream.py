"""TLS boundary tests use mocks and a local TLS endpoint only, never Upstox."""
import ast
from datetime import datetime, timedelta, timezone
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import threading
from unittest.mock import Mock

import pytest
import requests
import websocket
import upstox_client
import secure_upstox_stream as secure


def client():
    config = upstox_client.Configuration()
    config.access_token = 'SECRET-TOKEN'
    return upstox_client.ApiClient(config)


@pytest.mark.parametrize('url', ['ws://feed.upstox.com/x', 'wss://evil.example/x',
    'wss://upstox.com.evil.example/x', 'wss://user:pass@feed.upstox.com/x'])
def test_untrusted_signed_urls_rejected(monkeypatch, url):
    response = Mock(status_code=200)
    response.iter_content.return_value = [json.dumps({'status': 'success',
        'data': {'authorized_redirect_uri': url}}).encode()]
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(secure.requests, 'get', Mock(return_value=response))
    with pytest.raises(secure.StreamSecurityError, match='UNTRUSTED_FEED_ENDPOINT'):
        secure.authorized_url('SECRET-TOKEN')


@pytest.mark.parametrize('error,code', [(requests.exceptions.SSLError('SECRET-TOKEN'), 'TLS_VERIFICATION_FAILED'),
    (RuntimeError('SECRET-TOKEN signed URL'), 'STREAM_CONNECTION_FAILED')])
def test_authorization_fails_safely(monkeypatch, error, code):
    get = Mock(side_effect=error)
    monkeypatch.setattr(secure.requests, 'get', get)
    with pytest.raises(secure.StreamSecurityError) as raised:
        secure.authorized_url('SECRET-TOKEN')
    assert str(raised.value) == code
    assert get.call_args.kwargs['verify'] is True
    assert get.call_args.kwargs['allow_redirects'] is False


def test_verified_connection_protocol_and_no_bearer_forwarding(monkeypatch):
    monkeypatch.setattr(secure, 'authorized_url', lambda token: 'wss://feed.upstox.com/signed')
    conn = Mock()
    conn.getstatus.return_value = 101
    conn.recv_data.return_value = (websocket.ABNF.OPCODE_CLOSE, b'')
    connect = Mock(return_value=conn)
    monkeypatch.setattr(secure.websocket, 'create_connection', connect)
    stream = secure.VerifiedMarketDataStreamer(client())
    opened = Mock()
    stream.on('open', opened)
    stream.connect()
    stream.feeder.connection_thread.join(5)
    opened.assert_called_once()
    kwargs = connect.call_args.kwargs
    assert kwargs['sslopt'] == {'cert_reqs': ssl.CERT_REQUIRED, 'check_hostname': True}
    assert kwargs['redirect_limit'] == 0 and 'header' not in kwargs
    assert stream.enable_auto_reconnect is False
    stream.subscribe(['NSE_FO|1'], 'full')
    stream.change_mode(['NSE_FO|1'], 'ltpc')
    stream.unsubscribe(['NSE_FO|1'])
    assert [json.loads(c.args[0])['method'] for c in conn.send.call_args_list] == ['sub', 'change_mode', 'unsub']
    conn.close.assert_called_once()


def test_redirect_handshake_is_not_treated_as_open(monkeypatch):
    monkeypatch.setattr(secure, 'authorized_url', lambda token: 'wss://feed.upstox.com/signed')
    conn = Mock()
    conn.getstatus.return_value = 302
    monkeypatch.setattr(secure.websocket, 'create_connection', Mock(return_value=conn))
    stream = secure.VerifiedMarketDataStreamer(client())
    errors, opened = [], Mock()
    stream.on('error', errors.append)
    stream.on('open', opened)
    stream.connect()
    stream.feeder.connection_thread.join(5)
    assert errors == ['STREAM_HANDSHAKE_REJECTED']
    opened.assert_not_called()


@pytest.mark.parametrize('trusted_wrong_hostname', [False, True])
def test_actual_tls_rejects_untrusted_and_wrong_host_certificates(tmp_path, monkeypatch, trusted_wrong_hostname):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'wrong.example')])
    san = x509.DNSName('wrong.example') if trusted_wrong_hostname else x509.IPAddress(ipaddress.ip_address('127.0.0.1'))
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([san]), critical=False).sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path/'test-cert.pem', tmp_path/'test-key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    for env in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy',
                'WEBSOCKET_CLIENT_CA_BUNDLE'):
        monkeypatch.delenv(env, raising=False)
    if trusted_wrong_hostname:
        monkeypatch.setenv('WEBSOCKET_CLIENT_CA_BUNDLE', str(cert_path))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_path), str(key_path))
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(5)
    port = listener.getsockname()[1]
    received = []

    def serve():
        try:
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(5)
                try:
                    with context.wrap_socket(conn, server_side=True) as tls:
                        received.append(tls.recv(4096))
                except ssl.SSLError:
                    pass
        finally:
            listener.close()

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    # Only this test substitutes a loopback URL; production rejects non-Upstox URLs.
    monkeypatch.setattr(secure, 'authorized_url', lambda token: f'wss://127.0.0.1:{port}/')
    stream = secure.VerifiedMarketDataStreamer(client())
    errors, opened = [], Mock()
    stream.on('error', errors.append)
    stream.on('open', opened)
    stream.connect()
    stream.feeder.connection_thread.join(8)
    server.join(8)
    assert errors == ['TLS_VERIFICATION_FAILED']
    assert received == []  # No HTTP/credentials transmitted after failed TLS.
    opened.assert_not_called()


def test_app_uses_verified_stream_and_clears_quotes_on_failure():
    root = Path(__file__).resolve().parents[1]
    source = (root/'app.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MarketDataBuffer')
    namespace = {'threading': threading, 'LOGGER': Mock()}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), '<buffer-test>', 'exec'), namespace)
    buffer = namespace['MarketDataBuffer']('SECRET-TOKEN')
    buffer.connected = True
    buffer.quotes['NSE_FO|1'] = {'last_price': 100}
    buffer.on_error('TLS_VERIFICATION_FAILED')
    assert not buffer.connected and not buffer.quotes
    assert buffer.last_error == 'TLS_VERIFICATION_FAILED'
    buffer.on_error('AUTH_REQUIRED')
    assert buffer.auth_failed
    assert 'upstox_client.MarketDataStreamerV3(' not in source
    assert 'VerifiedMarketDataStreamer(upstox_client.ApiClient(configuration))' in source
    assert '"secure_upstox_stream.py"' in (root/'equity_runtime_health.py').read_text()
