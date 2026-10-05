# Checked dashboard releases

Scope: Streamlit application code only. Model authorization/promotion/rollback,
research schedules, option capture and database data/schema are unchanged.
No hosted configuration was changed during implementation.

## Subsequent-release compare guard repair

The first publication did not need a comparison because release was absent.
Later promotion/rollback exposed an implementation defect: GitHub.call rejected
any '..', including GitHub's legitimate SHA...SHA comparison separator. The earlier
Fake-based policy tests bypassed this real transport guard. This was a defect in
our adapter, not failed CI, divergent history or missing permissions.

The repair permits only GET /compare/<full-lowercase-SHA>...<full-lowercase-SHA>.
Traversal, encoded paths, fragments, backslashes/control characters, branch-name
comparisons, malformed separators and non-GET comparison methods stay blocked.
New offline tests use real GitHub.call for preview, promotion with an existing
release and paused rollback; only the HTTP response transport is mocked.

Repair upload group (four files, preserving folders):
- dashboard_release.py
- tests/test_dashboard_release.py
- DASHBOARD_RELEASE_RUNBOOK.md
- AUTOMATION_PROGRESS.md

If DASHBOARD_RELEASE_ENABLED remains true, this fix can automatically promote the
newest fully checked main commit, including the waiting post-cutover app changes.
For a controlled check, owner may pause it to false, let active publication finish,
upload/review the complete group and wait for exact-final-SHA CI. Run preview from
main; expect READY with previous set to the current release SHA and blockers [].
Then enable and promote. An atomic single reviewed merge avoids partially uploaded
groups. No workflow/permission change is needed for this fix. Do not manually move
release or change the independent fingerprint early to work around the bug.

Until a fixed controller has reached release, dispatch preview/promotion/rollback
from fully checked MAIN, not the old release controller that still has this bug.
Rollback still requires promotion paused, explicit confirmation and a previously
verified ancestor target. Once release contains the repair, the normal branch
choice instructions below apply again.

This repair does not change the app fingerprint. The pending post-cutover source
still expects 36e17a7552357bb9fa68197117874a694691fc01baf24a7e6a07713cfc4429e3;
the currently deployed pre-patch release still expects its old 2893995...c7b9.
Confirm successful PROMOTED output and the candidate's reported fingerprint,
then update Streamlit Secrets as described below. Failed verify/publish skipped
does not constitute deployment; keeping the old Secret until promotion was correct.

Reference: https://docs.github.com/en/rest/commits/commits#compare-two-commits

## How it works

The app will follow `release`; development/manual uploads and research stay on
`main`. `Checked dashboard release` wakes after quality, resilience or CodeQL
workflow completion. Its read-only job polls for up to 15 minutes for the newest
main SHA's successful main-push quality and resilience runs and successful CodeQL
default-setup analysis jobs. The trusted managed workflow path is
`dynamic/github-code-scanning/codeql`, event `dynamic`, in this repository on
main at the exact SHA. Its latest run/attempt must succeed, with exactly one
successful job for each of actions, javascript-typescript and python. Workflow
metadata and job SHA/run/attempt/branch are checked; the run is re-read to detect
reruns during verification. A YAML workflow merely named CodeQL cannot substitute.
PR runs, skips, neutral results, old success
before a failed rerun, another SHA or a fork never count. Missing checks block.

Only a ready result permits the separate write job. It rechecks main, release,
all required results and the controller commit's checks, then moves release to
the **same existing commit**, with no merge or generated code commit. A single
concurrency group serializes promotion and rollback; running publishers are not
cancelled midway. Automatic promotion only fast-forwards. No personal access
token, cloud secret or deployment credential is needed; only the job's scoped
GITHUB_TOKEN. No CI artifact, market data or PR code is downloaded into the writer.

The write job records `dashboard-verified/<full-SHA>` tags and reports the previous
and selected SHAs and selected equity fingerprint. A verified tag proves the
commit passed the gates; it does **not** prove hosted health or that a branch update
after the tag succeeded. Record successful PROMOTED output and hosted observations
to identify a genuinely known-good rollback target.

Several close uploads: an older completion checks the current main head; it never
publishes an older trigger SHA. A head change while waiting causes SUPERSEDED.
Another completion checks the new head. Rechecks prevent normal queued-event races.
GitHub offers no atomic transaction spanning both main and release: a new upload
can arrive between the final read and branch update. That can briefly publish an
older **checked, coherent** commit; it cannot produce a mixture of files. Keep
release/tag updates exclusive to this workflow. No system can infer that an owner
intends another future upload: a green intermediate commit can be released if
uploads pause long enough. For a strict batch boundary, upload all folders to one
temporary branch using GitHub's branch selector, then merge one reviewed PR into
main. Do not change the default branch from main.

Promotion verifies code and CI, not the running app's in-flight work. A Streamlit
restart can interrupt scans or lose unacknowledged ephemeral SQLite outbox entries.
Plan uploads in quiet periods after delivery drains, including after cutover;
automatic promotion has no hosted drain handshake. Guaranteed interruption-free
deployment needs a separate durable queue/drain design. A green release also does
not restore local files or prove external services/configuration are healthy.

