# Unified production-resilience implementation standard

The control plane is one path across P0, P1, and P2. Every live recommendation calls it. The most severe active finding determines the state, so a lower-severity subsystem cannot mask a higher-severity failure.

## P0 controls

1. **Correlated observability** — Propagate one correlation ID through rerun, provider, scanner, recommendation, evidence, fill, and incident events. Export bounded labels only. Monitor missing spans and error cardinality. Accept when >=99.9% of recommendations link quote-to-ledger without credentials or payload bodies. Missing business-critical telemetry is `DEGRADED`; integrity gaps are `READ_ONLY`.
2. **SLOs and error budgets** — Record success and latency, calculate rolling p95/error rate and multi-window burn. Monitor availability, recommendation latency, provider errors, and evidence durability. Accept at >=99.5% availability, <=0.5% error rate, and <=2.5s p95 over the configured window. Fast burn is `NO_TRADE`; latency-only breach is `DEGRADED`.
3. **Market-data supervisor** — Validate finite prices, timestamps, heartbeat, sequence, book consistency, and provider divergence. Monitor quote age and mismatch bps. Accept no stale/future/crossed quotes entering recommendations. Violations are `NO_TRADE`.
4. **Canary and rollback** — Probe auth, policy hash, restricted DB role, quote freshness, and evidence round trip against immutable candidate/previous release IDs. Monitor five-probe p95 and failures. Any failed probe emits `ROLLBACK`; deployment tooling must connect that decision to Streamlit hosting.
5. **Secrets lifecycle** — Keep value-free metadata for creation, rotation, expiry, use, and actor. Monitor expiry and unusual access. Accept zero plaintext findings, rotation within 90 days, and alerts 14 days before expiry. Exposure is `EMERGENCY_STOP`; expiry is `NO_TRADE`.
6. **Point-in-time recovery** — Run isolated restore drills with checksums, ledger verification, migrations, and restricted-role recreation. Monitor drill age/RPO/RTO. Accept RPO <=15m, RTO <=60m, successful drill <=90 days. Failure is `READ_ONLY`.
7. **Outbox reconciliation** — Compare local pending IDs to committed durable IDs, replay idempotently, and age the backlog. Monitor pending count, oldest age, attempts, and collision errors. Accept <=100 pending and oldest <=900s; breach is `READ_ONLY`.

## P1 controls

8. **Configuration-as-code drift** — Check approved policy checksum plus build/model/dependency/schema hashes at startup and periodically. Accept exact attestation equality. Signature failure is `EMERGENCY_STOP`; ordinary drift is `NO_TRADE`.
9. **Model promotion control plane** — Enforce shadow -> paper -> canary -> champion with immutable approval/rollback history. Accept PIT verification, untouched holdout, costs, >=500 OOS samples, >=3 regimes, independent approval, and rollback artifact. Failure blocks promotion and leaves probability unavailable.
10. **Calibration drift and abstention** — Evaluate chronological Brier, ECE, log loss, age, and deterioration. Accept policy thresholds; two consecutive breaches trigger `NO_TRADE`. One breach is `DEGRADED`; clean-window hysteresis prevents flapping.
11. **Independent quote reconciliation** — Compare timestamp-aligned executable-side prices using max(configured bps, two ticks). Accept all actionable quotes within tolerance. Divergence is `NO_TRADE`. Until a licensed adapter is configured, status is visibly `DEGRADED`; production may set it mandatory.
12. **HA collectors** — Use a database lease with owner ID, TTL, renewal, and monotonically increasing fencing token. Accept that two concurrent starts yield one active writer and a stale token cannot renew. Lease loss fails the run.
13. **Fill/execution surveillance** — Validate state transitions, cumulative quantity, partial-fill age, and slippage. Accept no terminal-state mutation, no overfill, partial age <=30s, and slippage <=50bps. Integrity errors are `READ_ONLY`; stale partials/slippage are `NO_TRADE`.
14. **Clock/session integrity** — Require timezone-aware exchange timestamps, approved calendar, normal session, and NTP offset <=250ms. Monitor offset, provider/exchange skew, DST/calendar version. Any breach is `NO_TRADE`.

## P2 controls

15. **Chaos/game days** — Inject provider outage, stale feed, clock skew, DB outage, outbox backlog, lease loss, and corrupt attestation only in CI/staging. Accept the exact expected state within one evaluation and preserve exits/audit access. Never inject production without incident-command approval.
16. **Capacity/degradation** — Track CPU, memory, DB-pool use, queue depth, latency, and scan concurrency. Accept <=85% CPU/memory, <=80% DB pool, and queue <=1000 under expected peak. Saturation reduces work (`DEGRADED`); unsafe queues become `NO_TRADE`.
17. **Incident command/runbooks** — Require roles, timestamps, correlation IDs, evidence preservation, recovery gates, and post-incident actions. Accept quarterly tabletop completion and every alert linking the correct runbook within five minutes.
18. **Failover/read-only safe mode** — Preserve exits and audit reads while blocking new risk and unsafe writes. Accept deterministic transition during DB/ledger failure and no recommendation leakage. Recovery requires reconciliation plus clean windows.
19. **Retention/privacy/audit durability** — Enforce seven-year evidence, 90-day operational logs, 30-day personal-data maximum unless legally required, immutable promotion/state history, and legal holds. Accept scheduled verification with zero ledger-chain failures. Drift or chain failure is `READ_ONLY`.

## External production configuration still required

- Connect OpenTelemetry/metrics export and alert routing to the organization's monitoring platform.
- Configure a licensed independent NSE quote source before making quote reconciliation mandatory.
- Connect CI rollback decisions to Streamlit's deployment/revision mechanism.
- Configure secret-manager rotation and provider revocation workflows.
- Enable the Supabase backup/PITR plan and execute isolated restore drills.
- Configure protected GitHub environments and independent approvers for production/model promotion.

These are provider-side controls. The repository validates and fails safely around them but cannot create external accounts, licenses, approvals, backups, or hosted rollback capabilities.
