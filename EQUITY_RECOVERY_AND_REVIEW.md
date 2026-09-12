# Equity scan recovery and manual quote review

Status: local implementation draft. The database migration has not been run.

## Scope and safety boundaries

- Equity only. Options, futures, MCX and SMC keep their existing behavior and the shared 2.00 net reward:risk threshold.
- The equity 1.30 net reward:risk threshold is unchanged.
- Research observations and outcomes remain in `equity_research`; they are not read by this feature and cannot become trade suggestions.
- Manual quote review is additive. It cannot turn a governance, model, trend, data or risk rejection into a trade.
- Recovery reruns unfinished candidates only. Results completed before interruption remain archived and are not silently reused as current suggestions.
- Every recovered candidate must pass a new Stage-1 check, obtain a new quote, and pass a new governance evaluation before it can be shown as a current signal.

## Database isolation

The draft migration creates the private `equity_operations` schema with:

- `scan_runs`: run state, heartbeat, fencing token and scan metadata.
- `scan_candidates`: per-candidate pending/completed checkpoints and fresh quote/governance timestamps.
- `manual_quote_reviews`: append-only, decision-bound manual confirmations.

Only the restricted `quant_app_runtime` role receives access. The migration explicitly revokes access from `PUBLIC`, `anon`, `authenticated`, `service_role` and `equity_research_collector`, forces row-level security, and verifies that the research collector cannot read the operational tables.

Do not put a password or connection string in this document or in Git. The app continues to use its existing protected `DATABASE_URL` secret.

## Interrupted scan recovery

1. A new equity scan creates a run and one `PENDING` checkpoint per Stage-2 candidate before workers start.
2. Each terminal candidate result is committed once. A completed checkpoint cannot be overwritten.
3. Cancellation, timeout, process exit or checkpoint failure leaves unfinished candidates recoverable.
4. **Recover interrupted scan** claims the run with a higher fencing token. Any older worker is then unable to write.
5. Live quotes and Stage-1 screening are refreshed for the unfinished set. Candidates that no longer pass Stage-1 are stored as recovery rejections.
6. Stage-2 and governance run again for candidates that pass refreshed Stage-1. A result is accepted only when both its quote timestamp and governance timestamp are at or after the recovery start and governance still allows the trade.
7. Previously completed results remain archived for audit; they are not mixed into the recovered current-result list.

The local SQLite checkpoint supports same-process and local restart recovery. The private PostgreSQL checkpoint is the cross-process durable source once the migration is approved and applied.

## Atomic equity evidence delivery

For equity evidence only, the immutable local ledger event and its remote-delivery outbox row are committed in one SQLite transaction. A crash therefore leaves either both records or neither. Remote delivery is at-least-once with the existing idempotency key, so a crash after remote acceptance but before local acknowledgement safely retries the same event identity.

Non-equity callers retain the previous ledger append path.

## Manual quote review

The dashboard offers a manual check only for an equity candidate that already has:

- a system `Buy` result;
- `allow_trade=true` from governance;
- an immutable decision ID;
- entry, stop, target, quote timestamp and governance timestamp.

For a trade the user actually intends to consider, the form records the second platform, observed price, reviewer, click timestamp and explicit confirmation. It intentionally leaves the source platform's own quote timestamp missing when that platform does not provide one.

The review is bound to a digest of the exact decision, run, ticker, system action, entry, stop, target, primary quote time and governance time. A different or changed decision is `SUPERSEDED`. A price outside the configured tolerance is `MISMATCH`. An old quote, governance decision or confirmation is `STALE`. Only a current `CONFIRMED` review leaves the already-approved system signal actionable.

## Acceptance checks

1. Manual review cannot override a rejected or non-Buy system decision.
2. A review is bound to the exact decision and becomes invalid when trade details change.
3. A process kill preserves completed checkpoints and exposes only unfinished candidates for recovery.
4. Recovery retries do not duplicate immutable evidence.
5. An older fenced worker cannot overwrite a recovered run.
6. Recovery rejects stale output and candidates that fail refreshed Stage-1.
7. Local evidence and remote-delivery queue records are atomic across crash boundaries.
8. Research tables/readiness counts and all non-equity thresholds and paths remain isolated.
9. The full regression suite and `import app` smoke test pass before deployment approval.

## Deployment order after review

1. Review the local file diffs and migration SQL.
2. Create or verify the restricted `quant_app_runtime` login outside source control.
3. Run the approved migration once using the Supabase SQL editor as an administrative role.
4. Verify grants with read-only checks before starting an equity scan.
5. Deploy the reviewed application files.
6. Interrupt a disposable equity scan after at least one checkpoint, recover it, and confirm the log shows a higher fencing token and fresh quote/governance timestamps.
7. On the first system-approved equity candidate, verify that it remains non-actionable until the exact manual quote review is stored.

