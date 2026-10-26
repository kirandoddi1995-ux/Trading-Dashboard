"""Opt-in, read-only equity study panel; real data remains unconnected."""
from __future__ import annotations

import json
from typing import Any, cast


def render_equity_eod_study(st: Any) -> None:
    st.subheader("Equity EOD Development Study — 2022–2024")
    st.warning("REAL STUDY NOT RUN — no admitted market data or accuracy result.")
    st.caption("First segment: cash equities. Existing scanner formulas and capture are unchanged. No orders, training or automatic tuning.")
    try:
        from equity_eod_study import readiness, rehearsal, validate_rehearsal
        with st.expander("What the first real report needs"):
            state = readiness()
            for requirement in cast(list[str], state["requirements"]):
                st.write(requirement)
        st.write("The rehearsal below explains the existing opening-gap rules and cost sensitivity using invented arithmetic examples, not historical prices.")
        key = "equity_eod_generated_rehearsal"
        if st.button("Run synthetic equity EOD report rehearsal", key="equity_eod_rehearse"):
            st.session_state[key] = rehearsal()
        value = st.session_state.get(key)
        if value is not None:
            report = validate_rehearsal(value)
            st.warning("SYNTHETIC ONLY — these results are not returns from any Indian stock or index.")
            st.caption("30 bps means a 0.30% round-trip cost assumption. The three cost levels are stresses, not verified charges. Each row is an independent artificial example, not a portfolio.")
            st.dataframe(report["payload"]["rows"], hide_index=True)
            for limitation in report["payload"]["limitations"]:
                st.write(limitation)
            with st.expander("Exact generated report and reproducibility hash"):
                st.json(report)
            st.download_button("Download synthetic equity report", json.dumps(report, sort_keys=True, allow_nan=False),
                               file_name="synthetic-equity-eod-rehearsal.json", mime="application/json",
                               key="equity_eod_download")
    except Exception:
        st.error("EQUITY_STUDY_REVIEW_REQUIRED — no raw error or private data displayed.")
