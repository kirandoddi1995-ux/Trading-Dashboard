# Storage trimming — 6 Nov 2026

The collectors stop at 476,000,000 bytes (Supabase free tier). Headroom on 6 Nov after the 14:37 run was 13.4 MB.

## 1. Universe (PR #76, merged)
- App page loads archived the same Upstox BOD file in a pandas shape. This stored a second full version for the day and rewrote the canonical rows. App rows are now restored to the provider record (2,742/2,742 text-equal on 6 Nov data), so they reuse the collector's version.
- Canonical `universe_membership` rows store `{"retention":"versions_v1"}`.
  - The provider row is in `universe_membership_versions` at `sha256(date|payload_hash)`.
  - Canonical dates referenced by scanner observations are never archived, so this growth was permanent (about 1 MB per trading day).

## 2. Scheduled Stage-1 scanner rows (this change)
- Each run stores about 2,742 rows. Their `feature_json` (390 B on average) repeated the run's `DECISION_BATCH_EVALUATED` ledger event:
  - `inputs_used`;
  - `action` = `shadow_action`;
  - `scan_run_id`, with `decision_id` = `observation_id`.
- The collector now writes the ledger batch first, then stores `{"scan_run_id": ..., "retention": "ledger_v1"}` (89 B). Data-quality rejections keep full features.
- Rebuild: aggregate `scan:<scan_run_id>`, candidate `decision_id = observation_id`, `inputs_used + scan_run_id + action`.
- Live check: 32,782/32,782 candidates from the last 8 days rebuild exactly.
- Saves about 1.65 MB per trading day.
- Readers: no reader of Supabase `feature_json` uses scheduled Stage-1 rows.
  - `pending_observations` reads Stage-2 rows.
  - `prediction_validation` and the app read local SQLite.
- Owner-accepted dependency:
  - `evidence_ledger_events` has no-delete/no-update triggers but is not in the Drive export.
  - Until it is, new Stage-1 inputs exist only in Supabase; archived scanner rows carry the pointer.
  - Adding the ledger to the Drive export belongs to the rolling archive work.

## Outlook
- Expected growth after both changes is about 6 MB per trading day (estimate).
- This buys days, not a permanent fix. The permanent fix is a rolling window: keep recent days hot, export older rows (and the ledger) to Drive, and prune after verified custody.
