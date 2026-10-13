"""Authenticated dashboard research view; no collectors, uploads, API keys or orders."""
from __future__ import annotations

from typing import Any, cast

from research_lab import plumbing_demo, readiness


def render_research_lab(st: Any) -> None:
    """Render only reviewed fixed content and an opt-in synthetic offline self-check."""
    st.subheader('NIFTY Research Lab')
    st.warning('INSUFFICIENT EVIDENCE — no trained model, calibrated win probability or tradable edge is claimed.')
    st.caption('Read-only research. Capture, safety gates, sealed periods and release settings are unchanged. No orders or automatic tuning.')
    state = cast(dict[str, Any], readiness())
    tabs = st.tabs(['Evidence & study', 'Backtesting & automation', 'ML & monitoring', 'Evidence explanation'])
    with tabs[0]:
        st.write('Verified research sessions and executable labels: unavailable, not zero.')
        for requirement in state['requirements']:
            st.write('Required: ' + requirement)
        st.write('First study: frozen futures-direction paper baseline versus no-trade and simple rules. Options require actual premium and contract quote evidence; index returns are not option profits.')
    with tabs[1]:
        st.write('Existing engine: version-as-of snapshots → causal dataset manifest → dated quote/cost scenarios → whole-session purged walk-forward → complete trial ledger → evidence gate.')
        st.write('Private real-data automation is not connected. The merged public workflow is synthetic-only and remains disabled. No backfill or hidden training is performed here.')
        if st.button('Run generated offline plumbing check', key='research_lab_demo'):
            try:
                st.json(plumbing_demo())
            except Exception:
                st.error('RESEARCH_SELF_CHECK_FAILED — no raw error or private data is displayed.')
    with tabs[2]:
        st.write('Start with frozen ridge and chance/mean/no-trade/rule baselines, using whole IST sessions and train-only transforms. No neural model is justified by a few capture days.')
        st.write('Diagnostics available offline: session-weighted Brier/log loss and reliability bins, paired session loss intervals, all-attempt Holm correction, fixed-bin distribution drift. These are descriptive, not approval gates.')
        st.write('Options volatility models, regime learning and calibrated probabilities remain blocked until their own data and validation exist. Drift never triggers automatic retraining.')
    with tabs[3]:
        st.caption('LLM backend disabled: zero-cost deterministic evidence summary. The tested optional local-model adapter may select cited facts only; it cannot invent figures or authorize a trade.')
        explanation = state['llm']
        for fact in explanation['facts']:
            st.write(fact['text'])
            st.caption('Code evidence: ' + fact['source'])
        st.caption('No external model call, credential read or private-data prompt is made.')
