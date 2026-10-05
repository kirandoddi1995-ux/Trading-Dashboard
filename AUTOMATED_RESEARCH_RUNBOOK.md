# Offline research foundation — owner runbook

This is development automation, not a new strategy, executable derivatives backtester,
commissioned cost model, promotion system or live approval source. The two
parked benchmarks stay parked. No validation/holdout file is opened. No new
Supabase storage, credentials, network requests or scheduled collectors.

## Upload and verification

1. Upload the files listed in AUTOMATION_PROGRESS.md together, preserving the
   `tests/` and `.github/workflows/` paths. No live application file changes.
   EXPECTED_EQUITY_CODE_SHA256 stays unchanged.
2. Wait for quality/resilience/CodeQL. The quality workflow adds strict type
   checks and offline imports; its full test and extracted-ZIP gates remain.
3. Locally install the CI-only tooling:
   `.venv\Scripts\python.exe -m pip install -r requirements-automation.txt`
4. Run:
   `.venv\Scripts\python.exe -m mypy --config-file mypy-automation.ini --cache-dir "$env:TEMP\research-mypy-cache"`
   and `.venv\Scripts\python.exe -m pytest -q tests/test_research_automation.py -p no:cacheprovider`.
   Full-suite SQL tests additionally need EQUITY_TEST_PGLITE_MODULE pointing at
   `tests/sql-harness/node_modules/@electric-sql/pglite`.

## Freeze and register the existing development report

Keep all reports, specs, ledger and outputs OUTSIDE the repository. Commands
below use the existing private TradingResearch directory without copying it.
No command supplies tokens. The provided SHA identifies the previously run
development report; independently compare Get-FileHash before registration.

```powershell
$researchDir = 'C:\Users\banga\Documents\TradingResearch'
$baseArgs = @('--spec', "$researchDir\automation-spec-v1.json",
              '--data-root', $researchDir,
              '--ledger', "$researchDir\automation-trials.sqlite")
.venv\Scripts\python.exe automated_development_checks.py @baseArgs --prepare --report-relative nifty-development-2022-2024.json --report-sha256 57e429252a3510d8eb7e8b95f4e184dfca9b331ef35fc9fcf8bc7ad11333500a
```

Expected SPEC_PREPARED. Preparation does not open the report. Review the spec:
only the two parked benchmark diagnostics, 2022–2024, actual source/lock hashes,
Python/numpy/pandas versions; no tunable search parameters. Then:

```powershell
.venv\Scripts\python.exe automated_development_checks.py @baseArgs --register
.venv\Scripts\python.exe automated_development_checks.py @baseArgs --output "$researchDir\automation-result-001.json"
.venv\Scripts\python.exe automated_development_checks.py @baseArgs --output "$researchDir\automation-result-002.json"
```

Expected REGISTERED, then RESEARCH_CHECK_COMPLETE twice with identical result
hashes and approval_authority false. Output files cannot be replaced. Re-registering
the same spec is rejected. An environment/source/input change blocks; never edit
a registered spec to conceal a change. A separately reviewed new spec is a new
research version, not a retune. This runner rechecks the existing replay report;
it does NOT rerun its signals from underlying bars or certify the original replay.

SUCCEEDED means diagnostics computed and committed to the ledger, not that a
result-file copy was published. Publication can independently fail (disk/ACL);
the CLI returns BLOCKED. Retry with a new output name; it creates a visible new
attempt. Failure messages deliberately omit raw paths and exceptions. Inspect
private state locally, never upload it to logs. Interrupted STARTED attempts
remain visible, not silently converted to success. The SQLite update/delete
triggers and hash chain prevent accidental alteration, not malicious file-owner
modification or undetectable removal of the last records. Back up the ledger and
specs privately; do not treat this as production execution evidence.

## Next owner/evidence boundaries

