"""Capture plumbing must be equity-only and must not enter gate calculations."""
import ast
import pytest
from pathlib import Path


@pytest.mark.parametrize("package", [None, {"purpose": "RESEARCH_OBSERVATION"},
    {"purpose": "LIVE_EQUITY_MANUAL_QUOTE_CHECK", "confirmed": True},
    {"purpose": "USER_REPORTED_BROKER_RESULT", "status": "FILLED"}])
def test_real_governance_new_equity_route_refuses_non_execution_evidence(monkeypatch, package):
    import datetime as dt
    from dataclasses import replace
    import live_governance
    from live_evidence import unavailable_bundle
    from resilience_control_plane import ResilienceControlPlane

    def legacy_must_not_run(**kwargs):
        raise AssertionError("Equity must not use the statistical fill-model route")
    monkeypatch.setattr(live_governance, "executable_fill_adjusted_ev", legacy_must_not_run)
    class Ledger:
        def outbox_stats(self): return {"pending": 0, "oldest_age_seconds": 0}
    class Metrics:
        def record(self, *a, **k): pass
    bundle = replace(unavailable_bundle(
        strategy_id="fixture", asset_class="equity", target_version="fixture", horizon_sessions=15,
        instrument="ABC", decision_at=dt.datetime.now(dt.timezone.utc)),
        equity_execution_evidence=package,
        fill_evidence={"status": "VALIDATED", "fill_probability": 1, "fill_probability_low": 1})
    result = live_governance.evaluate_live_governance(
        instrument="ABC", entry=100, stop=95, target=108, evidence=bundle,
        services=live_governance.GovernanceServices(control_plane=ResilienceControlPlane(),
            evidence_ledger=Ledger(), observability=Metrics(), app_build="fixture"))
    assert not result["allow_trade"]
    assert result["fill_adjusted_expected_value"]["expected_value_per_order"] is None
    assert any("execution/outcome evidence" in reason for reason in result["blocking_reasons"])
    assert result["conformal"]["status"] == "DEFERRED"
    assert "calibration_uncertainty" in result


@pytest.mark.parametrize("asset,threshold", [
    ("equity", 1.30), ("options", 2.00), ("futures", 2.00),
    ("mcx", 2.00), ("equity_smc", 2.00),
])
def test_both_ev_calls_receive_asset_specific_threshold(monkeypatch, asset, threshold):
    import datetime as dt
    from dataclasses import replace
    import live_governance
    from live_evidence import unavailable_bundle
    from resilience_control_plane import ResilienceControlPlane

    class Ledger:
        def outbox_stats(self): return {"pending": 0, "oldest_age_seconds": 0}
    class Metrics:
        def record(self, *args, **kwargs): pass

    captured = {}
    simple_ev = live_governance.executable_expected_value
    def simple(**kwargs):
        result = simple_ev(**kwargs)
        captured["simple"] = result["trade_math"]["minimum_ratio"]
        return result
    def fill(**kwargs):
        captured["fill"] = kwargs["minimum_ratio"]
        return {"status": "ABSTAIN", "failures": ["fixture fill evidence missing"]}
    monkeypatch.setattr(live_governance, "executable_expected_value", simple)
    monkeypatch.setattr(live_governance, "executable_fill_adjusted_ev", fill)
    monkeypatch.setattr(live_governance, "equity_execution_ev", fill)
    monkeypatch.setattr(live_governance, "validate_calibration_package", lambda *a, **k: {
        "usable": True, "status": "PASS", "probability": .7, "conservative_probability": .65})
    bundle = replace(unavailable_bundle(
        strategy_id="fixture", asset_class=asset, target_version="fixture", horizon_sessions=15,
        instrument="FIXTURE", decision_at=dt.datetime.now(dt.timezone.utc)),
        fill_evidence={"time_exit_probability": .1})
    result = live_governance.evaluate_live_governance(
        instrument="FIXTURE", entry=100, stop=95, target=107, evidence=bundle,
        services=live_governance.GovernanceServices(
            control_plane=ResilienceControlPlane(), evidence_ledger=Ledger(),
            observability=Metrics(), app_build="fixture"))
    assert captured == {"simple": threshold, "fill": threshold}
    assert result["allow_trade"] is False  # Other missing evidence still blocks approval.


