# Stage-2 shadow maturation (Phase 5), 11 Nov 2026

Shadow-only. Never places, sizes or recommends an order. Off unless the repository variable
`SCHEDULED_STAGE2_MATURATION` is `1`.

## Why
- The scheduled scans record Stage-2 shadow decisions (`equity-stage2-scheduled-shadow-v1`, see
  `AUTO_STAGE2_COLLECTOR_2026-11-10.md`), but nothing measures what happened after them.
- The existing maturation (`scheduled_collector.update_matured_targets`) labels only app decisions with a
  `DECISION_EVALUATED` event, and only in `close` mode; pg_cron job `collector-close-1545-ist` has been
  inactive since 5 Oct. `prediction_targets` holds 0 rows: no decision has ever been matured.
- 11 Nov: all 39 shadow passes were Watch. Their stops sit 12-39% below entry because
  `derive_long_trade_levels` takes min(entry - 1.5 ATR, 20-day low - 0.15 ATR). Deciding whether that
  rule (or the score threshold) is wrong needs outcomes, not opinions.

## What changes
- New `equity_stage2_maturation.py`. In each scan run, after the shadow Stage-2 step, it labels every
  shadow pass 22 to 60 days old that is missing a label, under two frozen level policies. Selection: a cheap
  id query finds every pending pass; the NIFTY bars (fetched once) say which have completed 15 sessions; only
  those take one of the run's 60 slots, so passes still waiting (holiday clusters) never crowd completed ones
  out. Half the slots go to the newest completed passes, half to the oldest of the rest (ties within a day
  reshuffled daily): new passes never wait behind ones that stay unlabelled, the ones closest to their
  60-day expiry go first, and a block of same-day passes that stays unlabelled cannot hold the same slots
  every day. Policies:
  - `incumbent-levels-v1`: the recorded stop and target;
  - `atr15-stop-v1`: stop = entry - 1.5 ATR, target from the same target logic (`levels_for_stop`,
    differential-tested against `derive_long_trade_levels`).
  Inputs (ATR, resistance levels, decision time, estimated costs) come from the decision's own ledger batch.
- Label version `net-excess-app-contract-v1` (13 Nov; replaces `net-excess-execution-v2.minute-aligned-v1`,
  which never stored a label): the app's own trade plan (`trade_contracts.build_trade_timing`, shown with every
  decision: "enter only during [decision, +15 min]; exit at target/stop, otherwise no later than 15:15 on the
  15th session"), executed on the stock's one-minute bars, net of the decision's cost estimate:
  - entry: the open of the first minute bar that starts after the decision time and within the entry window
    the app showed (recorded with the decision; 15 minutes, never past 15:15) on the decision day. No such bar
    = no trade (`no_fill`), never a later day;
  - exit: the first bar reaching the stop (stop first when one bar reaches both; filled at the bar's open when
    it opened below the stop, a gap through it) or the target (filled at the target, conservative), else the
    time exit at 15:15 on the 15th regular session after the decision day (the app counts weekdays; NIFTY's
    bars apply holidays; special sessions from `nifty_session_calendar.SPECIAL`, such as Muhurat, never count,
    though their bars stay on the minute path): the open of the first bar from 15:15, or the close of the last
    bar before it, either within 5 minutes of 15:15 (else `window_problem`: never an exit hours early);
  - evidence: every session of that window needs the stock's daily bar (no daily and no minute bar:
    `no_trading`, counted, quiet, a suspension; a daily bar missing while minutes traded is a data gap,
    reported) and valid minute bars (unique, ordered, finite, positive, consistent OHLC; else
    `window_problem`, reported), and on each session up to the outcome the minutes and the daily bar must
    agree on whether each level was reached (else `window_problem`, reported: a touch only one feed shows);
  - NIFTY over the same minutes: from the open of the entry minute to the open of the exit minute when the
    stock exits at a bar's open (15:15 time exit, gap stop), else to the close of the exit minute (a stop or
    target inside the bar, a last-close time exit); each NIFTY minute at most 5 minutes away, never reversed;
  - both policies are labelled from one fetch and stored together, or not at all: a missing NIFTY window for
    either (`no_benchmark`) retries both, so which policy gets labelled never depends on a NIFTY gap and a pair
    never mixes two fetches. Only a policy whose levels are invalid, or that the actual entry price is not
    strictly inside (`outside_levels`), is skipped alone (that never changes on a retry);
  - selection and label window agree (one regular-session count); the report's eligibility counts shadow-scan
    days, so a special session can only make it wait longer, never call a decision eligible early.
  Why not the production label (`prediction_validation.compute_forward_target`, `net-excess-execution-v2`,
  unchanged, used by the inactive close mode): it reads minute bars only on days whose daily bar shows a touch
  (a minute-only stop is missed), lets an in-session entry slip to a later day when the decision day's minutes
  run out, ends a time exit at the 14th session's close for an in-session entry while selection waited for the
  15th, and its NIFTY window starts at 09:15. ChatGPT's independent review (13 Nov, prompt 65) found these;
  Claude reproduced each on main `fa7fd21`.
