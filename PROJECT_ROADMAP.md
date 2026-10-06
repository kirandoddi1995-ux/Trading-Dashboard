# Project roadmap: a trustworthy intraday NIFTY decision desk

Prepared 6 October 2026. This is a standalone assessment, not a migration,
deployment instruction or permission to trade. It reflects the local records and
owner reports available today; later measurements and commissioning results can
change the sequence. No existing project file was changed to create this document.

## Plain-language summary

I see this project becoming a private decision desk for Kiran's intraday NIFTY
futures and options trading: it should help him decide whether a trade is worth
considering, whether he can afford it, and when he must stop considering it.
It must also be comfortable saying **“no supported trade today.”** It never places
orders, and it must not pretend that a signal, a price touch or a backtest is a fill.

Today we have substantial infrastructure, working market connectivity, reproducible
research and useful safety checks. We do not yet have an end-to-end commissioned
F&O decision system or an established tradable edge. Storage is urgently tight;
forward capture has not completed its first automatic day; derivative safeguards
are mostly dormant; costs and broker behaviour still need real verification.

My order is: make the existing system sustainable, obtain dependable evidence,
verify the economics, test a small frozen set of ideas, and only then expose
bounded actionable suggestions with independent monitoring. Building more signals
before these steps would increase apparent capability faster than actual reliability.

## 1. What I think the project should become

The finished app should answer five practical questions without making Kiran read
logs or understand database internals:

1. **Can I trust today's inputs?** Show market/session status, data age, missing
   information and whether the collector, database and independent monitor are healthy.
2. **Is there a supported opportunity?** Explain the completed-bar rule, direction,
   relevant contract and evidence supporting it. Clearly distinguish research from
   suggestions that passed the approved policy.
3. **Does it still make sense after costs?** Show estimated rupee charges, spread
   and slippage uncertainty, and the evidence behind the estimate. An attractive
   gross move must not masquerade as a net opportunity.
4. **Can this account safely consider it?** Show whole-lot affordability, premium
   commitment or required margin, risk-budget constraints and concentration. Margin
   is funding, not a maximum-loss guarantee. A useful research idea may be unaffordable.
5. **What ends the idea or requires attention?** Show reversal/invalidation,
   the reviewed intraday exit deadline, stale-data warnings and position-monitor
   alerts. Kiran acts at the broker; the app cannot guarantee an exit or enforce
   “never overnight” merely by displaying a deadline.

Behind that simple screen, each suggestion should be traceable to its original
inputs, rule version, costs, checks and subsequent observations. Restoring archived
evidence must be demonstrated, not merely described. Releases should be checked
before deployment, and failures should reach the owner even when the app is asleep.

My honest view: the engineering can deliver a dependable research and decision
system; it cannot promise a profitable strategy. The two tested directional rules
have not established an edge even before costs. A finished system that rejects
those rules and records why is a success, not an unfinished trading system.

Equities, mutual funds and market-context tiles are supporting features, not the
critical path for intraday NIFTY F&O. They should not consume unlimited storage or
drive the roadmap simply because they were built first. That does not authorize
discarding their evidence or breaking existing readers.

## 2. How the parts fit together today

There is not yet one continuous pipeline. There are several lanes, with different
levels of verification and some missing connections between them.

### A. The live dashboard

Upstox REST/websocket → app adapters and local caches → price/session/indicator
checks plus governance and derivative preflight → Streamlit → market readings,
research context, scan results and explicit blockers.

REST/TLS and streaming have been observed working. Daily equity setups and
intraday F&O calculations are separate; daily equity win rates are not F&O evidence.
The NIFTY index itself does not provide traded-volume confirmation. Some volume
logic remains a labelled heuristic, not a validated time-of-day participation model.
USD/INR was last reported unusable; that tile must remain unavailable rather than
being treated as a valid market input.

Scan/checkpoint and evidence writes → local ledger/outbox → asynchronous delivery
→ Supabase → recovery/readiness displays and retained audit evidence.

A scan can finish locally before remote acknowledgements arrive. The owner has
observed pending delivery draining later. That is not the same as unfinished
analysis. However, the scan's own backlog can still trigger READ_ONLY for later
candidates; sustainable delivery and consistent gating need commissioning, not
just a larger threshold.

### B. Existing collection and archival