def test_continuous_decision_is_persisted_by_real_ledger(tmp_path):
    import datetime as dt
    import sqlite3
    import pytest
    from evidence_ledger import ImmutableEvidenceLedger
    from live_evidence import unavailable_bundle
    from live_governance import GovernanceServices, evaluate_live_governance
    from resilience_control_plane import ResilienceControlPlane

    class Metrics:
        def record(self, *args, **kwargs):
            pass

    ledger = ImmutableEvidenceLedger(sqlite3.connect, str(tmp_path / 'ledger.sqlite3'))
    requests = []
    events = []

    def record(**kwargs):
        requests.append(kwargs)
        event = ledger.append(**kwargs)
        events.append(event)
        return event

    bundle = unavailable_bundle(
        strategy_id='equity-scanner-v19.0', asset_class='equity',
        target_version='net-excess-execution-v2', horizon_sessions=15,
        instrument='FIXTURE', decision_at=dt.datetime.now(dt.timezone.utc))
    result = evaluate_live_governance(
        instrument='FIXTURE', entry=100, stop=95, target=107, evidence=bundle,
        services=GovernanceServices(
            control_plane=ResilienceControlPlane(), evidence_ledger=ledger,
            evidence_recorder=record, observability=Metrics(), app_build='fixture'))

    assert [event['event_type'] for event in events] == [
        'RISK_DECISION', 'CONTINUOUS_DECISION']
    assert all(request['payload']['asset_class'] == 'equity' for request in requests)
    assert result['allow_trade'] is False
    assert result['blocking_reasons']
    assert not any('evidence append failed' in reason for reason in result['blocking_reasons'])
    assert ledger.verify()['valid']
    stored = ledger.events(events[-1]['aggregate_id'])
    assert len(stored) == 1
    assert stored[0]['payload'] == events[-1]['payload']
    assert ledger.append(**requests[-1])['duplicate'] is True
    assert len(ledger.events(events[-1]['aggregate_id'])) == 1
    with pytest.raises(ValueError, match='already bound to different evidence'):
        ledger.append(**{**requests[-1], 'payload': {'changed': True}})
    with pytest.raises(ValueError, match='Unsupported evidence event type'):
        ledger.append(aggregate_id='invalid', event_type='UNKNOWN_EVENT', payload={})


def test_quote_verification_policy_is_forwarded_and_audited(monkeypatch):
    import datetime as dt
    import live_governance
    from live_evidence import unavailable_bundle
    from live_governance import GovernanceServices, evaluate_live_governance
    from resilience_control_plane import ResilienceControlPlane

    seen = []
    monkeypatch.setattr(live_governance, 'runtime_readiness_findings',
                        lambda environment, quote_verification_policy='automated', asset_class='unknown':
                        seen.append(quote_verification_policy) or [])
    class Ledger:
        def outbox_stats(self): return {'pending': 0, 'oldest_pending_seconds': 0}
    class Metrics:
        def record(self, *args, **kwargs): pass
    bundle = unavailable_bundle(
        strategy_id='equity-scanner-v19.0', asset_class='equity',
        target_version='target-v1', horizon_sessions=15, instrument='FIXTURE',
        decision_at=dt.datetime.now(dt.timezone.utc))
    result = evaluate_live_governance(
        instrument='FIXTURE', entry=100, stop=95, target=108, evidence=bundle,
        quote_verification_policy='equity-intent-manual-quote-v1',
        services=GovernanceServices(control_plane=ResilienceControlPlane(),
                                    evidence_ledger=Ledger(), observability=Metrics(),
                                    app_build='fixture'))
    assert seen == ['equity-intent-manual-quote-v1']
    assert result['quote_verification_policy'] == 'equity-intent-manual-quote-v1'


def test_capture_does_not_change_governance_rejection():
    import datetime as dt
    from live_evidence import unavailable_bundle
    from live_governance import GovernanceServices, evaluate_live_governance
    from resilience_control_plane import ResilienceControlPlane
    class Ledger:
        def outbox_stats(self):
            return {'pending': 0, 'oldest_age_seconds': 0}
    class Metrics:
        def record(self, *args, **kwargs):
            pass
    class Spine:
        def capture(self, **kwargs):
            self.kwargs = kwargs
            return {'decision_id': 'fixture', 'event': {'event_hash': 'fixture'}}
    bundle = unavailable_bundle(strategy_id='equity-scanner-v19.0', asset_class='equity',
                                target_version='target-v1', horizon_sessions=15,
                                instrument='FIXTURE', decision_at=dt.datetime.now(dt.timezone.utc))
    results = []
    for payload in [None, {'equity_capture': {'scanner_composite_score': 72}}]:
        spine = Spine()
        results.append(evaluate_live_governance(
            instrument='FIXTURE', entry=100, stop=95, target=107, evidence=bundle,
            equity_capture_inputs=payload,
            services=GovernanceServices(control_plane=ResilienceControlPlane(),
                                        evidence_ledger=Ledger(), observability=Metrics(),
                                        app_build='fixture', decision_spine=spine)))
        if payload is not None:
            assert spine.kwargs['input_values'] == payload
    assert results[0]['blocking_reasons'] == results[1]['blocking_reasons']
    assert results[0]['allow_trade'] is results[1]['allow_trade'] is False


def test_capture_argument_only_used_in_final_equity_ledger_append():
    source = (Path(__file__).resolve().parents[1] / 'live_governance.py').read_text()
    tree = ast.parse(source)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'evaluate_live_governance')
    capture = next(n for n in ast.walk(function) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute) and n.func.attr == 'capture')
    uses = [n for n in ast.walk(function) if isinstance(n, ast.Name)
            and n.id == 'equity_capture_inputs']
    assert uses and all(n in list(ast.walk(capture)) for n in uses)
    forwarding = next(k.value for k in capture.keywords if k.arg is None)
    assert isinstance(forwarding, ast.IfExp)
    compiled = compile(ast.Expression(forwarding), '<forwarding>', 'eval')
    from types import SimpleNamespace
    for asset in ['options', 'futures', 'mcx', 'equity_smc']:
        assert eval(compiled, {'evidence': SimpleNamespace(context=SimpleNamespace(asset_class=asset)),
                               'equity_capture_inputs': {'fixture': 1}}) == {}
    assert eval(compiled, {'evidence': SimpleNamespace(context=SimpleNamespace(asset_class='equity')),
                           'equity_capture_inputs': {'fixture': 1}}) == {'input_values': {'fixture': 1}}
