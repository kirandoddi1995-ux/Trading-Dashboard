import copy
import datetime as dt

import pytest

import equity_research_observations as research
from equity_observation_capture import EquityCapture


def fixture_source(monkeypatch):
    from types import SimpleNamespace
    from prediction_validation import scanner_composite_score
    from trade_contracts import calculate_trade_math
    now = dt.datetime(2026, 9, 10, 4, tzinfo=dt.timezone.utc)
    capture = EquityCapture(identity={}, settings={'horizon_sessions': 15, 'minimum_net_rr': 1.3})
    components = dict.fromkeys(['trend', 'momentum', 'volume', 'relative_strength',
                               'risk_reward', 'adx', 'volatility', 'historical_edge', 'momentum_beta'], 70.)
    capture.observe(dict(price=100, sl=95, tgt=107, scanner_components=components,
                         score=scanner_composite_score(components),
                         trade_math=calculate_trade_math(100,95,107,round_trip_cost_bps=14,minimum_ratio=1.3),
                         raw_quote={'instrument_token': 'NSE_EQ|FIXTURE'},
                         cost_estimate=SimpleNamespace(round_trip_bps=14)), now=now)
    payload = {'decision_id': 'fixture', 'decision_at': now.isoformat(), 'action': 'No Trade',
               'identifiers': {'asset_class': 'equity', 'strategy_id': 'equity-scanner-v19.0',
                               'target_version': 'net-excess-execution-v2', 'horizon_sessions': 15,
                               'instrument': 'FIXTURE'},
               'features': {'raw_values_used': {'equity_capture': capture.snapshot()}},
               'levels': {'entry': 100, 'stop': 95, 'target': 107},
               'governance': {'allow_trade': False, 'blocking_reasons': ['No model']}}
    original_pin = research.digest(payload)
    monkeypatch.setattr(research, 'COHORT', {'fixture': {
        'event_id': 'event', 'payload_sha256': original_pin,
        'normalized_payload_sha256': research.normalized_payload_digest(payload)}})
    return {'event_id': 'event', 'event_hash': 'immutable-fixture-hash',
            'payload': payload, 'verified_payload_sha256': original_pin}


def test_cohort_is_exactly_89_fixed_ids():
    assert len(research.COHORT) == 89
    assert len({v['event_id'] for v in research.COHORT.values()}) == 89
    assert all(len(k) == 64 and len(v['payload_sha256']) == 64 for k,v in research.COHORT.items())


def test_enroll_preserves_missing_and_never_authorizes(monkeypatch):
    source = fixture_source(monkeypatch)
    original = copy.deepcopy(source)
    result = research.enroll(source, now='2026-09-11T00:00:00Z')
    assert source == original
    assert result['approved'] is False
    assert result['capture']['quote']['bid_used'] is None
    assert result['capture']['source_feature_available_at'] is None
    assert result['retrospective_enrollment'] is True


@pytest.mark.parametrize('mutation', ['id', 'score', 'event'])
def test_tampered_or_outside_cohort_rejected(monkeypatch, mutation):
    source = fixture_source(monkeypatch)
    if mutation == 'id':
        source['payload']['decision_id'] = 'other'
    elif mutation == 'score':
        source['payload']['features']['raw_values_used']['equity_capture']['scanner_composite_score'] = None
    else:
        source['event_id'] = 'other'
    with pytest.raises(ValueError):
        research.enroll(source, now='2026-09-11T00:00:00Z')


def test_incomplete_even_if_fingerprint_matches_is_rejected(monkeypatch):
    source = fixture_source(monkeypatch)
    source['payload']['features']['raw_values_used']['equity_capture']['inputs']['trade_math'] = None
    research.COHORT['fixture']['payload_sha256'] = research.digest(source['payload'])
    source['verified_payload_sha256'] = research.digest(source['payload'])
    research.COHORT['fixture']['normalized_payload_sha256'] = research.normalized_payload_digest(source['payload'])
    with pytest.raises(ValueError, match='Incomplete'):
        research.enroll(source, now='2026-09-11T00:00:00Z')


def test_no_naive_or_predecision_enrollment(monkeypatch):
    source = fixture_source(monkeypatch)
    for stamp in ('2026-09-11', '2026-09-09T00:00:00Z'):
        with pytest.raises(ValueError):
            research.enroll(source, now=stamp)


def test_equivalent_numbers_pass_without_mutating_source(monkeypatch):
    source = fixture_source(monkeypatch)
    source['payload']['levels']['entry'] = 100.0
    assert research.digest(source['payload']) != source['verified_payload_sha256']
    before = research.digest(source)
    result = research.enroll(source, now='2026-09-11T00:00:00Z')
    assert result['approved'] is False
    assert research.digest(source) == before
    assert isinstance(source['payload']['levels']['entry'], float)


def test_enrollment_keeps_original_pin_for_insertion_policy(monkeypatch):
    source = fixture_source(monkeypatch)
    original = source['verified_payload_sha256']
    assert original != research.normalized_payload_digest(source['payload'])
    result = research.enroll(source, now='2026-09-11T00:00:00Z')
    assert result['source_payload_sha256'] == original
    assert result['source_event_hash'] == source['event_hash']


@pytest.mark.parametrize('value', [100.01, '100', True, None])
def test_genuine_changes_still_rejected(monkeypatch, value):
    source = fixture_source(monkeypatch)
    source['payload']['levels']['entry'] = value
    with pytest.raises(ValueError, match='Source payload differs'):
        research.enroll(source, now='2026-09-11T00:00:00Z')


@pytest.mark.parametrize('pin', [None, '0' * 64])
def test_database_original_pin_is_independently_required(monkeypatch, pin):
    source = fixture_source(monkeypatch)
    source['verified_payload_sha256'] = pin
    with pytest.raises(ValueError, match='Source fingerprint pin differs'):
        research.enroll(source, now='2026-09-11T00:00:00Z')


def test_normalization_is_exact_and_type_sensitive():
    import math
    assert research.normalized_payload_digest({'x': 4}) == research.normalized_payload_digest({'x': 4.0})
    for value in (True, '4', None, 4.01):
        assert research.normalized_payload_digest({'x': value}) != research.normalized_payload_digest({'x': 4})
    assert research.normalized_payload_digest({}) != research.normalized_payload_digest({'x': None})
    assert research.normalized_payload_digest(2**53 + 1) != research.normalized_payload_digest(float(2**53 + 1))
    assert research.normalized_payload_digest(1.3) != research.normalized_payload_digest(math.nextafter(1.3, math.inf))
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            research.normalized_payload_digest(value)
    assert len({v['normalized_payload_sha256'] for v in research.COHORT.values()}) == 89