- Price basis (added 12 Nov, branch `stage2-corporate-action-guard`). The recorded entry, stop and target are
  on the decision day's price basis, but Upstox history is back-adjusted to the day it is fetched (the Aug
  2025 HDFCBANK bonus shows in 2022 bars, research 3 Nov). A split, bonus, rights issue or large dividend in
  between makes the levels meaningless against the fetched bars (a 1:1 bonus halves the history: every stop
  looks hit). Two fail-closed guards:
  - events: the stock's Upstox corporate actions (`/v2/fundamentals/{isin}/corporate-actions`, the endpoint
    the close-mode archive already used: 1,162 ISINs answered 200, 523 empty), one request per stock per run,
    before any history request. Held back (`corporate_action`) when any action except a dividend below 2% of
    the entry (amount > 0) has any ex-date (`ex_date`, `expiry_date`, every "Ex ... date" detail; a dash or
    "NA" is no date) after the decision day and on or before the run day (an ex-date after the window still
    shifts it, because the history is adjusted to the fetch day); any type naming a dividend ("Interim
    Dividend") is a dividend. What cannot be read, or a type other than
    Dividend, Bonus, Split and Rights Issue, holds it back and is reported (`unreadable_action`, run PARTIAL
    with the reason, so a renamed Upstox field or a new type cannot hold decisions back unseen): an action that
    is not an object, one in the window without a type or of an unknown type, a dividend in the window without
    a readable amount (missing, not a number, negative), or an unparsable ex-date when no ex-date in the window
    is readable; a small dividend is skipped only when all its dates are readable and, if one lies in the
    window, they agree (otherwise reported; dates that all lie outside the window do not matter), and a `null`
    actions list is an unreadable answer (Upstox sends `[]` for none: 233 of 563 stored
    answers, 0 null). Measured on the 464 stored actions of 330 ISINs (`feature_observations`, 12 Nov): only those
    4 types, every action dated, every "Ex ... date" detail equal to its `expiry_date`, so 0 reported. A non-200 or non-`success` answer is a failure, never a pass (asked once
    per stock per run, even when it fails). The held-back stock's actions are archived in `corporate_actions`
    (the close-mode archive's writer; the runtime role has INSERT/SELECT/UPDATE, no RLS on that table) and
    the pending query leaves out passes with an archived Bonus, Split or Rights Issue in that window: a
    terminal mark, so most take no later slot or request (exceptions in Limits). An archived action of any
    other type (also from the close-mode archive) does not exclude: the pass is held back and reported each
    run until it is 60 days old, so a new type never drops passes unseen;
  - basis (`basis_mismatch`): both histories must hold the decision day with the recorded entry (the scan's
    own quote, or its last close when it had none) inside its range (0.5%); the minutes' decision-day low and
    high must equal the daily bar's (0.5%: the entry and exit order come from the minutes, the anchor below
    checks the daily feed); and one of the 2 daily bars before the decision day (2: a scan feed
    one session behind still matches) must equal the scan's own last completed bar (`latest_indicators`
    Open/High/Low within 0.1%; the close is left out: AVTNPL's 10 Nov close is 100.14 on Upstox, 100.31
    elsewhere, O/H/L identical, so sources and revisions differ on it). A rescale above 0.1% fails that match
    whatever its factor (a 3% demerger factor inside the day's range is caught), so events the feed does not
    list are caught whenever the provider adjusted them. A pass without a readable bar is a mismatch, not a
    pass (all 93 live passes on 11-12 Nov carry it). Each mismatch is logged with its reason, and any mismatch
    makes the run PARTIAL with the reasons in the quality event (so a false positive is loud on the first
    labelling run, about 3 Dec; nothing is stored for it). Daily history now starts 10 days before the
    decision day.
  - the archive write is best effort: if it fails the decision is still held back this run (and asked again
    next run); a lost lease stops the run before the write.
- Storage: append-only `prediction_targets` rows (immutable by trigger), `target_version`
  `stage2-shadow:net-excess-app-contract-v1:<policy>`. The app's calibration, readiness count and training read
  `net-excess-execution-v2` only, so they never see these. No new table, grant or policy: the runtime role
  already has SELECT/INSERT on `prediction_targets` (policy `archive_preserve_runtime`, checked 11 Nov).
  About 2 rows per pass (~39 passes per trading day today).
- Upstox: 1 NIFTY daily request per run; per stock-day 1 daily + 1 one-minute request (ending at the
  exit session; both scans of a stock-day share them); 1 NIFTY one-minute request per decision
  window (shared by every stock with that window); 1 corporate-actions request per stock; each after a 0.2 s
  pause; at most 60 decisions (241 requests) and 300 s per run (checked between decisions; a budget stop makes the run PARTIAL, the rest is
  retried). With the shadow step's 151 requests a scan stays below half of Upstox's documented 1000 requests
  per 30 minutes per API (25/s, 250/min); capacity 120
  decisions a day against ~39 new passes a day. A lost lease stops the run before any write; a
  rejected token stops it as FAILED; any other failure is contained (quality event
  `STAGE2_MATURATION_FAILED`, WARNING; ERROR when FAILED) and makes the run PARTIAL; a malformed row is
  one counted failure, never a stopped run; an empty NIFTY answer stops the run as FAILED before any stock
  request, and so does a stale one (last bar older than 6 days); an empty stock answer is deferred (no minute
  request); an HTTP
  4xx on one instrument's daily request (dead key) is counted as `provider_rejected`, not a failure (a 4xx on
    the minute request stays a failure, so a broken endpoint cannot look like SUCCESS); NIFTY evidence missing for
  a holding window (no minute within 5 minutes of entry or exit) is counted as `no_benchmark` (once per decision);
  the label's own reasons are counted as `no_fill`, `no_trading`, `outside_levels` (quiet) and `window_problem`
  (reported, PARTIAL); an empty NIFTY minute answer is a failure (a broken feed must not look healthy). Unlabelled
  decisions (incomplete or ambiguous evidence) are retried by later runs until 60 days old. The run summary
  also shows the true backlog (`pending`), `awaiting_sessions` and `selected`.
