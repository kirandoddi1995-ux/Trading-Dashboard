"""Isolated read-only research pages; no startup fitting, filesystem or model calls."""
from __future__ import annotations

import json
from typing import Any

PAGES = ('Backtesting', 'ML Models', 'Automation Reports', 'Evidence Assistant')


def render_workbench(st: Any, page: str) -> None:
    """Contain optional-page failures so missing research code cannot break boot."""
    if page not in PAGES:
        st.error('RESEARCH_PAGE_NOT_AVAILABLE')
        return
    st.subheader('NIFTY ' + page)
    st.warning('INSUFFICIENT EVIDENCE — generated demonstrations are not market performance.')
    st.caption('Read-only research. No orders, live training, model calls, schedules or automatic tuning.')
    try:
        if page == 'Evidence Assistant':
            _assistant(st)
        else:
            _research(st, page)
    except Exception:
        # Do not echo provider errors, user input, paths or private report content.
        st.error('RESEARCH_PAGE_UNAVAILABLE — other application pages and capture are unaffected.')


def _research(st: Any, page: str) -> None:
    """Lazy backend import and explicit opt-in execution only."""
    from research_workbench import catalog, run_generated
    state = catalog()
    columns = st.columns(3)
    columns[0].metric('Admitted market results', 'Unavailable')
    columns[1].metric('Decision authority', 'None')
    columns[2].metric('Real training', 'Off')
    with st.expander('Frozen recipes and admission limits'):
        st.json(state)
    if page == 'Backtesting':
        st.write('Run, inspect and compare frozen generated studies. Real results require licensed quotes, dated contracts, costs, depth, margin and admitted outcomes.')
        st.caption('No index-to-option profit conversion; expiry, stops and fills are unsupported unless independently evidenced.')
    elif page == 'ML Models':
        st.write('Model registry, chronological validation and baseline comparison. Feature importance is unavailable unless a valid fitted model and independent evaluation support it.')
        st.caption('Whole-session validation; train-only transformations. Drift is diagnostic, never automatic retraining.')
    else:
        st.write('Scheduled research remains disabled. No private workflow artifacts or capture files are discovered automatically.')
        st.caption('Generated report rehearsal only. Real reports require a commissioned private, custody-verified input path.')
    key = 'workbench_report_' + page
    study = {'Backtesting': 'backtesting', 'ML Models': 'ml_models',
             'Automation Reports': 'automation_reports'}[page]
    if st.button('Run generated report', key='workbench_run_' + page):
        report = run_generated(study)
        st.session_state[key] = report
    report = st.session_state.get(key)
    if report is not None:
        payload = report.get('payload', {})
        if isinstance(payload, dict) and payload:
            tabs = st.tabs(['Results', 'Assumptions', 'Validation and drift', 'Evidence and registry'])
            with tabs[0]:
                st.caption('Artificial fixture units only. These numbers are not tradable returns.')
                st.json(payload.get('backtest', {}))
                st.json(payload.get('generated_execution', {}), expanded=False)
            with tabs[1]:
                st.json(payload.get('assumptions', {}))
                st.json(payload.get('readiness', {}))
            with tabs[2]:
                st.json(payload.get('validation', {}), expanded=False)
                st.json(payload.get('drift', {}))
            with tabs[3]:
                st.json(payload.get('model_registry', {}))
                st.json(payload.get('identities', {}), expanded=False)
                st.json(payload.get('automation_report', {}))
        with st.expander('Exact generated report and reproducibility hash'):
            st.json(report)
        st.download_button('Download generated report', json.dumps(report, sort_keys=True, allow_nan=False),
                           file_name='generated-research-report.json', mime='application/json', key='workbench_download_' + page)
        if page == 'Backtesting':
            st.caption('Comparison reruns the same frozen recipe to check reproducibility; it does not search or rank strategies.')
            if st.button('Compare generated study assumptions', key='workbench_compare'):
                from research_workbench import compare_reports
                st.json(compare_reports(report, run_generated(study)))


def _assistant(st: Any) -> None:
    """Free-text questions stay untrusted; no commissioned LLM backend is loaded."""
    from research_assistant import answer, assistant_status
    with st.expander('Evidence catalogue and disabled backend status'):
        st.json(assistant_status())
    usecase = st.selectbox('Evidence task', ['Explain evidence', 'Backtest summary', 'Capture health', 'Report draft'])
    question = st.text_input('Question about the admitted evidence', max_chars=500)
    st.caption('No private files or credentials are retrieved. Generated responses cannot become signals or approvals.')
    if st.button('Explain with record citations', key='workbench_explain'):
        st.json(answer(question, usecase))
