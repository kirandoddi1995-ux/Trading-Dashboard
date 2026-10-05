"""Fake native credential API only; never read/write the real Windows vault."""
import ctypes
import json

import pytest

import forward_windows_credentials as vault
from research_integrity import IntegrityError


def values():
    return dict(zip(vault.NAMES, ['SECRET_ACCESS', '2027-10-01T23:00:00+05:30',
        json.dumps({'type': 'authorized_user', 'client_id': 'SYNTHETIC_CLIENT', 'client_secret': 'SECRET_CLIENT',
                    'refresh_token': 'SECRET_REFRESH', 'token_uri': 'https://oauth2.googleapis.com/token',
                    'scopes': ['https://www.googleapis.com/auth/drive.file']}), 'PRIVATE_FOLDER', 'true']))


class FakeAPI:
    def __init__(self): self.writes, self.freed = {}, 0
    def CredWriteW(self, pointer, flags):
        item = pointer._obj
        assert item.Type == 1 and item.Persist == 2
        self.writes[item.TargetName] = ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize)
        return True
    def CredReadW(self, target, kind, flags, output):
        raw = self.writes.get(target)
        if raw is None: return False
        self.buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        self.item = vault.Credential(CredentialBlobSize=len(raw), CredentialBlob=self.buffer)
        ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(vault.Credential)))[0] = ctypes.pointer(self.item)
        return True
    def CredFree(self, pointer): self.freed += 1


def test_fixed_names_native_roundtrip_and_free():
    api = FakeAPI()
    vault.write_secret(vault.NAMES[0], 'SYNTHETIC_SECRET', library=api)
    assert vault.read_secret(vault.NAMES[0], library=api) == 'SYNTHETIC_SECRET'
    assert api.freed == 1
    assert set(api.writes) == {vault.PREFIX + vault.NAMES[0]}


@pytest.mark.parametrize('name,value', [('UNKNOWN', 'secret'), (vault.NAMES[0], ''), (vault.NAMES[0], 'x'*2561)])
def test_bad_credential_name_or_size_never_written(name, value):
    api = FakeAPI()
    with pytest.raises(IntegrityError): vault.write_secret(name, value, library=api)
    assert not api.writes


def test_missing_and_invalid_read_fail_and_free():
    api = FakeAPI()
    with pytest.raises(IntegrityError): vault.read_secret(vault.NAMES[0], library=api)
    api.writes[vault.PREFIX+vault.NAMES[0]] = b'\xff'
    with pytest.raises(UnicodeError): vault.read_secret(vault.NAMES[0], library=api)
    assert api.freed == 1


def test_hidden_setup_and_failure_outputs_contain_no_secrets(monkeypatch, capsys):
    data = values()
    api = FakeAPI()
    monkeypatch.setattr(vault.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(vault.getpass, 'getpass', lambda label: data[label.split(' ')[0]])
    monkeypatch.setattr(vault, 'api', lambda: api)
    assert vault.main(['--store']) == 0
    assert vault.load() == data
    monkeypatch.setattr(vault, 'write_secret', lambda *args: (_ for _ in ()).throw(RuntimeError('SECRET_REFRESH')))
    assert vault.main(['--store']) == 2
    assert vault.main([]) == 0
    output = capsys.readouterr()
    assert all(value not in output.out + output.err for value in ['SECRET_ACCESS', 'SECRET_REFRESH', 'SECRET_CLIENT', data['DRIVE_OAUTH_TOKEN_JSON']])


def test_noninteractive_setup_fails_without_prompt(monkeypatch, capsys):
    monkeypatch.setattr(vault.sys.stdin, 'isatty', lambda: False)
    monkeypatch.setattr(vault.getpass, 'getpass', lambda *args: pytest.fail('Prompt invoked'))
    assert vault.main(['--store']) == 2
    assert 'BLOCKED' in capsys.readouterr().out


@pytest.mark.parametrize('field,value', [('FORWARD_CAPTURE_LICENSE_ACK', 'false'), ('FORWARD_TOKEN_EXPIRES_AT', 'naive'),
    ('DRIVE_OAUTH_TOKEN_JSON', '{}')])
def test_invalid_config_never_enables_unattended_auth(field, value):
    data = values()
    data[field] = value
    with pytest.raises((ValueError, IntegrityError)): vault.validate(data)