Upstox and other existing equity/NAV sources → scheduled collectors → Supabase
quotes, universe snapshots, observations and outcomes → verified private Drive
export → exact reviewed row matching before eligible deletion.

This archive path has run successfully for its supported sources. It is not yet
a complete retention system for every growing table. The ledger especially needs
preserved signatures, chain boundaries and working readers before any hot history
can be removed. Deletion/vacuum can create reusable space within one relation
without making that space available to another or shrinking the cluster.

The 89 equity research horizons completed, but coverage did not become complete
for every outcome. Completion of elapsed time is not complete observation, and
price touches are not net F&O returns. Deduplication and summaries help preserve
that distinction; the evidence is not automatically upgraded.

### C. Historical research

Upstox NIFTY five-minute/daily downloads → private local files → verified session
calendar and previous-close checks → development-only export → frozen registered
recipe → deterministic replay → research reports, not live approval.

The owner reproduced the 2022–2024 results trade by trade. The historical split is
2022–2024 development, 2025 validation, 2026 holdout. The last two remain unexamined.
The two development rules are parked: their session-clustered intervals include
zero before costs. Reproducibility establishes consistent calculations, not
independent price truth or profitability. No historical option book has been created.

### D. Forward collection: two different tools

Official NSE prior close + Upstox underlying bars → Windows prepare/poll/audit
tasks → private local journal/input bundles → verified private Drive backups
→ eventual observed-input replay comparison.

This is underlying directional evidence, not executable options or futures P&L.
On 6 October preparation failed, no session recipe was published and polls blocked.
A new source request timed out; the original failure cause is not proven. The
diagnostic repair is staged, not installed. Today's lost observations stay missing.

Upstox option feed → explicitly authorised GitHub pilot at a bounded slot →
timestamp/age/skew/scope checks → private Drive snapshot → capture/audit receipt.

The owner observed an on-time pilot with 47 rows and exit 0. That verifies a bounded
capture path, not continuous session coverage. Four snapshots a day cannot replay
five-minute option decisions and intervening exits. The continuous quote recorder
remains a proposed next tool, not an existing commissioned feed.

### E. Derivative safety and economic checks

Reviewed contract/master/rule/ban sources + broker positions/policies → restricted
derivative tables and monitor → preflight/cost/margin checks → permitted research
or blocked proposal.

The modules and review drafts exist, but all nine hosted derivative tables were
absent at the latest inventory. Costs and futures-history tools exist locally;
complete dated tariff/account-plan reconciliation, historical contract data and
real margin commissioning are unfinished. Installing empty tables fixes an absent
table error; it does not supply the missing evidence or turn the safeguards on.

### F. How code reaches the app

Reviewed local files → owner upload to main → checks for the exact commit → checked
release-branch promotion → Streamlit deployment → independent build/policy/code
expectations and runtime health.

The release cutover and corrected configuration have been observed working.
Research/capture workflows remain on main and the PC tasks still load the editable
local workspace. They do not automatically inherit the dashboard's release isolation.
Large green test counts are valuable, but they do not prove hosted permissions,
provider availability, broker behaviour, archive restoration or trading efficacy.

## 3. The road ahead, as a chain

Protect and recover → dependable data → verified economics → development research
→ untouched validation and forward shadow evidence → commissioned safeguards
→ supervised decision pilot → reliable everyday app.

This is an acceptance chain, not a demand to finish each line before starting any
parallel design. Costs can be researched while storage is repaired; monitoring
can be built alongside research. Nothing skips its prerequisites for live use.

### Stage 1 — Protect storage and make recovery real

Delivers: a bounded operational database, evidence-preserving cold storage, working
archive readers, demonstrated restores and alerts before capacity is exhausted.
Needs: fresh inventories, protected reader/chain dependencies and owner-reviewed
changes. Blocked by very thin headroom and incomplete all-writer admission,
archival integration and recovery commissioning.

Start with existing reviewed NAV relief and ordinary maintenance, then finish the
permanent storage work. On 6 October at 09:47 IST the cluster was 494,377,781 bytes,
about 5.62 MB below the nominal 500 MB limit. This is a dated measurement, not a
forecast or safe reserve. A proposed steady-state budget is not yet achieved.

### Stage 2 — Commission dependable data, without growing Supabase history

