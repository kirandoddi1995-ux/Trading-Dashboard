# Foundation acceptance and boundaries

This is an evidence inventory, not a claim that the trading system or a strategy
has been validated. All build checks used synthetic fixtures; real 2025/2026
prices/outcomes remain unopened. No hosted resource or owner setting was changed.

## Implemented / mechanically checked

- Frozen, explicitly registered development-only recipes for existing report
  diagnostics and actual causal underlying replay. No tuning or unseal interface.
- Exact input hashes, transitive local source hashes, dependency/runtime identity.
- Exact compressed private input retention, deduplication, archive-only recovery
  with result verification, and consumed-prefix replay references. Replay origin
  is mandatory and cannot satisfy the observed-decision journal.
- Durable local trial lifecycle with failed/interrupted attempts visible, append-only
  triggers, serialized idempotency/conflict rules and repeated-result checks.
- Atomic non-overwriting result publication; computation vs publication separated.
- Reviewed synthetic five-session engine golden plus hand-derived reversal trades;
  prefix invariance, calendar exclusions, missing/delayed bars, IST and forming-bar
  guards. Existing engine math is reused unchanged. These do not prove alpha.
- Private append-only observation journal and full 75-decision session comparison:
  missing observations/replay, input/basis mismatch, delayed availability and output
  mismatch remain separate. Research records explicitly prohibit approval/fill claims.
- One-command offline archived-replay check across all accepted sessions, opening
  the journal read-only. Missing observations and excluded sessions cannot pass.
  Even full synthetic agreement never claims live capture or execution evidence.
- Pure health contract: configured expected release vs actual hash (never self-
  compare), real clock-state input, explicit commissioning and expected-run completion
  identity/deadline. Missing data does not report healthy. No automatic remediation.
- CI imports/types/full suite/SQL safety and original extracted-bundle gate retained.
  Opt-in scheduled offline self-check reuses CI without market/DB secrets.
- Owner runbook and continuity manifest, updated after each completed checkpoint.

## Owner/evidence-dependent: NOT commissioned or proved live

- Independent forward producer: journal/comparison APIs are built but NOT wired into
  app.py. A genuine producer must persist the full input bundle or a recoverable
  archive plus its hash, including history, calendar, source versions, previous close,
  availability and receipt times. A hash alone cannot reconstruct inputs for replay.
  Historical-final bars are not interchangeable with recorded point-in-time inputs.
- Actual date-partitioned files for the frozen runner: owner prepares development-
  only copies privately; never upload them or open holdout/validation in automation.
- True derivatives net P&L/margins: old underlying references are not fills. Dated
  charges/lots/deadlines, Upstox Plus and expired futures access remain unverified.
- Option executable replay needs recorded bid/ask/size; candles are insufficient.
- Live producer/monitor persistence and alert destinations, independent host/static
  IP, unattended auth, email/watchdog accounts and expected heartbeat policy require
  owner commissioning. Contract tests are not a functioning remote watchdog.
- Authenticated Streamlit synthetic UI checks and release-branch deployment need
  owner-controlled identity/settings. Existing import/ZIP tests do not exercise UI.
- External archive/storage measurements remain owner-only. No Supabase connection
  or storage probe was added; local research does not consume its scarce capacity.
- No automated AI repair/merge/promotion, source mutation or performance-gate tuning.

## Next reviewed commissioning sequence

1. Review/upload the complete file manifest; wait for CI. Run the offline self-check
   manually before optionally setting AUTOMATED_SELF_CHECK_ENABLED=true.
2. Review/register development-only recipe and compare repeated replay outputs.
3. Decide producer persistence/host and record complete input bundles under a frozen
   source/spec identity. Only then wire observation capture, supervised first.
4. Verify exact replay comparison against those records, including interrupted capture,
   absent data and input revisions. Do not silently accept partial matching subsets.
5. Commission independent completion receipts/notifications and deliberately miss a
   heartbeat. Acknowledgment must not imply resolution. Configure real release and
   clock expectations; a start/page-load/HTTP ping must not masquerade as completion.
6. Commission costs/data/broker timing and authenticated deployment smoke separately.
   Strategy validation and holdout access require a new explicit reviewed decision.

Until then, the overall programme is partial. Do not advertise unattended real-data
backtesting, live replay parity or monitored derivative safety as operational.

## Requirement-by-requirement handoff audit

The local foundation implements frozen recipes and append-only registered trials
in research_integrity.py, automated_development_checks.py and
automated_directional_replay.py. Their tests check sealed dates before file access,
actual content dates, source/runtime drift, missing data and failed/interrupted
attempts. No unseal interface or parameter search is provided.

Replay causality is checked by synthetic engine goldens and prefix-invariance
tests. Existing intraday engine math is reused rather than replaced. Calendar,
special-session, missing-bar, timezone and forming-bar checks remain explicit.
Output is underlying directional research, never net futures/options P&L.

Recoverability is proved by archive-only restoration while original-file reads
are forbidden in a test. Corrupt/oversized/truncated archives fail; earlier prefix
identities do not change when future prices change. Observation tests reject
reconstructed references as captured records. Integrated checks use read-only
journal access, retain missing decisions in the denominator and flag exclusions.

Automated local self-checking is wired into the full quality workflow, not a
separate reduced test list. SQL safety, lint, types, app import, dependency audit,
resilience and extracted-release gates remain. The optional scheduled workflow
inherits no secrets and does not collect data or mutate code/settings.

Owner-only operations remain owner-only: publishing, release branch/settings,
notification accounts, credentials, real source verification and supervised
commissioning. The runbook gives local commands and the Actions enable/manual
steps; no green local result is represented as hosted evidence. No database
migration or extra Supabase storage is required by this foundation.

Independent choices differ from the reference report where evidence or authority
is missing: no arbitrary performance promotion thresholds; no fabricated option
fills; no fixed broker exit time; no auth bypass for UI tests; no automated repair,
issue writes or merges; no real-data nightly schedule before private input/host
commissioning. These are deliberate safety boundaries, not implemented claims.
The broader end state still needs genuine capture provenance, verified dated
costs/contracts/execution evidence and owner-controlled live deployment/alerts.