- `scheduled_collector.py`: one call after the shadow step, its rows in `record_count`, PARTIAL/FAILED
  makes the run PARTIAL. Workflow passes `vars.SCHEDULED_STAGE2_MATURATION`.
- New read-only `sql/stage2_shadow_outcomes_report.sql`: per policy, recorded action (Buy/Watch) and score
  band; a stock that passed in both scans of a day counts once (its earliest scan, chosen before labels are
  looked at); a decision is eligible once 15 sessions of the shadow scan follow it (the database has no NSE
  calendar; a missed scan only delays eligibility) or any pass of its day is labelled (a label proves NIFTY
  completed that day's horizon, so coverage is never judged on labelled passes alone); `eligible` vs `labelled` coverage (a decision missing from its ledger batch still counts, action
  `unknown`); sample `paired` = decisions labelled under both policies (the like-for-like comparison); IST
  dates; one label version and horizon 15 only.

## Why not a DECISION_EVALUATED event per pass
The spec's other Phase 5 option. Rejected: the app's `pending_observations` would pick those passes up and
write production-version (`net-excess-execution-v2`) labels into the app's own calibration evidence, and
each event adds about 5 KB of ledger that is never deleted. Shadow labels stay in their own versions.

## Owner steps
1. Merge.
2. GitHub, Settings, Secrets and variables, Actions, Variables: add `SCHEDULED_STAGE2_MATURATION` = `1`.
3. First labels: about 3 weeks after the first shadow day (11 Nov), i.e. from about 2-3 Dec 2026.
4. Results: run `sql/stage2_shadow_outcomes_report.sql` in the Supabase SQL editor (read-only).