The opt-in `research-self-check.yml` reuses the entire quality workflow (unit/SQL,
golden/causal checks, imports, static checks, audits and ZIP gate); it does not
read private datasets, call Upstox or replay real market files. It declares no
secret inheritance, has a non-overlapping concurrency group and a bounded
25-minute job. On weekdays it requests 23:47 IST; GitHub may delay/skip it, so it
is not a heartbeat or proof that a market collector ran.
Implementation reference: [GitHub reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
and [workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

After uploading and green CI, first run **Actions → Offline research and
application self-check → Run workflow** manually. Then, only if you want recurring
offline checks, add the repository Actions variable `AUTOMATED_SELF_CHECK_ENABLED`
with the exact value `true`. Leave it absent/false to keep scheduled jobs disabled.
This is independent of option capture and every archive/research switch. Do not
put private data or credentials into Actions for this job. Alerts/watchdog still
need separate commissioning; a green synthetic run is not live market validation.

Before automated genuine derivatives
replays: confirm Upstox Plus/expired history availability, source terms, dated
costs and lots, executable quote evidence, and actual broker intraday deadlines.
Keep missing values missing. OHLC or assumed slippage is not fill evidence.
Daily-bar probabilities must not approve intraday derivatives.

Deployment separation is an OWNER task, not implemented by this batch. In GitHub
create a release branch from a reviewed green commit. In Streamlit app settings
verify whether changing the deployed branch is supported; otherwise create a
separate app pointing to that branch and verify its OIDC/secrets privately before
switching users. Do not move deployment until an authenticated UI smoke test and
runtime health checks pass. Existing app-import and extracted-ZIP tests do not
exercise an authenticated browser session. Do not relax auth to enable tests.

Persistent external alerts and a heartbeat watchdog are also uncommissioned.
Choose an independent host/static IP and notification account with the owner;
configure credentials privately, send a supervised test, stop its heartbeat and
prove missed-heartbeat detection and retry behaviour before relying on it.
No Sentry/Healthchecks/Telegram account or hosted setting was created here.

Validation (2025) and holdout (2026) require a separate reviewed access process.
There is deliberately no unseal flag in this implementation. No automatic
selection, promotion, parameter tuning, fixed performance threshold or order
placement exists. Remaining live-commissioning work is recorded in
AUTOMATION_PROGRESS.md, not represented as complete by this first slice.

## Frozen causal replay from bars (development only)

`automated_directional_replay.py` executes the existing two parked rules with
their original confirmation counts; no tuning interface exists. Use separate
development-only `bars.csv` and `sessions.json` files outside the repository,
not the combined 2022–2026 readiness pack. Do not hand-edit session eligibility,
previous-close provenance or gaps to make a run pass. Both files require known
SHA-256 hashes; the calendar is part of the frozen input, not guessed by weekdays.

CSV columns: timestamp,Open,High,Low,Close,available_at. JSON: the existing explicit
replay session list (open, close, previous_close, source, availability_basis,
eligibility/exclusion and out-of-session metadata). Missing/delayed sessions stay
visible and reset warmup. This adapter does not independently verify NSE source
documents or reconstruct historical revisions. Owner-verified readiness is still
required. Historical-final assumed bar-end availability stays labelled.

```powershell
$replayDir = 'C:\Users\banga\Documents\TradingResearch\development-only'
$replayArgs = @('--spec', "$replayDir\replay-spec-v1.json",
                '--data-root', $replayDir, '--ledger', "$replayDir\replay-trials.sqlite")
$barsHash = (Get-FileHash -LiteralPath "$replayDir\bars.csv" -Algorithm SHA256).Hash.ToLowerInvariant()
$sessionsHash = (Get-FileHash -LiteralPath "$replayDir\sessions.json" -Algorithm SHA256).Hash.ToLowerInvariant()
.venv\Scripts\python.exe automated_directional_replay.py @replayArgs --prepare --bars-relative bars.csv --bars-sha256 $barsHash --sessions-relative sessions.json --sessions-sha256 $sessionsHash
# Review spec and provenance BEFORE this registration.
.venv\Scripts\python.exe automated_directional_replay.py @replayArgs --register
.venv\Scripts\python.exe automated_directional_replay.py @replayArgs --output "$replayDir\replay-001.json"
.venv\Scripts\python.exe automated_directional_replay.py @replayArgs --output "$replayDir\replay-002.json"
```

Expected SPEC_PREPARED, REGISTERED, REPLAY_COMPLETE twice with matching hashes.
All remain approval_authority false. Compare trade lists and accepted/excluded
session counts with the previously reviewed development run; do not assume that
matching repeated outputs prove profitability. Session-end closes and next-open
references are synthetic underlying exposure, not broker fills or deadline proof.
No futures/option P&L, margin validation or commissioned costs are claimed.

The transitive local import closure is fingerprinted, not just a manual module
list. After this batch, old checkpoint specs will fail source/environment matching
as intended; prepare and explicitly register a newly reviewed spec, never overwrite
the old one. No private research file has been opened by the agent in this build.

## Observation comparison / health contracts (not live yet)

`research_replay_comparison.py` provides a private local ObservationJournal and
exact 75-decision regular-session comparison. No app capture hook is installed.
This version compares the shared raw directional-bias decisions for the frozen
NIFTY recipe, not confirmation-specific entries/exits, sizing, fills or multi-
instrument output. Those need separately versioned identities before integration.
Observed records are explicitly RESEARCH_OBSERVATION; reconstructed references
are REPLAY_REFERENCE. Both have approval_authority=false and fill_evidence=false.
Reconstructed rows are rejected by the observation journal. An identical durable retry is acknowledged; a conflicting
same-key record is rejected, never overwritten. Preserve original capture receipt
metadata for retries. Keep its SQLite file outside the repository and back it up
privately; triggers/checksums do not protect against a malicious file owner.

A future producer must retain complete recoverable input bundles, not just hashes.
That includes warmup/history, previous-close source, verified calendar, source/spec
versions and actual availability times. No feed acquisition or Drive upload is
implemented here. Do not claim future nightly reproduction is possible until that
producer and its persistence have been commissioned. A recorded bar-end basis and
historical-final assumed bar-end basis are NOT interchangeable. No late observation
is backdated. Capture lag is displayed, not compared to an invented tolerance.
Missing records stay in the 75-row denominator; no paired records gives a null
match fraction. Available vs unavailable decision matches are reported separately;
matching 75 warmup/unavailable records is not 75 usable trading signals.
Regular boundaries are validated, but holiday eligibility must
come from the frozen verified calendar. Specials are not silently scored.

`automation_health.py` is a pure operator-check contract, not a running watchdog.
It requires an explicit reviewed lane scope, expected release, actual clock status,
commissioning state, expected run identity, deadline and matching completion receipt.
Completion BEFORE deadline counts; a previous run/start/page-load does not. Missing
policies, expectations or receipts cannot report healthy. It has no polling, network
notification, secret input or automatic action. Host/account/auth setup, supervised
failure drills and live wiring remain owner-dependent. See
AUTOMATION_FOUNDATION_ACCEPTANCE.md for the full implemented/uncommissioned boundary.

## Recoverable private development replay

`research_input_archive.py` stores exact source bytes in compressed, hash-addressed
private files, deduplicating identical inputs. It verifies size, SHA and complete
compression streams before acknowledging storage. No Drive/DB access or deletion.
Keep the entire archive, recipes and SQLite ledger backed up privately. Local disk
survival is not guaranteed by this code. Restore also needs the matching source
and dependency environment; environment drift blocks rather than changing results.

First prepare the development-only replay spec using the earlier instructions.
Then use new filenames outside the repository; these examples use a private root
chosen by you. Do not copy these private files into GitHub.

```powershell
$privateRoot = 'D:\TradingResearch\automation'
.venv\Scripts\python.exe archived_directional_replay.py prepare --replay-spec "$privateRoot\replay-spec.json" --spec "$privateRoot\archived-spec.json"
# Review the new recipe before explicit registration.
.venv\Scripts\python.exe archived_directional_replay.py register --spec "$privateRoot\archived-spec.json" --ledger "$privateRoot\trials.sqlite"
.venv\Scripts\python.exe archived_directional_replay.py run --spec "$privateRoot\archived-spec.json" --ledger "$privateRoot\trials.sqlite" --data-root "$privateRoot\inputs" --archive "$privateRoot\archive" --output "$privateRoot\archived-result-1.json"
```

Read `manifest_sha256` from that result, then reproduce without the original files:

```powershell
.venv\Scripts\python.exe archived_directional_replay.py restore --archive "$privateRoot\archive" --manifest-sha256 '<manifest_sha256>' --output "$privateRoot\restored-1.json"
```

Compare `report` and `references` exactly, not whole result hashes (run and restore
envelopes differ). Restore verifies previously registered computation; it is not
a new hypothesis trial. Restore checks the recorded report/reference hashes.
Never overwrite prior results. A computed SUCCEEDED trial is not proof that final
result publication succeeded; inspect both ledger and output. Publication errors
can be retried with a new output filename.

References bind only consumed prefixes, previous close, warmup and session rules;
future prices never enter earlier input hashes. Trial identity separately binds
the complete files. Actual observed records must use this exact comparison/prefix
scheme before comparison is meaningful. The development checker is not wired to
the new prospective producer; see FORWARD_DATA_RUNBOOK.md for its distinct actual-
receipt policy and offline reproduction. Historical
full-session eligibility and assumed bar-end availability are retrospective research
metadata, not proof of real-time availability. Do not backdate receipts or relabel
replay as observed. No real 2025/2026 file is opened by these commands.

## One-command offline replay self-check

After the reviewed archive run, compare all accepted development sessions against
the private observation journal:

```powershell
.venv\Scripts\python.exe research_replay_check.py --archive "$privateRoot\archive" --manifest-sha256 '<manifest_sha256>' --journal "$privateRoot\observations.sqlite" --output "$privateRoot\comparison-1.json"
```

Exit 0: every expected decision in every accepted session matches, with no excluded
sessions. Exit 1: evidence is missing/different or calendar sessions were excluded;
read the private output to see each cause. Exit 2: integrity/read/publication failed;
stdout gives a sanitized BLOCKED message. Existing output files are never replaced.
The journal is opened read-only, never created or repaired by this check. An absent
journal remains absent and produces missing observations, not a green result.

This runner does not turn archived historical bars into captured observations.
Its output always has live_capture_verified=false, approval_authority=false and
fill_evidence=false, even when every comparison matches. A passing comparison
proves mechanical agreement only. It does not commission costs, certify capture
provenance, certify profitability or unlock suggestions. No schedule is added for
private replay; commissioning the new prospective producer and persistent host
remains an owner-reviewed step. Do not upload private journal or comparison results.
