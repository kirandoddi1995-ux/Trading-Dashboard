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
- Label version `net-excess-execution-v2.minute-aligned-v1` = `prediction_validation.compute_forward_target`
  (the production label: first one-minute open after the decision, minute-ordered touches, stop first, net of
  the decision's cost estimate) with two changes, so tight and wide stops are compared fairly:
  - a stop reached by a minute bar that opens below it fills at that open (gap through the stop), not at the
    stop, so tight stops are not flattered. Targets stay filled at the target. A bar opening at 0 or below is
    bad data: no label (retried); a NaN open keeps the stop fill;
  - NIFTY is measured over the stock's own holding window on NIFTY one-minute bars: from the open of the entry
    minute to the close of the exit minute (each NIFTY minute at most 5 minutes away, never reversed), or
    to NIFTY's daily close for a time exit. The production label
    measures NIFTY from the entry day's 09:15 open to the outcome day's close: for a 10:07 decision that adds
    NIFTY's first hour, and for a stop or target exit the rest of that day, to the "excess".
  A label whose NIFTY evidence is missing is not stored (`no_benchmark`, retried).
- Storage: append-only `prediction_targets` rows (immutable by trigger), `target_version`
  `stage2-shadow:net-excess-execution-v2.minute-aligned-v1:<policy>`. The app's calibration, readiness count and training read
  `net-excess-execution-v2` only, so they never see these. No new table, grant or policy: the runtime role
  already has SELECT/INSERT on `prediction_targets` (policy `archive_preserve_runtime`, checked 11 Nov).
  About 2 rows per pass (~39 passes per trading day today).
- Upstox: 1 NIFTY daily request per run; per stock-day 1 daily + 1 one-minute request (ending at the
  horizon's last session; both scans of a stock-day share them); 1 NIFTY one-minute request per decision
  window (shared by every stock with that window); each after a 0.2 s pause; at most 60 decisions (181
  requests) and 300 s per run (checked between decisions; a budget stop makes the run PARTIAL, the rest is
  retried). With the shadow step's 151 requests a scan stays below half of Upstox's documented 1000 requests
  per 30 minutes per API (25/s, 250/min); capacity 120
  decisions a day against ~39 new passes a day. A lost lease stops the run before any write; a
  rejected token stops it as FAILED; any other failure is contained (quality event
  `STAGE2_MATURATION_FAILED`, WARNING; ERROR when FAILED) and makes the run PARTIAL; a malformed row is
  one counted failure, never a stopped run; an empty NIFTY answer stops the run as FAILED before any stock
  request, and so does a stale one (last bar older than 6 days); an empty stock answer is deferred; an HTTP
  4xx on one instrument's daily request (dead key) is counted as `provider_rejected`, not a failure (a 4xx on
    the minute request stays a failure, so a broken endpoint cannot look like SUCCESS); NIFTY evidence missing for
  a holding window (no minute within 5 minutes of entry or exit, no daily close for a time exit) is counted as
  `no_benchmark`; an empty NIFTY minute answer is a failure (a broken feed must not look healthy). Unlabelled
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

## Limits
- One-minute evidence (the stock's and NIFTY's) must be available from Upstox for the label to be exact;
  otherwise the decision is retried, never labelled from daily bars.
- The production label (`net-excess-execution-v2`, written by the inactive close-mode maturation) keeps the
  day-bar NIFTY window; fix it there (new version) before that maturation is switched back on (backlog).
- A next-open entry (decision outside the session) averages the five opening minutes; its NIFTY window starts
  at the fifth (a few minutes, not an hour).
- The challenger's levels use the recorded `resistance20/60` (rounded to 0.01); the ATR is exact.
- Labels are hypothetical outcomes of every pass, not a portfolio: capital and overlapping positions are
  not modelled.
- No corporate-action guard: a split or bonus inside the 15 sessions would give a wrong label (backlog).
- The 300 s budget is soft: a single decision can run long on request timeouts and retries.
- A minute range over 29 days (suspended or illiquid stock with missing bars) makes more chunk requests (up
  to 3 for about 60 days), unpaced, and its NIFTY window the same.
- `storage_policy.BUDGETS` gives `prediction_targets` 2 MB (advisory, no gate): at ~80 rows a day that is
  reached in about 2-3 months; review the budget then.
