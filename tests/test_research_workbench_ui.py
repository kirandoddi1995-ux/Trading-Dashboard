"""Optional research screens cannot fit on boot or break the main application."""
from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from research_workbench_ui import PAGES


@pytest.fixture
def backends(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    research = ModuleType('research_workbench')
    assistant = ModuleType('research_assistant')

    def run(study: str) -> dict[str, Any]:
        calls.append(study)
        return {'status': 'SYNTHETIC_ONLY', 'approval_authority': False, 'training_eligible': False}

    research.catalog = lambda: {'status': 'INSUFFICIENT_EVIDENCE'}  # type: ignore[attr-defined]
    research.run_generated = run  # type: ignore[attr-defined]
    research.compare_reports = lambda a, b: {'status': 'SYNTHETIC_COMPARISON_ONLY'}  # type: ignore[attr-defined]
    assistant.assistant_status = lambda: {'backend_enabled': False}  # type: ignore[attr-defined]
    assistant.answer = lambda q, u: {'status': 'GENERATED_GROUNDED_FALLBACK', 'approval_authority': False}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'research_workbench', research)
    monkeypatch.setitem(sys.modules, 'research_assistant', assistant)
    return calls


@pytest.mark.parametrize('page', PAGES)
def test_pages_boot_without_running_or_training(page: str, backends: list[str]) -> None:
    app = AppTest.from_string("import streamlit as st\nfrom research_workbench_ui import render_workbench\nrender_workbench(st," + repr(page) + ")").run()
    assert not app.exception
    assert backends == []
    assert any('INSUFFICIENT EVIDENCE' in item.value for item in app.warning)
    assert any(item.value == 'NIFTY ' + page for item in app.subheader)


@pytest.mark.parametrize('page', PAGES[:3])
def test_generated_opt_in_and_download(page: str, backends: list[str]) -> None:
    app = AppTest.from_string("import streamlit as st\nfrom research_workbench_ui import render_workbench\nrender_workbench(st," + repr(page) + ")").run()
    next(button for button in app.button if button.label == 'Run generated report').click().run()
    study = {'Backtesting': 'backtesting', 'ML Models': 'ml_models', 'Automation Reports': 'automation_reports'}[page]
    assert not app.exception and backends == [study]
    assert any('SYNTHETIC_ONLY' in item.value for item in app.json)
    if page == 'Backtesting':
        next(button for button in app.button if button.label == 'Compare generated study assumptions').click().run()
        assert backends == [study, study]
        assert not app.exception


def test_backend_failure_is_redacted_and_contained(backends: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def bad() -> Any:
        raise RuntimeError('SYNTHETIC_PRIVATE_ERROR_MUST_NOT_RENDER')

    monkeypatch.setattr(sys.modules['research_workbench'], 'catalog', bad)
    app = AppTest.from_string("import streamlit as st\nfrom research_workbench_ui import render_workbench\nrender_workbench(st,'ML Models')").run()
    assert not app.exception and backends == []
    assert len(app.error) == 1 and 'RESEARCH_PAGE_UNAVAILABLE' in app.error[0].value
    assert 'SYNTHETIC_PRIVATE_ERROR' not in app.error[0].value


def test_unknown_page_does_not_import_backend() -> None:
    app = AppTest.from_string("import streamlit as st\nfrom research_workbench_ui import render_workbench\nrender_workbench(st,'unknown')").run()
    assert not app.exception and app.error[0].value == 'RESEARCH_PAGE_NOT_AVAILABLE'