## 1. Upload and validate (owner)

For the default-setup CodeQL repair, upload these five changed files together,
preserving folders (the other files from the original installation are unchanged):
- dashboard_release.py
- .github/workflows/dashboard-release.yml
- tests/test_dashboard_release.py
- DASHBOARD_RELEASE_RUNBOOK.md
- AUTOMATION_PROGRESS.md

Keep `DASHBOARD_RELEASE_ENABLED` absent or `false` while uploading. Existing main
deployment remains exposed to uploads until the one-time cutover is finished;
do this installation in a quiet maintenance window. Wait for the **final full
commit**'s quality, resilience and CodeQL to pass. Quality now includes actual
AppTest boot of the copied application: OIDC login screen and full Settings page
with synthetic local development configuration, fresh state and denied external
I/O. This proves those paths only, not live OAuth, broker/database integration,
every authenticated page or hosted configuration. Existing extracted ZIP/import
verification remains mandatory.

The local full-suite command (normal project terminal) is:

```powershell
$env:EQUITY_TEST_PGLITE_MODULE = Join-Path (Get-Location) 'tests/sql-harness/node_modules/@electric-sql/pglite'
$releaseTestTemp = Join-Path $env:TEMP ('dashboard-release-tests-' + [guid]::NewGuid().ToString('N'))
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp $releaseTestTemp
.venv\Scripts\python.exe -m pyflakes dashboard_release.py tests/test_dashboard_release.py tests/test_streamlit_boot.py
.venv\Scripts\python.exe -m mypy --config-file mypy-automation.ini
```

## 2. Preview and establish release (owner)

1. Repository → Actions → Checked dashboard release → Run workflow.
2. Select branch main, mode preview, leave rollback SHA empty and confirmation
   unchecked. Run. Expected READY for the exact newest main SHA with blockers [].
   Publish job is skipped; preview never changes a branch or tag.
3. If CodeQL is listed as a blocker although the UI is green, inspect that commit's
   `codeql.reason` in the preview JSON. Success shows VERIFIED, run_id,
   run_attempt, workflow_id and missing_or_failed_jobs []. The three mandatory
   job names are listed in required_jobs. Missing jobs, an inactive/changed
   managed workflow, a failed/latest rerun or API errors remain blockers.
   Do not rename a normal job or relax the gate to satisfy it.
   The earlier aggregate-check policy was wrong for this default-setup push:
   read-only public API inspection of bb31d2bc723c268b055f1a481e0cb355e4d81a3e
   found workflow 339597929 named **CodeQL**, managed path above, successful
   dynamic run 37287267947, attempt 1, and all three expected jobs. The UI's
   lowercase codeql label is not the API workflow name. Both spellings are wake
   triggers; dynamic events are now accepted for the CodeQL handoff, while the
   API still independently verifies the managed path. No aggregate check is
   required. No additional token permissions, secrets or CodeQL settings needed.
   This gate verifies successful analysis execution, not absence of every alert;
   keep reviewing Security → Code scanning. If languages/default setup change,
   review and update this explicit policy and its tests rather than auto-detecting
   a smaller required set. Unsupported advanced setup fails closed.
4. Settings → Environments → New environment → name `dashboard-release`.
   Configure deployment branches/tags as **Selected branches and tags**: add branch
   rules for exactly `main` and `release`, with no tag rule. Leave required reviewers
   and wait timers off for automatic promotion; add no secrets. These server-side
   restrictions prevent the publisher job from deploying from a feature ref.
   Then Settings → Secrets and variables → Actions → Variables → New repository
   variable: `DASHBOARD_RELEASE_ENABLED`, value `true`. This authorizes future
   automatic ref updates after checks, independently of all capture/archive flags.
5. Actions → Checked dashboard release → Run workflow, branch main, mode promote.
   Expected PROMOTED (or ALREADY_RELEASED on repetition). Record the full SHA,
   previous SHA and fingerprint. Code tab → branch selector → release should show
   that exact SHA. Initial publication can create release; no hand-created commit
   or copying files into release is needed.
6. Branch/ruleset policy: reserve release and dashboard-verified tags for this
   publisher. Never upload or merge directly into release. Do not require PRs or
   release-branch CI that the GITHUB_TOKEN update cannot satisfy: required results
   are checked on the exact main SHA, and token-generated pushes do not generally
   start other workflows. Existing org/repo restrictions may block the ref write;
   if so it fails and release stays unchanged. Review the rule rather than grant
   a broad PAT or disable security checks. A protection rule prohibiting force
   updates also blocks deliberate rollback; choose that trade-off explicitly.

## 3. Switch Streamlit (owner, quiet maintenance window)

Streamlit identifies an app by repository, branch and entrypoint. Its documented
coordinate-change route is delete then redeploy, not an in-place branch edit:
https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/rename-your-app

1. Stop starting scans. Check that evidence and checkpoint pending delivery are
   **zero**, no scan/sender work is active, and recovery/checkpoint health is
   healthy. Do not delete/reboot with unacknowledged local outbox records: local
   SQLite is ephemeral. Wait/investigate if these checks fail.
