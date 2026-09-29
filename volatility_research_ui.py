"""Isolated upload/download workbench. Does not return data to decision callers."""
import json

from volatility_research import analyze_bundle


def render_volatility_research(st):
    with st.expander('Volatility research workbench — never trade authorization'):
        st.caption('Offline captured European-option bundles only. No database writes, broker calls, '
                   'automatic collection or promotion. Existing trading safeguards are unchanged. '
                   'Input schema and conventions: VOLATILITY_RESEARCH.md.')
        upload = st.file_uploader('Captured research bundle (JSON, at most 5 MB)',
                                  type=['json'], key='vol_research_bundle')
        if upload is None or not st.button('Analyze research bundle', key='vol_research_run'):
            return
        if upload.size > 5_000_000:
            st.error('Research bundle exceeds 5 MB.')
            return
        try:
            report = analyze_bundle(json.loads(upload.getvalue()))
        except (ValueError, TypeError, KeyError, ArithmeticError, AttributeError, RecursionError):
            # Never render a raw uploaded payload or an exception containing its contents.
            st.error('Invalid or unsupported research bundle. Check timestamps, books and the documented schema.')
            return
        st.warning('RESEARCH ONLY. Fits and scenarios cannot authorize a trade or satisfy a regulatory check.')
        for sl in report['slices']:
            st.write(f"Expiry {sl['expiry']}: {sl['smile']['status']} · {sl['books']}")
            grid = sl['smile'].get('grid', [])
            if grid:
                st.line_chart(grid, x='k', y='iv', x_label='Log(strike / forward)',
                              y_label='Fitted IV (decimal)')
            st.json({'same_delta': sl['same_delta'], 'unavailable_contracts': sl['diagnostics']})
        st.json({k: report[k] for k in ('calendar_diagnostics', 'constant_tenor', 'iv_history', 'realized')})
        st.download_button('Download research report', json.dumps(report, allow_nan=False, indent=2),
                           file_name='volatility-research.json', mime='application/json',
                           key='vol_research_download', on_click='ignore')
