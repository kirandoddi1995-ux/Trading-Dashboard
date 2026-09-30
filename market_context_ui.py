"""Display-only panel; its return value is never consumed by trade evaluation."""
from datetime import datetime, timezone
import hashlib

import streamlit as st
import requests

from market_context import (bundle, canonical, latest, known, freshness, gift_overnight,
    vix_percentile, yield_change_bp, event_state, SECTOR_TAGS, stamp, number)
from market_context_sources import collect_quotes, import_manual, parse_participant_oi, IST


def render_market_context(token, vix_history=None):
    with st.expander('Market context — descriptive only, not a recommendation', expanded=False):
        st.caption('No trade votes, position sizing, entry permission or event blackout is produced here. '
                   'GIFT, US futures and Asian markets can reflect the same news, not independent confirmations.')
        st.warning('A missing calendar is UNKNOWN, not “no event risk”. Event warnings below do not enforce a trading blackout.')
        state_key = 'market_context_bundle'
        current = datetime.now(timezone.utc)
        if state_key not in st.session_state:
            st.session_state[state_key] = bundle([], current)

        def merge(incoming):
            records = {r['record_id']: r for r in st.session_state[state_key]['records']}
            records.update({r['record_id']: r for r in incoming['records']})
            combined = bundle(list(records.values()), current, incoming.get('issues', []))
            sources = {s['sha256']: s for s in st.session_state[state_key].get('source_files', [])}
            sources.update({s['sha256']: s for s in incoming.get('source_files', [])})
            combined['source_files'] = list(sources.values())
            canonical(combined)  # Bound the whole session before replacing it.
            st.session_state[state_key] = combined

        permitted = st.checkbox('Private research export is permitted by my data terms', key='context_terms')
        if st.button('Refresh Upstox context', disabled=not token or not permitted, key='context_refresh'):
            try:
                with requests.Session() as client:
                    merge(collect_quotes(client, token, vix_history=vix_history))
            except Exception:
                st.error('Context refresh failed. Existing records retain their original timestamps; check authentication/source access.')

        manual = st.file_uploader('Import dated official-source records or a context JSON export (1 MiB maximum)',
                                  type=['json'], key='context_import')
        if manual is not None:
            try:
                data = manual.getvalue()
                identity = hashlib.sha256(data).hexdigest()
                if identity != st.session_state.get('context_imported_sha'):
                    merge(import_manual(data, current))
                    st.session_state['context_imported_sha'] = identity
            except Exception:
                st.error('Import rejected: check schema, units, official-source URL and timezone-aware dates. No records were replaced.')
        st.caption('Manual values are not independently verified. Import stamps availability now, never at a claimed historical time.')
        oi = st.file_uploader('Optional original NSE participant-wise OI CSV', type=['csv'], key='context_oi_csv')
        oi_day = st.date_input('Report date printed in that OI file', value=current.astimezone(IST).date(), key='context_oi_day')
        if st.button('Read OI file', disabled=oi is None, key='context_read_oi'):
            try:
                merge(parse_participant_oi(oi.getvalue(), oi_day, current))
            except Exception:
                st.error('OI file rejected: report date, headers, participant coverage or totals do not match.')
        current = datetime.now(timezone.utc)  # Include observations received during the explicit refresh.
        packet = st.session_state[state_key]
        rows = packet['records']
        for issue in packet.get('issues', []):
            st.caption('Source status: '+issue)
        cards = st.columns(4)
        for column, kind, title in zip(cards, ('GIFT', 'VIX', 'GSEC10Y', 'USDINR'),
                                       ('GIFT indicator', 'India VIX', 'India 10Y yield', 'USD/INR / labelled proxy')):
            row = latest(rows, kind, current)
            column.metric(title, row['payload']['value'] if row else 'Unavailable')
            if row:
                column.caption(f"{row['unit']} · {freshness(row, current)} · source time {row['source_at']} · {row['origin']}")
                if row['payload'].get('proxy'):
                    column.caption(row['payload']['note'])
                if row['payload'].get('declared_latency'):
                    column.caption('Provider-declared latency: '+str(row['payload']['declared_latency']))
        gift = latest(rows, 'GIFT', current)
        bases = [r for r in known(rows, current) if r['kind'] == 'GIFT' and r['payload'].get('anchor') == 'INDIA_CLOSE']
        base = max(bases, key=lambda r: stamp(r['source_at'])) if bases else None
        move = gift_overnight(gift, base, current)
        st.write('Same-contract overnight GIFT move (%):', str(move) if move is not None else 'Unavailable — verified contract and session anchors required')
        vix = latest(rows, 'VIX', current)
        pct = vix_percentile(vix, rows, current)
        st.write('VIX trailing 252-session percentile:', f'{pct:.1f}' if pct is not None else 'Unavailable — insufficient distinct prior sessions')
        closes = [r for r in known(rows, current) if r['kind'] == 'VIX_CLOSE' and vix and stamp(r['source_at']) < stamp(vix['source_at'])]
        previous_vix = max(closes, key=lambda r: stamp(r['source_at'])) if closes else None
        st.write('VIX change versus last supplied completed close (points):',
                 str(number(vix['payload']['value'])-number(previous_vix['payload']['value'])) if vix and previous_vix else 'Unavailable')
        st.caption('VIX describes implied volatility, not direction. Percentile uses distinct supplied prior sessions; inspect gaps and stale inputs.')
        y = latest(rows, 'GSEC10Y', current)
        past = [r for r in known(rows, current) if r['kind'] == 'GSEC10Y' and y and stamp(r['source_at']) < stamp(y['source_at'])]
        bp = yield_change_bp(y, max(past, key=lambda r: stamp(r['source_at'])) if past else None, current)
        st.write('10Y yield change versus prior supplied observation (basis points):', str(bp) if bp is not None else 'Unavailable — matching benchmark required')
        st.caption('Yield differentials alone do not determine FII flows. Currency futures are not spot or reference fixes.')

        revisions = {}
        for row in sorted(known(rows, current), key=lambda r: stamp(r['available_at'])):
            if row['kind'] in {'EVENT', 'REBALANCE'}:
                revisions[(row['kind'], row['series'])] = row
        st.write('Dated events and index reviews')
        if not revisions:
            st.caption('Coverage unknown — no supplied calendar/rebalance records. No yearly meeting or review dates are guessed.')
        for row in revisions.values():
            state = event_state(row, current) if row['kind'] == 'EVENT' else (
                'ANNOUNCED_NOT_EFFECTIVE' if current < stamp(row['payload']['effective_at']) else 'EFFECTIVE_DATE_PASSED')
            st.write(row['series'], state, row['payload'])
            st.caption(f"Published {row['published_at']} · first known {row['available_at']} · {row['source_url']}")
        st.caption('RBI repo, stance, liquidity and press conference are separate records. Election counting stays unresolved until reviewed. '
                   'No automatic “resume in 15 minutes”. Rebalance demand estimates are not observed buying.')
        st.write('Participant OI — contracts, not directional exposure')
        oi_rows = [r for r in known(rows, current) if r['kind'] == 'PARTICIPANT_OI']
        if oi_rows:
            report_day = max(r['payload']['report_date'] for r in oi_rows)
            latest_participant = {}
            for r in sorted(oi_rows, key=lambda r: stamp(r['available_at'])):
                if r['payload']['report_date'] == report_day:
                    latest_participant[r['payload']['participant']] = r
            st.dataframe([dict(participant=r['payload']['participant'], report_date=report_day,
                              available_at=r['available_at'], freshness=freshness(r, current),
                              **r['payload']['counts']) for r in latest_participant.values()], hide_index=True)
        else:
            st.caption('No participant-wise OI file loaded. Existing FII/DII cash-flow data is not a substitute.')
        st.caption('Client ≠ retail. Futures shorts may be hedges; option contract counts are not delta exposure.')
        sector = st.selectbox('Qualitative sector exposure tags — no fitted weights', list(SECTOR_TAGS), key='context_sector')
        st.write(', '.join(SECTOR_TAGS[sector]))
        st.caption('These are exposure hypotheses, not scores, causal estimates or instructions to trade.')
        st.download_button('Download context JSON for private archival', canonical(packet),
                           file_name='market-context.json', mime='application/json', disabled=not permitted)
