# Quant Terminal resilience runbook

This runbook applies to `v22.0-RESILIENCE-CONTROL-PLANE` and later. Never disable a safety gate merely to restore trade output. Exits, position reduction, and audit reads remain available in every safety state.

## Safety states

- `NORMAL`: New recommendations, evidence writes, exits, and audit reads are enabled.
- `DEGRADED`: New recommendations are allowed only when their own mandatory gates pass. Reduced scan scope and higher observability are required.
- `NO_TRADE`: Block every new recommendation/order. Continue exits, reconciliation, evidence capture, and audit reads.
- `READ_ONLY`: Block new recommendations and nonessential writes. Preserve exits and audit reads. Use this for ledger, database, outbox, or retention-integrity risk.
- `EMERGENCY_STOP`: Block all new risk. Preserve emergency exits and audit access. Recovery requires an identified approver plus the configured number of clean windows.

## Incident command

1. Open an incident record with UTC and IST timestamps, correlation ID, safety state, build, policy hash, model version, data provider, and first failing control.
2. Assign incident commander, operations lead, communications lead, and recorder. One person must not both change and approve a model or production policy.
3. Preserve logs, ledger/outbox files, provider responses with credentials removed, runtime attestation, and deployment revision.
4. Prefer `NO_TRADE` or `READ_ONLY` over bypassing a failed dependency. Never delete pending outbox evidence.
5. End only after the cause is corrected, reconciliation is complete, canaries pass, and the state-machine recovery rule is satisfied.

## Stale or divergent market data

Confirm exchange calendar/session, NTP offset, provider heartbeat, quote timestamp, sequence continuity, best bid/ask, and secondary quote. Keep `NO_TRADE` until three clean evaluation windows. If the secondary provider is not configured, record `DEGRADED`; set `require_independent_quote=true` only after its licensed adapter is deployed and monitored.

## Database, ledger, or outbox incident

Enter `READ_ONLY`; retain local outbox files; verify database role and schema version; restore connectivity; replay idempotently; compare local pending IDs with durable ledger IDs; verify every aggregate hash chain. Do not mark delivered before the durable append commits. Clear the state only after backlog count is zero and the oldest pending age is below policy.

## Collector failover

Only the owner of the current lease and fencing token may write. A worker that loses renewal must stop. Confirm the previous lease expired before starting a replacement. Compare run IDs, fencing tokens, quote coverage, and record counts; duplicate idempotent rows are acceptable, divergent rows are not.

## Model/calibration incident

Set calibrated probability to unavailable and abstain after the configured consecutive drift breaches. Keep the current champion unless its safety is implicated. Promotion requires signed artifact, point-in-time features, untouched chronological holdout, costs, at least 500 OOS samples, at least three regimes, independent approval, and a rollback model.

## Release rollback

The repository emits `PROMOTE`, `BLOCK`, or `ROLLBACK` decisions. Connect `ROLLBACK` to the hosting provider's immutable previous release ID; repository code cannot provision this external connection. After rollback, verify authentication, restricted DB role, policy checksum, quote freshness, evidence append/replay, and five healthy canary probes before resuming.

## Backup recovery drill

Restore to an isolated Supabase project, never over production. Measure RPO/RTO; apply migrations using the owner-only URL; recreate the restricted runtime role; verify row counts, PIT snapshots, target labels, and all ledger chains; keep outbound providers disabled; document the backup ID and hashes. Required: RPO <= 15 minutes, RTO <= 60 minutes, and a successful drill every 90 days.

For schema version 4, manually dispatch **Scheduled evidence collector** once with `apply_migrations=true`. Routine scheduled runs do not receive or use the owner credential; they validate and use only `quant_app_runtime`.

## Secret compromise

Enter `EMERGENCY_STOP` for a leaked ledger key or trading/provider credential. Revoke at the provider, rotate in the secret manager, preserve key IDs needed to verify old ledger events, redeploy, invalidate sessions, and inspect access logs. Telemetry may contain secret names and key IDs but never values.

## Game-day safety

Run `python resilience_acceptance.py --game-day` only against local/CI test doubles. Production fault injection requires explicit incident commander approval, a bounded blast radius, active exits, and rollback readiness.