Delivers: a successful supervised forward day, missing-run detection, verified
private backups and a capture installation that cannot change under running tasks.
Needs: Stage 1 for new database ingestion; source access, licence/entitlement checks,
stable code/dependencies and an awake maintained PC or approved persistent host.
Blocked by today's preparation failure and unproven full-day capture/recovery.

Keep raw bars/books in private Drive with a local spool, not public GitHub or
Supabase. After the snapshot pilot, measure continuous option recording and feed
connection limits before committing to it. Prove expired development-period
futures history before any bulk acquisition; otherwise futures P&L stays unknown.

### Stage 3 — Commission costs, contracts and account constraints

Delivers: dated rupee charge estimates, exact contract lot/tick/expiry terms,
reviewed intraday deadlines and genuine current-basket margin checks.
Needs: retained official sources, actual account-plan evidence and broker-response
reconciliation. Blocked by incomplete dated fees, unconfirmed brokerage and actual
margin/deadline behaviour. Much of this review can proceed alongside Stages 1–2.

Freeze execution assumptions before research: fills are not inferred from candle
closes, roll changes are not trading profits, and current margin does not establish
historical margin. Keep one-lot research separate from Kiran's affordable sizing.

### Stage 4 — Run a small, frozen development research round

Delivers: a documented verdict on a limited candidate set after costs and execution
stress, with all attempts and exclusions retained.
Needs: Stages 2–3 evidence for the instrument being tested, a preregistered protocol,
causal completed-bar inputs and uncertainty/search controls. Blocked by economic
and futures/option execution-data gaps, not by a shortage of indicator ideas.

The existing rules stay parked. New rules are new hypotheses, not repairs to make
old results pass. All 2022–2024 has already been examined; an internal resplit is
exploratory, not a fresh untouched test. Stop if no candidate survives.

### Stage 5 — Validate once, then assess forward shadow evidence

Delivers: evidence that a frozen candidate survives beyond development, and that
observed-input live calculations agree with replay of those same inputs.
Needs: a justified development result, approved evaluation protocol and sufficient
quality/independent sessions. Blocked until those prerequisites exist. 2025 and
2026 are not opened automatically, nor used to solve historical data-access gaps.

Use 2025 only for an explicitly approved validation round; preserve 2026 as final
holdout until authorised. Newly frozen prospective capture is separately labelled;
it does not grant permission to mine historical 2026 performance. Failures are
reported, not tuned away. Forward snapshots and simulated fills are not genuine
broker execution evidence and cannot populate gates that require it.

### Stage 6 — Commission derivative safeguards and independent monitoring

Delivers: real restricted tables, current reviewed references, fresh preflight,
position reconciliation, working alerts and a watchdog independent of the app.
Needs: safe storage/retention, owner-applied migrations, verified host access,
broker instructions and supervised failure drills. Blocked by absent tables,
unpopulated rules and uncommissioned host/email/watchdog access.

Begin implementation/testing in parallel with research once storage allows;
completion is a hard prerequisite for real F&O positions supported by the app.
NIFTY-only intraday scope should stay narrow. Overnight/settlement safeguards
remain useful for failed exits, but are not a reason to expand the trading mandate.

### Stage 7 — Integrate and supervise the decision-support pilot

Delivers: one traceable path from data to candidate to net economics to account
eligibility to screen, with clear no-trade reasons and independent monitoring.
Needs: all relevant research, model, risk, execution-evidence and operational gates
actually satisfied. Blocked by any remaining missing evidence; a successful recorder
or monitor alone cannot authorise a strategy. This pilot never places orders.

Start in shadow/manual-review mode. Prove live/replay consistency, stale-feed and
token failure handling, delivery lag behaviour, reviewed exit timing and restoration.
Integrate the chosen frozen strategy explicitly: the research adapter is not
automatically equivalent to every input used by the dashboard's bias engine.

### Finished app — reliable daily operation

Delivers: a simple trustworthy screen, bounded ongoing storage, checked releases,
actionable alerts and a repeatable review process. Needs sustained operation across
ordinary and awkward sessions, not one green CI run or a fixed number of pilot days.
Only individually commissioned instruments and strategies appear as supported.

The owner remains responsible for broker execution, source/account decisions and
reviewed releases. Automation collects, verifies, reproduces and alerts; it never
retunes rules, fabricates missing observations or loosens a gate to obtain a trade.

## 4. Main blockers and what clears them

