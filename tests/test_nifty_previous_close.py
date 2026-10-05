"""Synthetic official-format fixtures; no real sealed history or network."""
import base64
from copy import deepcopy
from datetime import date, datetime

import pytest

import nifty_previous_close as close
from forward_nifty_producer import prepare_config, validate_config, ROOT
from research_integrity import IntegrityError


def report(day='01-10-2026', value='22728.50', name='Nifty 50'):
    return ('Index Name,Index Date,Closing Index Value\n' + name + ',' + day + ',' + value + '\n').encode()


class Response:
    def __init__(self, raw, status=200):
        self.raw, self.status_code = raw, status
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size): yield self.raw


class Session:
    def __init__(self, raw, status=200): self.raw, self.status = raw, status
    def get(self, url, **kwargs):
        assert url == close.source_url(date(2026, 10, 1))
        assert kwargs['verify'] is True and kwargs['allow_redirects'] is False
        return Response(self.raw, self.status)


def provenance():
    return close.fetch(Session(report()), date(2026, 10, 5),
                       received_clock=lambda: datetime.fromisoformat('2026-10-05T08:59:00+05:30'))


def v2_config():
    source = provenance()
    config = prepare_config('2026-10-05', 22728.5, source['sha256'], '2026-10-05T09:00:00+05:30')
    config.update(version='nifty-forward-v2', previous_close_provenance=source)
    return config


def test_prior_close_skips_holiday_weekend_but_includes_special_session():
    assert close.previous_session(date(2026, 10, 5)) == date(2026, 10, 1)
    assert close.previous_session(date(2024, 3, 4)) == date(2024, 3, 2)


@pytest.mark.parametrize('day', [date(2026, 10, 2), date(2026, 10, 4), date(2027, 1, 4)])
def test_closed_or_unreviewed_calendar_does_not_fetch(day):
    with pytest.raises((IntegrityError, ValueError)):
        close.previous_session(day)


def test_source_bytes_hash_exact_date_and_decimal_adapter():
    source = provenance()
    assert base64.b64decode(source['csv_base64']) == report()
    assert source['publication_time'] is None
    assert close.validate(source, date(2026, 10, 5), '2026-10-05T09:00:00+05:30') == 22728.5
    validate_config(v2_config(), ROOT)


@pytest.mark.parametrize('raw', [report(day='30-09-2026'), report(value='NaN'), report(value='-1'),
    report(value='0'), report(name='Nifty 50 TRI'), b'<html>Denied</html>', b'',
    report() + b'Nifty 50,01-10-2026,22728.50\n', b'Index Name,Index Name\n', report() + b'bad\n'])
def test_invalid_or_ambiguous_report_rejected(raw):
    with pytest.raises(IntegrityError):
        close.parse_close(raw, date(2026, 10, 1))


@pytest.mark.parametrize('field,value', [('sha256', 'a'*64), ('close_date', '2026-09-30'),
    ('close_decimal', '999'), ('source_url', 'http://evil.invalid/'),
    ('retrieved_at', '2026-10-05T10:00:00+05:30'), ('retrieved_at', '2026-10-01T08:00:00+05:30'),
    ('publication_time', 'guessed')])
def test_provenance_changes_fail_closed(field, value):
    source = provenance()
    source[field] = value
    with pytest.raises(IntegrityError):
        close.validate(source, date(2026, 10, 5), '2026-10-05T09:00:00+05:30')


def test_embedded_source_and_numeric_config_cannot_disagree():
    config = v2_config()
    config['previous_close'] = 20000
    with pytest.raises(IntegrityError, match='CONFIG_MISMATCH'):
        validate_config(config, ROOT)
    config = deepcopy(v2_config())
    config['previous_close_source_sha256'] = 'a'*64
    with pytest.raises(IntegrityError, match='CONFIG_MISMATCH'):
        validate_config(config, ROOT)


def test_no_network_fallback_on_http_or_size_error():
    with pytest.raises(IntegrityError, match='UNAVAILABLE'):
        close.fetch(Session(report(), 403), date(2026, 10, 5), received_clock=lambda: datetime.now())
    with pytest.raises(IntegrityError, match='SIZE_INVALID'):
        close.fetch(Session(b'x'*(close.LIMIT+1)), date(2026, 10, 5), received_clock=lambda: datetime.now())


def test_naive_receipt_and_unrepresentable_adapter_fail():
    with pytest.raises(IntegrityError, match='AWARE'):
        close.fetch(Session(report()), date(2026, 10, 5), received_clock=lambda: datetime(2026, 10, 5))
    source = close.fetch(Session(report(value='22728.123456789123456')), date(2026, 10, 5),
                         received_clock=lambda: datetime.fromisoformat('2026-10-05T08:59:00+05:30'))
    with pytest.raises(IntegrityError, match='PRECISION'):
        close.validate(source, date(2026, 10, 5), '2026-10-05T09:00:00+05:30')