2. Privately save the COMPLETE current Streamlit Secrets and app settings outside
   the repo/chat/logs; record Python version, exact app URL/custom subdomain and
   sharing/access settings. Preserve positions.owner_key, OIDC client settings,
   cookie_secret, allowlist, database role and expected hash/build/policy values.
   App deletion must not be treated as preserving these settings automatically.
3. Confirm release SHA and expected fingerprint from step 2. Complete CI and the
   preview **before** deleting the existing app.
4. share.streamlit.io → app menu → Delete app → confirm. Then Create app/Deploy
   from GitHub → same repository → branch release → entrypoint app.py. Advanced
   settings: same Python version and privately restored secrets. Request the same
   custom subdomain if available; verify the actual resulting URL before relying
   on it. This involves downtime and is not guaranteed to retain the URL.
5. If the URL changes, privately change auth.redirect_uri to the new exact
   `https://<app-host>/oauth2callback` and register that same URI with the identity
   provider's existing OAuth client. Preserve authorization allowlists. If the
   URL is retained, verify the existing URI still matches. Restore Cloud sharing
   restrictions if used; application OIDC is a separate gate.
6. Verify logged-out access shows only sign-in, allowed sign-in works, unexpected
   identities are rejected, runtime fingerprint/build/policy/clock/recovery are
   expected, and remote database uses the existing restricted role. Review all
   safety hold banners. A passed offline boot is not evidence of hosted readiness.
7. Record this SHA as the first observed known-good dashboard release. Confirm
   scheduled research and option capture still use main; default branch stays
   main. Do not launch a second fully configured dashboard concurrently merely to
   test cutover: auto-start scans/feed connections can duplicate production work.

## Fingerprint ordering (every production-code change)

EXPECTED_EQUITY_CODE_SHA256 stays a **Streamlit Secrets** value, not a GitHub
variable or a generated self-expectation in the app. The publisher reports the
candidate's public hash without modifying that secret. For this installation,
production code/fingerprint is unchanged:
2893995505709b1b6a6bfcea342a2edb3770319c695297234747cf1b6801c7b9

After a later automatic promotion changes fingerprinted code, the old secret
deliberately causes NO_TRADE until you update it to the reported exact release
fingerprint. Prefer updating **after** successful promotion, then verify runtime
health against release SHA. Updating early would block the previous app instead.
Also review EXPECTED_APP_BUILD and RESILIENCE_POLICY_SHA256 if that release changes
them. Reconcile all values on rollback. Configuration mismatch never silently
passes. Automatic code promotion thus removes a per-upload branch step, but it
does not remove the owner step for changed external safety expectations. Removing
that step requires a separately reviewed trusted expectation channel; this
implementation does not weaken the current gate. Research workflows on main do
not read the dashboard's Streamlit Secrets.

## Rollback (owner)

1. Settings → Actions variables → DASHBOARD_RELEASE_ENABLED = `false`. Wait for
   any running Checked dashboard release publisher to finish; the same concurrency
   group serializes rollback. Variables are supplied to a run as configuration,
   so changing one is not instant revocation of an already authorized run. Clear
   any queued/verification-only old runs (cancel only while no publish job is
   running), and confirm no prior publication is active or queued before dispatching
   rollback. Do not cancel a publisher during a ref write. Concurrent GitHub pending
   runs can replace one another; confirm your rollback actually ran.
2. Stop new dashboard scans and drain local delivery as above. Choose an observed
   known-good SHA from a successful release log. Confirm its verified tag exists
   and its schema/contracts remain compatible with today's database. Review current
   advisories against its pinned dependencies too: stored green checks are historical
   evidence, not a fresh vulnerability audit. Missing/expired CI records block the
   automatic policy rather than trusting the tag alone. Code rollback
   does not undo migrations, stored data, secrets or external provider changes.
3. Actions → Checked dashboard release → Run workflow. Prefer branch release
   (its controller has already passed CI), mode rollback, paste the FULL 40-character
   commit SHA, check confirm_rollback. Main may also be used if its controller
   commit is fully checked. Do not choose a feature branch or arbitrary ref.
4. Expected ROLLED_BACK, exact ancestor SHA and fingerprint; release is atomically
   reset while main/research history stays intact. Missing marker, divergent SHA,
   failed checks, unverified controller or promotion still enabled blocks it.
5. Restore that release's expected fingerprint/build/policy in Streamlit Secrets,
   verify hosted login/runtime/health and keep promotion false until the cause is
   fixed. A webhook restart is asynchronous; confirm what actually loaded.
6. After the corrected newest main commit is green and reviewed, restore
   DASHBOARD_RELEASE_ENABLED=true and run mode promote. It fast-forwards from the
   rolled-back ancestor to the current checked head. No research dataset is reset.

Sources: GitHub workflow_run security/triggers and ref API:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run
https://docs.github.com/en/rest/git/refs#update-a-reference
https://docs.github.com/en/rest/actions/workflows#get-a-workflow
https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt
