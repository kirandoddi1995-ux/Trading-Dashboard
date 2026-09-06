# Production external-action gate

Repository controls are implemented and tested, but the application must remain **NO TRADE** or safer until the following provider-side controls are configured and independently verified.

- Create separate Google Secret Manager secrets for the model-artifact key and each approver. Configure GitHub OIDC/Workload Identity Federation with read-only access, then set `GCP_SECRET_MANAGER_PROJECT`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SECRET_READER_SERVICE_ACCOUNT`, `MODEL_ARTIFACT_SIGNING_SECRET_REF`, and `MODEL_APPROVER_SECRET_REFS_JSON`. The two approver identities must reference different secrets. Keep `REQUIRE_MANAGED_PROMOTION_KEYS=true`; do not restore plaintext promotion keys to GitHub.
- Keep `RUNTIME_EVIDENCE_SIGNING_KEY` separate from model, approver, and evidence-ledger keys. Schedule rotation through `RotationCoordinator`; validate the new version before disabling the old version and retain retired versions according to the audit-retention policy.
- Subscribe to a licensed Zerodha Kite Connect data plan before setting `SECONDARY_QUOTE_PROVIDER=KITE`, `KITE_API_KEY`, `KITE_ACCESS_TOKEN`, and `SECONDARY_QUOTE_SYMBOL_MAP_JSON`. The mapping must contain explicit `NSE:` symbols. Run quote reconciliation in shadow first and validate timestamp alignment, coverage, and executable bid/ask tolerances before passing the result into live governance.
- Connect `OTEL_EXPORTER_OTLP_ENDPOINT` and `ALERT_WEBHOOK_URL` to monitored HTTPS backends. Page on feature-quality failures, evidence-write failures, scan/collector failures, governance NO_TRADE/safer states, telemetry-export failures, SLO burn, outbox age, authentication failures, and database-role misuse. Configure `ALERT_WEBHOOK_SIGNING_KEY` at the receiver and reject unsigned/invalid payloads.
- Configure `DEPLOYMENT_ROLLBACK_TARGET` to an immutable prior Streamlit release/revision and connect the canary `ROLLBACK` decision to the hosting API. The repository does not possess or create hosting credentials.
- Configure `SECRETS_MANAGER_URI`, automated rotation/revocation, access audit logs, and expiry alerts. Rotate at least every 90 days.
- Configure `NTP_MONITOR_ENDPOINT` and alert/block at an absolute offset above 250 ms.
- Enable a Supabase plan that supports the required backup/PITR objective and protect the `production-recovery` GitHub environment. Run `.github/workflows/recovery-drill.yml` in plan mode, then use the source project's **Backups → Restore to a New Project** Dashboard flow at the planned timestamp. Supabase's public PITR Management API is in-place and is deliberately not called by this repository. After the new project exists, configure its restricted `DR_DATABASE_URL` and run verify; confirm ledger continuity and role restrictions before recording RPO/RTO attestations.
- In GitHub, protect the `production` environment with independent reviewers. Store all secret values as environment secrets and non-secret endpoints/attestations as environment variables.
- Connect the protected workflow's verified authorization output to the actual durable model registry/deployment endpoint. Until that integration is configured, successful CI means **authorized package produced**, not **production deployed**.

Run `python production_readiness.py --strict` in the protected environment. Any missing requirement is a failed deployment and a runtime safety finding.

## Evidence-gated Step 3 pipeline

The logistic/GAM, monotonic boosted candidate, chronological stack, separate Platt window, untouched holdout, signed artifact, and SHADOW registry paths are implemented. Synthetic fixtures are `TEST_ONLY` and cannot create a production artifact. Artifact creation requires immutable production-spine attributes, independently supplied promotion evidence, and explicit proof that a rollback champion exists; no field defaults to success.

After deploying this release, manually run **Real evidence model-pipeline refusal smoke**. It uses the restricted `DATABASE_URL` and should currently finish with `INSUFFICIENT_EVIDENCE`, `INVALID_EVIDENCE`, `NEGATIVE`, or another safe no-artifact result. `UNAVAILABLE` is acceptable only in a local environment without the production secret; it is a deployment failure in GitHub. Do not provide signing keys to this smoke workflow.

No calendar event feed is guessed by the repository. Select official RBI, Government of India, and statistical-agency publication feeds, map their published/available timestamps to the strict calendar parser, and archive the provider payload under your permitted retention terms. Until that mapping exists, event-distance features remain unavailable and non-scoring.

The read-only evidence tracker and automatic weekday model-readiness check are documented in `EVIDENCE_READINESS.md`. They do not create or promote an artifact. Managed artifact signing, durable registry connectivity, rollback proof, two independent cryptographic approval roles, protected-environment approval, and the hosting deployment integration remain required after a candidate validates.

## Prospective shadow collection activation

The repository now schedules the exact shared equity Stage-1 funnel at 10:07 and 14:37 IST on weekdays.
These two reproducible snapshots capture morning and afternoon conditions without manufacturing highly
correlated pseudo-samples or creating unnecessary database growth. It runs in GitHub Actions and does not
require a browser or Streamlit session. Every
result is permanently labelled **Watch** or **No Trade**; the scheduled path cannot run Stage-2, unlock a
live recommendation, size a position, or place an order.

A separate 03:15 IST Tuesday-Saturday run captures global cues after the corresponding US cash close. The
India-close and US-close-window observations carry distinct `capture_context` values and retain the provider
generation timestamp and declared latency; neither is silently presented as an exact exchange closing print.

Before enabling durable storage of Upstox D5 depth, global cues, FII/DII activity, company profiles, and
corporate-action payloads, review your Upstox plan and data terms. Then add this non-secret GitHub repository
variable under **Settings → Secrets and variables → Actions → Variables**:

`PROSPECTIVE_DATA_LICENSE_ACK=true`

Without that variable, scheduled Stage-1 observations still run, but the new provider payloads remain
disabled and a `LICENSE_ACK_REQUIRED` quality event is recorded. D5 snapshots use the existing Full Market
Quote API; D30 is intentionally not requested because it requires Upstox Plus. No second data vendor or paid
cloud service is required by this code. GitHub Actions usage, Supabase storage growth, and any Upstox plan
charges remain account-dependent and must be checked in those services.

After deployment, manually run the workflow once with mode `scan` during the scan window and once with mode
`close`. Verify `scheduled_stage1.quote_coverage >= 0.90`, no candidate action is `Buy`, and the shadow
summary reports stored records rather than rejected/missing records. Alert on `LICENSE_ACK_REQUIRED`,
`FEATURE_QUALITY_FAILED`, `QUOTE_COVERAGE_LOW`, any `PARTIAL` run, or a missing expected collection run.
