from copy import deepcopy
import json

import pytest

import equity_eod_study as study


def test_readiness_never_executes_a_replay(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("REPLAY_ON_BOOT")
    monkeypatch.setattr(study, "run_long_bracket_backtest", forbidden)
    state = study.readiness()
    assert state["status"] == "REAL_STUDY_NOT_RUN"
    assert state["market_data_reads"] == state["network_calls"] == 0
    assert all(state[flag] is False for flag in study.AUTHORITY_FLAGS)


def test_generated_report_uses_same_engine_and_is_reproducible():
    result = study.rehearsal()
    assert result == study.rehearsal()
    assert study.validate_rehearsal(json.loads(json.dumps(result))) == result
    payload = result["payload"]
    assert payload["engine"] == "event-driven-bracket-v2"
    assert len(payload["rows"]) == 12
    assert payload["market_accuracy"] is payload["portfolio_return"] is None
    assert all(payload[flag] is False for flag in study.AUTHORITY_FLAGS)
    assert payload["real_study_status"] == payload["real_baselines_status"] == "NOT_RUN"


def test_cost_stresses_do_not_retune_signal_or_bracket():
    rows = study.rehearsal()["payload"]["rows"]
    for name, *_ in study.SCENARIOS:
        group = [r for r in rows if r["scenario"] == name]
        assert [r["cost_bps"] for r in group] == [30., 60., 100.]
        assert len({r["exit"] for r in group}) == len({r["outcome"] for r in group}) == 1
        assert group[0]["net_return_scenario_only"] - group[1]["net_return_scenario_only"] == pytest.approx(.003)
    assert next(r for r in rows if r["scenario"] == "Adverse opening gap")["exit"] == 90.
    assert next(r for r in rows if r["scenario"] == "Target opening then reversal")["exit"] == 110.


@pytest.mark.parametrize("tamper", ["price", "hash", "eligibility", "status", "shape"])
def test_modified_report_never_becomes_market_evidence(tamper):
    value = deepcopy(study.rehearsal())
    if tamper == "price":
        value["payload"]["rows"][0]["exit"] = 999.
    elif tamper == "hash":
        value["report_sha256"] = "0" * 64
    elif tamper in ("eligibility", "status"):
        value["payload"]["training_eligible" if tamper == "eligibility" else "status"] = True
        value["report_sha256"] = study.fingerprint(value["payload"])
    else:
        value["extra"] = 1
    with pytest.raises(ValueError, match="EQUITY_REHEARSAL_"):
        study.validate_rehearsal(value)


@pytest.mark.parametrize("change", [
    lambda p: p.update(market_accuracy=.99),
    lambda p: p.update(portfolio_return=5.),
    lambda p: p["rows"].pop(),
    lambda p: p["rows"][0].update(exit=999.),
    lambda p: p["design"].update(training_eligible=True),
    lambda p: p["design"].update(end="2026-01-01"),
    lambda p: p["design"].update(promotion_authorised=0),
    lambda p: p.update(extra_claim="not part of fixed recipe"),
])
def test_rehashing_cannot_turn_fabricated_content_into_a_valid_report(change):
    value = study.rehearsal()
    change(value["payload"])
    value["report_sha256"] = study.fingerprint(value["payload"])
    with pytest.raises(ValueError, match="EQUITY_REHEARSAL_SEMANTICS_INVALID"):
        study.validate_rehearsal(value)
