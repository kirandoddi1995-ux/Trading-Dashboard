"""Capture plumbing must be equity-only and must not enter gate calculations."""
import ast
from pathlib import Path


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
