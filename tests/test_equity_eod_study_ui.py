import json

from streamlit.testing.v1 import AppTest


SOURCE = "import streamlit as st\nfrom equity_eod_study_ui import render_equity_eod_study\nrender_equity_eod_study(st)"


def test_panel_is_not_run_until_explicit_synthetic_action():
    app = AppTest.from_string(SOURCE).run()
    assert not app.exception
    assert any("REAL STUDY NOT RUN" in item.value for item in app.warning)
    assert not app.dataframe
    next(b for b in app.button if b.key == "equity_eod_rehearse").click().run()
    assert not app.exception
    assert any("SYNTHETIC ONLY" in item.value for item in app.warning)
    report = next(json.loads(item.value) for item in app.json if "report_sha256" in item.value)
    assert len(report["payload"]["rows"]) == 12
    assert report["payload"]["training_eligible"] is False
    assert report["payload"]["market_data_reads"] == 0


def test_errors_are_redacted_and_do_not_disappear_into_claims(monkeypatch):
    import equity_eod_study as study
    def denied():
        raise RuntimeError("SYNTHETIC_PRIVATE_ERROR_DO_NOT_DISPLAY")
    monkeypatch.setattr(study, "rehearsal", denied)
    app = AppTest.from_string(SOURCE).run()
    next(b for b in app.button if b.key == "equity_eod_rehearse").click().run()
    assert not app.exception
    assert any("EQUITY_STUDY_REVIEW_REQUIRED" in item.value for item in app.error)
    assert all("SYNTHETIC_PRIVATE_ERROR" not in item.value for item in app.error)
