# Production label successor: `net-excess-app-contract-v1` (16 Nov 2026)

Backlog 11. Approved by Kiran 16 Nov 2026 ("Yes, build it"), shown to him before merge (label formula change).

## Why

The production equity label `net-excess-execution-v2` (`prediction_validation.compute_forward_target`,
used by the close-mode maturation `scheduled_collector.update_matured_targets`) had three execution bugs,
the same ones found in the first shadow label (prompt 65 review, 13 Nov):

1. NIFTY benchmark from the entry day's 09:15 daily open to the outcome day's daily close, not over the
   minutes the stock was held (a NIFTY move before the entry minute or after the exit minute was charged
   to the stock's excess return).
2. An in-session decision whose first minute bar fell on a later day entered on that later day (the app's
   15-minute entry window was ignored).
3. The time exit came at the close of the 15th session counted from the entry day, not 15:15 on the
   15th regular session after the decision day (the app's mandatory exit, `trade_contracts.build_trade_timing`).

It also read minute bars only on days whose daily bar showed a touch (a touch only the minutes show was missed).

Live state when fixed (read-only checks, 16 Nov): close mode (pg_cron job 4) is inactive; 0 rows in
`prediction_targets` under any version; 0 passed app decisions waiting for a label. Nothing stored changes.

## What changed

One label engine for both shadow and production: the shadow label `net-excess-app-contract-v1`
(`equity_stage2_maturation`, merged 13 Nov) is the production label now.

- `prediction_validation.TARGET_VERSION` = `net-excess-app-contract-v1`. The old string is kept as
  `LEGACY_TARGET_VERSION`; `compute_forward_target` still exists (research tests) but stamps only the legacy
  version and is no longer called by the collector.
- `equity_stage2_maturation`:
  - `exit_session`, `window_end`, `trade_contract` and `_history` take the decision's recorded horizon
    (shadow: 15, unchanged).
  - `label_decision` takes optional `levels`, `versions` and `early` (shadow defaults unchanged).
  - New `production_decision` (inputs from the DECISION_EVALUATED payload: decision time, cost, horizon,
    entry window, last completed bar), `production_payload` (exactly one decision event) and
    `label_production_decision` (guard, history, shared label on the recorded stop/target, full window only).
- `scheduled_collector.update_matured_targets` uses it:
  - selection: `pending_observations(exit_since=today - 60 days, final_dispositions=PRODUCTION_FINAL)`,
    400 rows read. The 60 days run from the estimated exit day (decision day + horizon in weekdays + a week),
    so a long horizon (the app allows 1-365 sessions) stays selected until it can mature; a decision with
    fewer calendar days since its decision day than horizon sessions cannot be complete and is not read
    (`ready_before=today`), so waiting long horizons cannot fill the 400 rows. Never-tried decisions come
    first, by estimated exit day, then the least recently tried, so retried failures cannot crowd new
    decisions out. A decision whose horizon has not completed, or whose recorded time has no entry window
    (after 15:15, or a day without a regular NSE session per `nifty_session_calendar`: closed, or a special
    session such as a Budget Saturday), is answered from the NIFTY calendar with no Upstox request. An open
    weekday missing from NIFTY's bars is a retried window problem.
  - budget: at most 40 decisions fetched per run and 300 s. A 15-session decision costs about 4 requests;
    minute data comes in 30-day chunks, so a long horizon costs more (the 300 s budget bounds it). The
    lease is checked before every decision and every write (LeaseLost stops the run, as in the shadow
    maturation).
  - per decision: label saved first, then the OUTCOME_MATURED event (15 completed session closes, outcome
    time = the actual exit minute). If the event fails, the next run finds the stored label (returned by
    the pending query) and writes the event from it without re-labelling (one daily request for the
    session proof; the exit minute is not stored, so its outcome time is that session's 15:30 close, never
    earlier than the exit). Re-labelling could disagree after a corporate action or a revised bar.
    Storing the exit minute would need a `prediction_targets` column (Kiran-run DDL); not done.
  - no label: the reason is counted in `unlabelled` and kept as the decision's disposition
    (`stage2_shadow_dispositions`, label version = TARGET_VERSION, the same string as the shadow label
    version; app decisions and shadow passes have different observation ids; the table and grants
    already exist). Reasons a retry cannot change (`no_entry_window`, `no_fill`, `no_trading`,
    `outside_levels`, `corporate_action`, `duplicate_decision`: two DECISION_EVALUATED events, which the
    evidence contract refuses) are final: never selected again. Retried: data problems (window,
    basis, unreadable corporate actions: WARNING quality event), `no_history` (an empty daily answer,
    a renamed or delisted key; counted as an attempt), `provider_rejected` (an HTTP 4xx on the daily
    history request) and errors (`failed`, ERROR event; a corporate-actions 4xx is one of these).
  - a rejected token (on any request, NIFTY included) ends this step FAILED; the rest of the close run
    (mutual funds, shadow cues) goes on, and the run is reported PARTIAL (`close_run_status` reads the
    step's own status as well as its failure count).
  - status (LESSON 12, as the shadow maturation): any listed problem (window, basis, unreadable
    corporate action, error) or a time-budget stop makes the step PARTIAL; the attempt cap alone does not.
- Training readiness: `model_training_pipeline` defaults and `.github/workflows/model-training-readiness.yml`
  use TARGET_VERSION. A test fails if any production file names `net-excess-execution-v2` outside the legacy
  label and the historical cohort check.
- Literals: `production_repository.pending_observations` default and readiness count, `evidence_progress`
  equity contract. `equity_research_observations` keeps `net-excess-execution-v2`: it validates the fixed,
  approved 89-decision historical cohort, which was recorded under that version.
- Version stamps: the scheduled Stage-1 batch and the shadow Stage-2 ledger batches also record
  `TARGET_VERSION` (an identifier only; no reader filters on it; shadow labels are unchanged).
- Deploy: the app (Streamlit) and the collector (GitHub Actions) both run from `main`. A decision the app
  makes on the old code after the merge is stamped v2 and never labelled; close mode is off, so none is owed.
- `app.py` untouched (it imports `TARGET_VERSION`). New app decisions are stamped with the new version, and
  calibration, readiness and training read it. The 3,449 older decisions stamped v2 have no passes, so no
  label is owed to them.

## Test harness fix (same change)

`tests/test_archive_maintenance_sql.py` (the shared PGlite SQL harness, pinned): rows now come back by
column position (`rowMode: 'array'`). Rows built from column names lost repeated names, so a query with
several `count` columns (`ProductionRepository.stats`) returned shifted values. All 299 harness tests pass
unchanged; the new `stats` test needs it.

## The label (same as the shadow label, `equity_stage2_maturation` docstring)

Entry: open of the first minute bar after the decision time and within the entry window the app showed.
Exit: the first stop or target touch on one-minute bars (stop first; a gap through the stop fills at the
bar's open), else 15:15 on the horizon's last regular session. Net of the decision's estimated round-trip
cost. NIFTY over the same minutes. Guards: corporate actions since the decision day, price basis (recorded
entry and last completed bar against the fetched history), daily/minute touch agreement, bar validity.
Production labels only full windows (no early labels).

## Second opinion (Gemini notebook, 16 Nov) and what was done with it

- "Training could mix in shadow labels": no. Shadow labels are stored as `stage2-shadow:<version>:<policy>`,
  and `matured_decision_dataset` joins DECISION_EVALUATED identifiers (strategy and version). With 0
  labels, readiness reports INSUFFICIENT_EVIDENCE as a healthy check (test kept).
- "Dispositions FK to scanner_observations": every pending row comes from a join on scanner_observations.
- "The dispositions table records, never selects": that contract was already relaxed for the shadow
  rotation (`last_at`, 13 Nov, accepted); production now also leaves out final reasons. Documented here.
- "LESSON 12: hold-backs must be loud": accepted. The step now turns PARTIAL on any listed problem or a
  budget stop (it only listed them before).
- "A rejected token should halt dependent steps": the later close-mode steps either do not use Upstox (AMFI
  mutual funds) or handle a 401 themselves (corporate actions); the run is reported PARTIAL.
- "Budget vs runner time": 300 s per step, inside the close job's timeout; close mode is off (job 4).

## Rollback

Revert the merge commit. No data migration: no label was ever stored under either version.

## Not changed

Close mode stays off until Kiran switches pg_cron job 4 on.
