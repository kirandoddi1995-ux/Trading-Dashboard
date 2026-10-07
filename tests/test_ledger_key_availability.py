"""Presence-only secret backup checks with synthetic values, no real files."""
import json
from pathlib import Path

import pytest

import ledger_key_availability as check


@pytest.mark.parametrize('raw,count', [
    (b'EVIDENCE_LEDGER_SIGNING_KEY="synthetic-key"', 1),
    (b'[auth]\nEVIDENCE_LEDGER_SIGNING_KEY="synthetic-key"', 1),
    (b'EVIDENCE_LEDGER_SIGNING_KEY=""', 0),
    (b'EVIDENCE_LEDGER_SIGNING_KEY=42', 0),
    (b'OTHER="synthetic-key"', 0),
    (b'EVIDENCE_LEDGER_SIGNING_KEY="   "', 0),
    (b'evidence_ledger_signing_key="synthetic-key"', 0),
    (b'\xef\xbb\xbfEVIDENCE_LEDGER_SIGNING_KEY="synthetic-key"', 1),
    (b'[first]\nEVIDENCE_LEDGER_SIGNING_KEY="one"\n[second]\nEVIDENCE_LEDGER_SIGNING_KEY="two"', 2),
])
def test_presence_only(raw, count):
    result = check.inspect_toml(raw)
    assert result['nonempty_string_copies'] == count
    assert result['historical_match_verified'] is False
    assert result['values_output'] is False
    assert 'synthetic-key' not in json.dumps(result)
    assert result['writes'] == result['network_calls'] == 0


@pytest.mark.parametrize('raw', [b'', b'not TOML synthetic-secret', b'\xff',
    b'EVIDENCE_LEDGER_SIGNING_KEY="one"\nEVIDENCE_LEDGER_SIGNING_KEY="two"'])
def test_unsupported_format_is_redacted(raw):
    with pytest.raises(check.KeyCheckError) as error:
        check.inspect_toml(raw)
    assert 'synthetic-secret' not in str(error.value)


def test_size_and_depth_bound(monkeypatch):
    monkeypatch.setattr(check, 'MAX_BYTES', 1)
    with pytest.raises(check.KeyCheckError, match='SIZE_INVALID'):
        check.inspect_toml(b'k="value"')
    monkeypatch.setattr(check, 'MAX_BYTES', 1024)
    monkeypatch.setattr(check, 'MAX_DEPTH', 0)
    with pytest.raises(check.KeyCheckError, match='NESTING_INVALID'):
        check.inspect_toml(b'[section]\nk="value"')


def test_outside_project_file_is_unchanged(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    private = tmp_path / 'private.toml'
    raw = b'EVIDENCE_LEDGER_SIGNING_KEY="synthetic-key"'
    private.write_bytes(raw)
    result = check.check_file(private, project_root=project)
    assert result['present'] is True
    assert private.read_bytes() == raw
    assert sorted(p.name for p in tmp_path.iterdir()) == ['private.toml', 'project']


def test_project_relative_missing_directory_rejected(tmp_path):
    private = tmp_path / 'in-project.toml'
    private.write_bytes(b'EVIDENCE_LEDGER_SIGNING_KEY="synthetic-key"')
    with pytest.raises(check.KeyCheckError, match='OUTSIDE_PROJECT'):
        check.check_file(private, project_root=tmp_path)
    for path in (Path('relative.toml'), tmp_path / 'missing', tmp_path):
        with pytest.raises(check.KeyCheckError):
            check.check_file(path, project_root=tmp_path / 'project')


def test_preview_does_not_prompt_or_read(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError('must not prompt or read')
    monkeypatch.setattr(check.getpass, 'getpass', forbidden)
    monkeypatch.setattr(check, 'check_file', forbidden)
    assert check.main([]) == 0
    assert json.loads(capsys.readouterr().out)['reads'] == 0


def test_cli_hidden_path_and_value_redaction(tmp_path, monkeypatch, capsys):
    private = tmp_path / 'private.toml'
    private.write_bytes(b'EVIDENCE_LEDGER_SIGNING_KEY="synthetic-private-key"')
    prompts = []
    def prompt(text):
        prompts.append(text)
        return str(private)
    monkeypatch.setattr(check.getpass, 'getpass', prompt)
    assert check.main(['--check-private-toml']) == 0
    output = capsys.readouterr().out
    assert json.loads(output)['present'] is True
    assert prompts and 'hidden' in prompts[0]
    assert str(private) not in output and 'synthetic-private-key' not in output


def test_cli_failure_has_no_parser_details(tmp_path, monkeypatch, capsys):
    private = tmp_path / 'invalid.toml'
    private.write_bytes(b'synthetic-private-password INVALID')
    monkeypatch.setattr(check.getpass, 'getpass', lambda text: str(private))
    assert check.main(['--check-private-toml']) == 2
    output = capsys.readouterr().out
    assert 'password' not in output and str(private) not in output


def test_cli_never_accepts_or_echoes_a_key_or_path_argument(capsys):
    assert check.main(['--file', 'synthetic-private-secret']) == 2
    captured = capsys.readouterr()
    assert 'synthetic-private-secret' not in captured.out + captured.err
    assert json.loads(captured.out)['code'] == 'PRIVATE_KEY_CHECK_ARGUMENTS_INVALID'


def test_links_are_rejected_without_read(tmp_path, monkeypatch):
    private = tmp_path / 'private.toml'
    private.write_bytes(b'EVIDENCE_LEDGER_SIGNING_KEY="synthetic-key"')
    original = Path.is_junction
    monkeypatch.setattr(Path, 'is_junction', lambda path: path == private or original(path))
    with pytest.raises(check.KeyCheckError, match='LINK_REJECTED'):
        check.check_file(private, project_root=tmp_path / 'project')


def test_cli_unexpected_prompt_failure_is_redacted(monkeypatch, capsys):
    def fail(*args):
        raise OSError('synthetic-secret-prompt-value')
    monkeypatch.setattr(check.getpass, 'getpass', fail)
    assert check.main(['--check-private-toml']) == 2
    assert 'secret-prompt-value' not in capsys.readouterr().out