- **Capacity:** verified existing relief buys relation-local reuse; complete bounded
  storage, restores and transaction-level admission clear the structural problem.
  No promise of physical shrink. Keep derivatives held until measured reserve exists.
- **Capture reliability:** install the staged diagnostic repair during maintenance,
  obtain genuine pre-open preparation, supervise polls and audit, then isolate a
  frozen capture installation. A PC timer being enabled is not proof of collection.
- **Execution-quality data:** commission continuous bid/ask capture for options;
  establish expired futures entitlement/depth for historical futures research.
  If unavailable, restrict the conclusion rather than manufacture executable prices.
- **Economics/account evidence:** complete dated charge and contract records;
  privately reconcile broker plan, notes, margin responses and square-off instructions.
- **No established edge:** preregister a small new research round only after its
  inputs are ready. Better infrastructure cannot turn near-zero development results
  into a profitable strategy. No tradable edge remains an acceptable conclusion.
- **Dormant safety/alerts:** install reviewed schemas only with capacity, supply real
  references and commission monitor/watchdog, including token, database and mail failures.
- **Operational coupling:** separate task-loaded capture code from active development,
  commission sustainable outbox delivery, and distinguish service health from trading
  approval. Do not solve late-candidate READ_ONLY by simply raising a threshold.
- **Owner-dependent setup:** accounts, licences, privately stored credentials,
  migrations and host/settings changes need owner action. Prepare bounded checklists;
  do not make them invisible prerequisites or ask for credentials in chat.

## 5. My priorities, uncertainties and decisions needed from you

My immediate priority is sustainable storage and trustworthy capture, not additional
signals. Costs/source review is the best parallel lane. I would initially retain
one bounded Supabase operational store and private Drive history, rather than add
a second database solely to postpone retention work. If protected data cannot fit
safely or availability requires separation, bring that decision back with measured
evidence. No new host, paid plan or data purchase is assumed here.

I am not certain that the proposed storage budget is physically achievable, that
NSE access will be reliable from this PC, that older futures history is obtainable,
or that any candidate will produce a cost-surviving edge. Earlier work moved fast;
transport integration defects and generic diagnostics showed where tests missed
real behaviour. The full suite's latest recorded 2,114 passes are encouraging,
not a production-readiness certificate. Some old design notes contain superseded
status statements; this roadmap prioritises later progress and actual owner results.

Decisions/action needed now:

1. Approve and perform the already prepared storage-relief/maintenance steps, and
   choose a stopped-task window for capture repair. Preserve the failed day's evidence.
2. Confirm that capture should move to a frozen owner-installed directory before
   more unattended days; choose who maintains the awake PC. An always-on host is a
   later availability decision, not assumed spending.

Needed before economic/safety commissioning, not to continue offline engineering:

3. Privately confirm Kiran's broker plan, capital/risk settings and intraday product;
   provide reviewed non-sensitive conclusions, not tokens or raw account documents.
4. Confirm data-retention rights and whether expired futures access is actually
   available. If not, decide whether to keep spot-only research or investigate an
   approved alternative. No purchase or holdout access is implied.
5. Select/approve the independent monitor and alert host/channel when its checklist
   is ready. Keep operational alerts separate from trade suggestions.

No strategy choice, validation unsealing or live-trade permission is requested now.
Those decisions belong after the prerequisites above, not at the start of the chain.

## Local basis for this assessment

The primary continuity source is AUTOMATION_PROGRESS.md, read through the latest
6 October capture/storage checkpoint. Supporting local documents include
CAPTURE_MORNING_REPAIR_2026-10-06.md, PERMANENT_STORAGE_DESIGN.md,
STORAGE_FIRST_RELIEF.md, FORWARD_DATA_RUNBOOK.md, NEXT_INTRADAY_RESEARCH_ROUND.md,
FUTURES_COST_DATA_COMMISSIONING.md, INTRADAY_FO_COSTS.md,
DERIVATIVE_PILOT_COMMISSIONING.md, DERIVATIVE_MONITOR_REVIEW.md,
INTRADAY_OPTION_REPLAY_SPEC.md and DASHBOARD_RELEASE_RUNBOOK.md.
“Automated backtesting and self checks.md” informs the direction, but its proposed
order, platforms, statistical targets and agent automation are not adopted as mandates.

This document required no new hosted check, no market-data examination, no code
change and no edit to the continuity record or any other existing file.
