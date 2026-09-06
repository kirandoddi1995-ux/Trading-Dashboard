# Production external-action gate

Repository controls are implemented and tested, but the application must remain **NO TRADE** or safer until the following provider-side controls are configured and independently verified.

- Put `MODEL_ARTIFACT_SIGNING_KEY`, `RUNTIME_EVIDENCE_SIGNING_KEY`, and two independent entries in `MODEL_APPROVER_KEYS_JSON` in a managed secret store. Do not reuse the evidence-ledger key.
- Configure a licensed secondary NSE quote source and set `SECONDARY_QUOTE_PROVIDER_URL`; validate timestamp alignment and executable-side tolerances before enabling recommendations.
- Connect `OTEL_EXPORTER_OTLP_ENDPOINT` to a monitored backend with paging for missing critical spans, SLO burn, outbox age, safety-state changes, auth failures, and role misuse.
- Configure `DEPLOYMENT_ROLLBACK_TARGET` to an immutable prior Streamlit release/revision and connect the canary `ROLLBACK` decision to the hosting API. The repository does not possess or create hosting credentials.
- Configure `SECRETS_MANAGER_URI`, automated rotation/revocation, access audit logs, and expiry alerts. Rotate at least every 90 days.
- Configure `NTP_MONITOR_ENDPOINT` and alert/block at an absolute offset above 250 ms.
- Enable Supabase PITR/backups. Run an isolated restore, verify ledger chains and the restricted role, and set the signed drill facts: `RECOVERY_DRILL_AT`, RPO (<=15 minutes), RTO (<=60 minutes), ledger verification, and role verification.
- In GitHub, protect the `production` environment with independent reviewers. Store all secret values as environment secrets and non-secret endpoints/attestations as environment variables.
- Connect the protected workflow's verified authorization output to the actual durable model registry/deployment endpoint. Until that integration is configured, successful CI means **authorized package produced**, not **production deployed**.

Run `python production_readiness.py --strict` in the protected environment. Any missing requirement is a failed deployment and a runtime safety finding.

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