## Rollback
Delete the repository variable (or set it to `0`): the next run skips maturation entirely. Stored labels are
evidence and stay (append-only).

## Review (11 Nov)
Independent adversarial reviewer on the first version: no blocker, 4 major + 11 minor, 15 of 40 mutants
survived. Fixed: newest-first order (stuck rows starved new ones), per-row parse inside the error handling,
report decisions chosen before labels + coverage + paired sample, gap-through stop fill, empty stock answer
deferred, empty/partial NIFTY not stored, window 22 days, one minute request ending at the horizon, per-run
history cache, lease-checked quality event, WARNING/ERROR severity, match by decision_id, report pinned to
one label version, 0-bps cost kept.
Second pass: no blocker, 1 new major (incomplete passes filled the 60-row cap; simulated on the 2026 NSE
calendar, 8% of labellable decisions would expire around holiday clusters) + 4 minor, 8 of 46 mutants
survived. Fixed: completion decided on NIFTY sessions before the cap (above), HTTP 4xx per instrument not a
run failure, NIFTY gaps counted, report keeps decisions missing from the ledger and pins horizon 15, IST date,
NaN open guarded; tests added for the 6 test-gap survivors. Final mutation set: 46 of 47 killed (the survivor,
minute bars cut at the run day, is equivalent: minutes are only fetched up to the horizon's last session).
Third pass: no blocker, no major; 3 minor. Fixed: provider rejection limited to the daily request, stale NIFTY
fails the run, tests for the NaN-open guard and a deleted batch event. Not changed (documented): a permanent
defect in one row (missing ledger entry, malformed row, persistent 5xx) makes every run PARTIAL with a WARNING
until the row is 60 days old.
Bot review on PR #87 (12 Nov; CodeRabbit, CodeAnt, MergeHarbor, Graphify), each finding reproduced on the
first commit before fixing: NIFTY window misaligned with the minute entry and exit (+1% NIFTY first hour
showed as -1% excess; a stop's benchmark ran to that day's close) -> NIFTY one-minute holding window, label
version renamed (nothing was ever stored under the old one); a block of newer unlabelled passes could
starve older ones -> half newest, half oldest with ties reshuffled daily (Gemini notebook: "oldest half"
alone fails when more than 30 stuck passes share the oldest date; the reviewer's simulation showed a plain
rotating window lets 153 of 1,950 backlog decisions expire, this rule 0); a budget stop left the run SUCCESS -> PARTIAL; a 0 open gave a
-100% gap fill -> no label; the report counted 22 calendar days as complete -> 15 scan sessions or a label.
Second adversarial review of the fix: no blocker, 4 minor, all fixed: the rotation above; an empty NIFTY
minute answer left the run SUCCESS (now a failure); NIFTY minute gaps could stretch or reverse the window
(now within 5 minutes and ordered); report eligibility was per pass, not per day. `scan_sessions` and
`labelled_days` are MATERIALIZED (6.5k decisions in PGlite: 0.3 s vs 18.7 s inlined). Tests added for the 14
surviving mutants it listed (exact NIFTY window, daily close for time exits, window sharing, run date,
session and label decoys in SQL). Direct tests added for `_guard`, `_mature_one` and the execution adjustment. Not changed: the switch accepts
`1/true/yes/on` like the shadow Stage-2 switch (all explicit opt-ins); Graphify coupling notes are advisory.

## Review of the price-basis guard (12 Nov)
First adversarial pass: no blocker, 1 major (a held-back decision was asked again every run until it aged
out, taking slots and requests) + 5 minor. Fixed: the terminal mark (archive + pending-query exclusion),
failed answers cached per stock, `status` checked, every "Ex ... date" detail read, dividend amount > 0.
Second pass: no blocker, 1 major (a basis mismatch was only counted, so a systematically wrong anchor would
hold every decision back in silence) + 2 minor + nits. Fixed: mismatches make the run PARTIAL with reasons;
the archive write is best effort and lease-checked; a missing anchor is a mismatch; the anchor compares
O/H/L over the 2 bars before the decision day; ex-date labels with hyphens or no type word. Not measurable
here (Upstox is not reachable from the review sandbox): the anchor's and the minute/daily range check's
false-positive rates on live data (the pre-open auction open against the 09:15 minute, missing minutes on
illiquid stocks; 0.5% should absorb ordinary cases, a news-day auction gap may not); the PARTIAL run makes
either visible on the first labelling run. Targeted mutants for both passes' fixes: all killed.
Third pass: no blocker, 1 major (the fail-closed hold-backs on unreadable data, a renamed `amount` or a dash
in a date, were as silent as round 2's mismatches and never terminal: a schema change would hold back every
stock with any action, run SUCCESS) + 2 minor + 3 nits. Fixed: unreadable hold-backs make the run PARTIAL with
reasons (`unreadable_action`), a dash or "NA" is no date, a readable in-window date wins over an unreadable
one; the minutes' decision-day range must equal the daily bar's (a minute-only x0.97 rescale was labelled);
docs (archive date order, entry fallback, the in-window detail date in Limits); tests for the 4 surviving
mutants (top-level `ex_date`, a 0.11% rescale, a zero anchor price, an upper-case DIVIDEND). Round-3 mutants:
20 of 20 killed.
Fourth pass: no blocker, no major; 2 minor + 2 nits. Fixed: a type naming a dividend ("Interim Dividend")
was held back as a non-dividend in silence and then excluded for good by the pending query -> dividend matched
inside the type name in both, and a type outside the 4 known ones is reported; unreadable/undated rows
measured on stored payloads (0 of 464); the range check's live rate listed as not measurable; doc wording;
`nil/null/none` placeholders tested. Mutants: 5 of 5 killed.
PR #88 bots: CodeRabbit (minor, fixed) - the pending query also excluded passes for an archived action of
an unknown type, which the close-mode archive can write, so such a pass was dropped without a report ->
only Bonus, Split and Rights Issue exclude now. Not changed: CodeRabbit's "archive the accepted ex-date" (cost
only, 0 of 464 stored actions affected, the writer is shared close-mode code; in Limits), CodeAnt's
cancelled-action note (in Limits), MergeHarbor's 3 test gaps (coverage: `_held_back`, `_basis_event`,
`_ex_dates` 100% of statements run by this file's tests).
Gemini notebook second opinion (12 points): no new defect. Covered already: ISIN change on a split, an
ex-date on D or D-1, demerger gaps (fail closed), the terminal mark, the request budget (241 + 151 per scan);
under T+1 the ex-date is the record date. Added to Limits: actions without a readable ex-date are re-checked
like large dividends. Kept: a basis mismatch makes the run PARTIAL (round 2's major); if live mismatches
are frequent, review the anchor tolerance before that becomes noise.

## Label successor (13 Nov): ChatGPT's independent review, prompt 65
ChatGPT (independent checker, synthetic probes on PR #88's head) found: a minute stop missed when the daily
range disagrees; an in-session entry slipping to the next day; an in-session time exit after the 14th session
while selection waits for the 15th; a retry pairing labels from different fetches; a NIFTY gap deciding which
policy survives. Claude reproduced the first four on main `fa7fd21` (no shadow label was stored yet: 0 rows).
Fixed here by the new label version (above). From ChatGPT's private guard candidate: finite positive
decision-day bounds, a `null` actions list as unreadable, the small-dividend skip only with one readable
ex-date, conflicting dividend ex-dates reported. Not changed: the anchor stays undated (the capture records no
date for its last completed bar); an ex-date on the decision day stays a non-event (the anchor catches a scan
still on the old basis); the versioned disposition table and tick-size rounding are follow-ups (Limits).
ChatGPT's retained-data replay (2023-24, 12 names, frozen daily EMA/ADX setup) favoured the incumbent stop at
every cost: keep both policies in shadow; the forward pairs are the test of the actual Stage-2 policy.
Targeted mutants: 34 of 34 non-equivalent killed (2 equivalent ones removed as redundant code).
Independent reviewer, round 1: no blocker, no major, 4 minor + 3 nits. Fixed: a time exit priced from a feed
that stopped hours before 15:15 (now within 5 minutes or reported); special sessions (Muhurat, DR drills)
counted towards the 15 (now regular sessions only, in selection too); a small dividend with one unparsable
date held back silently (now reported); a daily-feed gap with minutes present counted as a quiet suspension
(now reported); conflicting small-dividend dates outside the window no longer hold back; NIFTY end-price
wording; the recorded entry window is used. Tests added for the 5 surviving mutants; 20 of 20 round-2
mutants killed.
Round 2: no blocker, no major, 1 minor + 3 nits. Fixed: bars of a special session inside the window were on
the path but never validated or cross-checked (now checked like any session when the stock has bars that day;
3 of 3 mutants killed, 1 equivalent removed). Kept and listed in Limits: the 5-minute exit rule is loud for a
thin stock (a feed that stops early looks the same); the entry window starts at the recorded decision time
(the app's minute-truncated plan time would allow a bar that began before the decision); `SPECIAL` is a
hand-kept list.
Gemini notebook second opinion (10 points): no defect. Kept by design: PARTIAL on ticker-level evidence problems
(LESSON 12), the 15:15 exit and gap-only stop fills (the app's plan; conservative for both policies), `no_fill`
for a thin entry window; the daily-only print risk is in Limits.

## Limits
- One-minute evidence (the stock's and NIFTY's) must be available from Upstox for the label to be exact;
  otherwise the decision is retried, never labelled from daily bars.
- The production label (`net-excess-execution-v2`, written by the inactive close-mode maturation) keeps the
  day-bar NIFTY window and the execution issues listed under the label version; give it a successor version
  before that maturation is switched back on, and keep its v2 rows (backlog).
- The entry takes the bar's open; the app also says "at or below the displayed ask", which is not modelled.
- Levels stay at two decimals for this frozen comparison; NSE tick sizes (dated, per price band) are not
  applied. An execution-quality successor should round side-aware to the instrument's dated tick and
  recheck stop < entry < target and net reward:risk after rounding (SADBHIN and other low-priced names).
- `no_fill`, `no_trading` and `outside_levels` repeat each run until the pass is 60 days old (one fetch
  each, rare); the report counts such passes as eligible, unlabelled, without the reason. A versioned
  per-decision disposition (reason, guard version, event identity, evidence) would make held, terminal and
  expired passes visible and let a corrected archive row release a pass: it needs a new table (DDL,
  Kiran-run), so it is a follow-up, not part of this change.
- The daily/minute touch check fails closed when a level lies between the daily bar's extreme and the
  minutes' (a print in the daily bar but in no minute bar: the pre-open auction if Upstox's 09:15 bar
  excludes it, or a block-deal or closing-session print if the daily bar includes one); how often that
  happens on clean sessions is not measured yet (the first labelling run reports each case). No trade in
  the 15-minute entry window is `no_fill`, as the app's plan says ("enter only during"), even for a thin
  stock whose resting order might have filled later.
- `nifty_session_calendar.SPECIAL` is hand-kept (last entry 2026-11-08): a future special session on a weekday
  that nobody adds counts as a regular one. Add each year's special sessions with the NSE holiday circular
  (backlog: NSE 2027 calendar).
- No bar within 5 minutes of the 15:15 exit is reported (`window_problem`) every run until the pass is 60 days
  old, also for a thin stock that simply did not trade then (a feed that stops early looks the same); a thin
  entry window is a quiet `no_fill` instead.
- The entry window starts at the recorded decision time (`evaluated_at`, stamped just after the decision), a
  few milliseconds after the app's plan time: the entry can be the next minute's bar, never an earlier one.
- The two inserts of a pair are separate statements: a crash between them leaves one policy stored and the
  next run labels the other from fresh bars (shortcut; `production_repository.py` is hash-pinned).
- The challenger's levels use the recorded `resistance20/60` (rounded to 0.01); the ATR is exact.
- Labels are hypothetical outcomes of every pass, not a portfolio: capital and overlapping positions are
  not modelled.
- Corporate actions: an event that the Upstox feed omits and the provider also did not adjust for (a raw
  ex-date jump inside the window) is not caught; Upstox listed only Dividend, Bonus, Split and Rights Issue
  in the archived rows. A decision held back only for a large dividend, or for an action whose ex-date the
  archive writer does not read (it reads `ex_date`, `expiry_date` and the "ex date", "ex dividend date" and
  "ex split date" details, and skips an undated row, so nothing excludes the pass), is re-checked (one request) each run until it is 60 days
  old (Upstox reportedly does not back-adjust dividends, so a large dividend after the window holds a decision
  back for nothing; rare). An action ex-dated on the decision day itself is not an event (the scan's quote is
  already on the new basis); a scan whose last completed bar was still on the old basis fails the anchor. A
  split that moves the stock to a new ISIN is looked up under the recorded one: if Upstox then lists nothing,
  the anchor still catches an adjusted history, and an old-ISIN history that stops at the split defers the
  label for missing bars. The report still counts held-back passes as eligible,
  unlabelled.
- The terminal mark reads the archive's single ex-date per action (the archive writer takes `ex_date`, else
  `expiry_date`, else a named detail) and the archive never deletes rows, so an action Upstox later cancels or re-dates still excludes
  its passes for good; a mis-dated row can also exclude a pass the live check would have let through. Rare;
  clearing it is a manual row fix in `corporate_actions` (Kiran-run SQL). The other way round, an action
  held back by an in-window detail date while its `expiry_date` lies after the run day is archived under the
  later date, so the pass stays pending and is re-checked each run (cost only; all dates agreed in the 911
  archived rows).
- A rescale under 0.1% (a dividend-sized adjustment) passes the anchor; the 0.5% entry-range checks and the
  events guard still apply.
- The 300 s budget is soft: a single decision can run long on request timeouts and retries.
- A minute range over 29 days (suspended or illiquid stock with missing bars) makes more chunk requests (up
  to 3 for about 60 days), unpaced, and its NIFTY window the same.
- `storage_policy.BUDGETS` gives `prediction_targets` 2 MB (advisory, no gate): at ~80 rows a day that is
  reached in about 2-3 months; review the budget then.
