# Automatic shadow Stage-2 in the scheduled collector (Phase 2 + 3), 10 Nov 2026

Shadow only. Nothing here places, sizes or routes an order.

## What changed

- `equity_stage2_collector.py` (new): runs app.py's Stage-2 decision core
  (`equity_stage2_decision.evaluate_stage2`, the parity-tested copy from Phase 1b) on
  every Stage-1-shortlisted ticker of a `scan` run, and archives the result.
- `scheduled_collector.py`: after ALL Stage-1 evidence of a scan is committed, calls
  `run_shadow_stage2(...)`. The Stage-1 batch, rows and quote evidence are byte-identical
  with the switch on or off (tested). The universe evidence dict was moved to a local
  variable so both batches use the same one.
- `equity_stage2_engine.py`: + app.py's history parser (`normalize_market_timestamp_series`,
  `_history_to_dataframe`), verbatim, parity-tested like the other helpers.
- `deployment_canary.py`: new check `scheduled_stage2_is_shadow_only` (the existing
  `scheduled_scan_is_shadow_only` is unchanged and still true).
- `.github/workflows/scheduled-collector.yml`: passes `vars.SCHEDULED_STAGE2_SHADOW`.

Source pin: `SOURCE_SUPERSESSIONS.json` now maps the historical `scheduled_collector.py`
pin `6be0f301...` to these bytes (it pointed at `cda09c60...`, the
STORAGE_TRIMMING_2026-11-06.md successor); `security_profile_successors.SUPERSESSIONS_SHA256`
re-pins the record. Regression-only, not an upload admission.

## Switch

Off by default. On only when the repository variable `SCHEDULED_STAGE2_SHADOW` is `1`
(also `true`/`yes`/`on`). Optional `SCHEDULED_STAGE2_BUDGET_SECONDS` (default 900).
Off = no history requests, no extra rows, no extra ledger event.

## Settings (app.py widget defaults, pinned by a test)

Horizon 15 days, max price Rs 50,000, weekly confirmation off, advanced filters off,
capital Rs 10,00,000, risk 2 %, max position 20 %.

## Inputs, matched to the app

- History: 1200 days of Upstox V3 daily candles, parsed by app.py's parser, then written
  to and re-read from an in-memory SQLite with app.py's own SQL = what app.py's
  `get_cached_history` returns on a cold cache. A warm app cache can differ (old fetches,
  incremental refresh): a Phase 4 comparison item, not copied.
- Features: computed from scratch (feature-cache miss path).
- NIFTY 50: 400 days, once per run (as app.py).
- Quote: the Stage-1 snapshot (Full Market Quote V3). The decision core reads bid/ask only
  from `market_data.bid_price/ask_price`, which this snapshot does not have (depth is under
  `market_depth`), so costs are modelled without a measured spread - the same as app.py's
  Full NSE scan (full-universe quotes are REST LTP + OHLC). The app's Quick scan can carry
  websocket bid/ask and estimate a different cost; both shapes are parity-tested.
  `capture.costs.measured_spread_available` says which applied.
- `market_open`: the verified NORMAL_OPEN status.
- History index must be a sorted, unique, naive DatetimeIndex (completed-bar logic
  filters by index dates). An HTTP 200 with an error body or no candle list is a fetch
  failure (NOT_EVALUATED), not "no candles".
- Feature cache mode is recorded as `full_rebuild` (what the real store reports when cold).

## Evidence written (per scan, when on)

1. One `DECISION_BATCH_EVALUATED` event, aggregate `scan:<run_id>:stage2-shadow`,
   idempotency `decision-batch:<run_id>:stage2-shadow`, strategy
   `equity-stage2-scheduled-shadow-v1`, covering the COMPLETE shortlist:
   - EVALUATED: pass, or the app's reject (category + reason, levels computed so far);
   - NOT_EVALUATED: history/NIFTY fetch failed, token rejected, invalid history index,
     malformed quote, or time budget exhausted. A data failure is never a strategy reject.
   - Ledger action is only `Watch` (passed) or `No Trade`. The app's would-be action
     (`Buy`/`Watch`) is data (`signal_action`). `governance_evaluated: false` always: the
     app's live governance step can still reject a shadow pass.
   - Per candidate: result, app-shaped features on a pass, history span, and a compact
     EquityCapture (constants/identity moved to the batch, raw quote and per-input times
     dropped; `expand_capture` rebuilds the rest exactly - tested).
2. Then one `scanner_observations` row per shortlisted ticker (same strategy version,
   id `sha256(run_id|key|version)`), pointer features only (`scan_run_id`, `retention`),
   app-style `rejection_reason` "Category: reason", typed score/entry/stop/target.
   Data-quality-rejected candidates keep full features and are never a pass.

Any failure other than a lost lease is contained: quality event `STAGE2_SHADOW_FAILED`
(or `_PARTIAL`), summary in the run metadata, no shadow rows without their batch.
A lost lease raises (fenced worker stops).

## Storage

Measured on synthetic runs: ~1.7-2.7 kB per reject, ~5.9 kB per pass (raw JSON before
TOAST compression). 150 shortlisted is about 0.3-0.4 MB raw per scan, two scans a day.
The ledger is never deleted, so this adds roughly a third to its weekly growth. Shadow
pass rows (`stage2_pass` true) are kept by the archive rule; there are few per scan.

## Not in this change

- Outcome maturation for shadow passes (needs a `DECISION_EVALUATED` per pass; Phase 5).
- Turning the switch on (Kiran) and the Phase 4 dry-run comparison against the live app.

## Tests

`tests/test_equity_stage2_collector.py` (differential vs app.py's real history path and
real `evaluate_stock` on the same candles, settings/SQL/request pins, history guards,
capture round trip, code-hash closure, failure containment, lease fencing, canary).
`tests/test_equity_stage2_engine_parity.py` covers the two new verbatim helpers.
`tests/test_equity_stage2_decision.py`: the elapsed_fraction capture input is now
compared with a tolerance (it reads the wall clock and differed in the last digits
during market hours after 10:11 IST - a latent flake in the Phase 1b test).
