# Capture first; bounded storage next

Status: local opt-in research implementation, not commissioned. No installed capture,
tasks, hosted resource, release setting, secret or existing evidence is changed.
This document is the continuity record for this additive package.

## Decision and order

1. Restore useful **prospective research observation capture** with versioned inputs.
   Missed forward observations cannot be recovered by replaying final candles.
2. In parallel, retain measured storage admission and the existing scan-only load.
   Treat the owner's approximately 55-day estimate as planning runway, not permission
   to defer checks for 55 days. Check actual size/growth at least each trading day.
3. Commission independent encrypted custody, real restore and independently delivered
   capacity alerts. The separately prepared custody/alert package may follow this one;
   this capture package does not depend on it. Its offline checks alone do not authorize deletion.
4. Wire guarded writers and exact cold readers, then deduplicate universe history and
   commission bounded source-specific retention. Demonstrate bounded steady-state growth
   before increasing collection load. Stop new writes at the existing admission floor.

No paid service is required by this package. Raw capture remains in private local files
and the already configured private Drive archive, not Supabase. A numeric provider
revision is retained and annotated, never declared harmless by an invented tolerance.

## Evidence contract

- Each received snapshot and its actual receipt time is inserted once in a new
  `state/versioned-v1/journal.sqlite`. Its selected inputs and research observation are
  committed in the same transaction. Later snapshots never update earlier observations.
- Selection is the latest version actually received at or before that observation's
  cutoff. A later correction may change a **later** observation's prefix, not an earlier
  decision. All versions and revision annotations remain in the exported generation.
- Missing prefixes persist as raw polls without an observation. A later complete response
  permits only the current slot's observation, never synthetic earlier observations.
- Monday 12 Oct's original journal, one recorded observation, 74 missing slots and
  quarantine remain untouched. There is no conversion, rescore or retrospective replay
  into accepted forward evidence. New-format observations are a separate series.
- The existing parked-rule mathematics is unchanged. Its warm-up can report unavailable
  observations; `recorded_decisions` does not mean actionable signals or successful trades.
  Finality is not established. Approval, fill evidence and training eligibility remain false.
- This is NIFTY **index** research, not executable options/futures fills. The existing
  verified 09:15–15:30 index window remains unchanged. The unresolved derivative 15:40
  question does not silently extend this window or establish a broker exit deadline.
- A pre-open sidecar recipe pins the original owner-file configuration, policy and
  transitive sources. Changes after freeze block rather than silently adopt new code.
- Default CLI is a zero-read, zero-network, zero-write preview. Confirmed polls delegate
  to the unchanged scheduler/job's licence, credentials, date, slot and clock gates.
  The adapter replaces only process-local producer/publisher bindings and restores them
  on exit; run it in a dedicated process, never concurrently inside the dashboard.
- New Drive objects use a new format/name. Both data and manifest bytes must download
  identically before an acknowledgement receipt. Drive failure does not undo a committed
  local poll. A later successful cumulative generation includes earlier committed polls.
  Never retry an ambiguous commit at the same slot or use the old `--backup-only` tool
  on the new journal. Dedicated offline/remote restore tooling for this format is not
  yet commissioned; the logical verifier replays each stored as-of observation.
- Audit verifies local logical evidence and reports counts, not remote custody or
  trade approval. SQLite append-only triggers are operational safeguards, not protection
  against an administrator rewriting the entire database. Independent authenticated
  custody and witnesses remain separate work.

## Exact upload group (one PR, eight new files)

Source base: `C:\Users\banga\Desktop\kiran_share_market\`.
Destinations below are relative to the clean repository clone; source suffix equals
destination suffix. Do not upload the whole working folder or any private JSON/secrets.

| Source suffix → destination | Purpose |
| --- | --- |
| forward_versioned_producer.py → forward_versioned_producer.py | Atomic versioned journal and verified generation |
| forward_versioned_capture.py → forward_versioned_capture.py | Explicit pre-open/poll/audit launcher |
| versioned_capture_upload_check.py → versioned_capture_upload_check.py | Exact clean-clone check |
| tests/test_forward_versioned_producer.py → tests/test_forward_versioned_producer.py | Producer, revision, corruption and full-session tests |
| tests/test_forward_versioned_capture.py → tests/test_forward_versioned_capture.py | Launcher and unchanged-job integration |
| tests/test_versioned_capture_upload.py → tests/test_versioned_capture_upload.py | Packaging tests |
| VERSIONED_CAPTURE_2026-10-12.md → VERSIONED_CAPTURE_2026-10-12.md | Runbook and continuity |
| VERSIONED_CAPTURE_UPLOAD_2026-10-12.json → VERSIONED_CAPTURE_UPLOAD_2026-10-12.json | LF-normalized hashes and prerequisites |

On the clean clone at the exact latest main SHA, copy only these eight paths, then:

```powershell
$versionedBase = git rev-parse HEAD
.venv/Scripts/python.exe versioned_capture_upload_check.py --base $versionedBase
.venv/Scripts/python.exe -m pytest -q tests/test_forward_versioned_producer.py tests/test_forward_versioned_capture.py tests/test_versioned_capture_upload.py
.venv/Scripts/python.exe -m mypy --strict --follow-imports=silent forward_versioned_producer.py forward_versioned_capture.py versioned_capture_upload_check.py tests/test_forward_versioned_producer.py tests/test_forward_versioned_capture.py tests/test_versioned_capture_upload.py
```

Require package check, tests and all exact-commit PR/main CI checks green. No direct push,
release promotion or Streamlit fingerprint update is part of this package. If another
upload lands first, use a fresh exact-main clone and rerun; prerequisites must still match.

## Owner installation and supervision (not executed by the agent)

If review, tests and installation cannot finish **before open**, continue the already
reviewed raw-only procedure for that date. Never freeze this interpretation after open.

1. With capture tasks disabled and no poll process running, prepare a separate clean
   capture code folder from reviewed main using the existing capture installation and
   private credential procedure. Include the two new root modules and all their import
   dependencies from that same commit; do not mix sources or copy private state into code.
   Keep the existing installed folder and task export for rollback. Do not modify Monday's
   files or use the source workspace's unfinished files as installed dependencies.
2. From the **new** folder, run its usual owner-file preparation for the current session
   with the existing private `$forwardPrivateState`. Verify the source date, attestation
   and clock result as usual. Do not change the reviewed previous-close procedure.
3. Preview, then freeze the new interpretation before 09:15 IST, after base preparation:

```powershell
.venv/Scripts/python.exe forward_versioned_capture.py --root "$forwardPrivateState" --session-date 2026-10-13 --mode prepare-policy
.venv/Scripts/python.exe forward_versioned_capture.py --root "$forwardPrivateState" --session-date 2026-10-13 --mode prepare-policy --confirm-versioned-research
```

Expected: `VERSION_POLICY_PREPARED`, zero decisions added, authority/training false.
Use the real current session date; this date-pinned example is not an unattended schedule.
On any block, do not reset a journal, remove a lock or overwrite the sidecar.

4. At ONE future five-minute slot plus 30 seconds, then one more future slot after success:

```powershell
.venv/Scripts/python.exe forward_versioned_capture.py --root "$forwardPrivateState" --session-date 2026-10-13 --mode poll --confirm-versioned-research
```

Expected: `REMOTE_VERIFIED`, capture status `VERSIONED_OBSERVATION_RECORDED` or
`VERSIONED_INPUT_BLOCKED` with raw evidence retained. Counts increase only for actually
recorded observations. A missing-prefix block is not a fabricated zero signal. Inspect
the new `versioned-v1/receipts` privately; report only redacted statuses/counts.
If job reports BLOCKED, keep recurrence disabled and retain local state for review.
No same-slot retry, no catch-up. Success is a transport/evidence check, not proof of edge.

5. Only after two supervised verified future-slot polls, the owner may export the existing
   task and explicitly opt in to date-pinned recurrence. Change its action to the new
   folder's reviewed Python executable, working directory and the exact poll arguments
   above, keeping the reviewed timing, no-catch-up and overlap safeguards. Do not leave
   a raw-only task and versioned task enabled together. Disable the date-pinned task
   after the final 15:30:30 poll. Do not extend the session or enable tomorrow automatically.
6. At 15:40, run the new format's local audit:

```powershell
.venv/Scripts/python.exe forward_versioned_capture.py --root "$forwardPrivateState" --session-date 2026-10-13 --mode audit --confirm-versioned-research
```

Expected: `VERSIONED_LOCAL_AUDIT_PASSED`, actual raw/recorded/missing counts;
`remote_custody_verified: false`. The old audit counts only the old journal; it cannot
certify new-format coverage. Keep receipts and Drive objects privately for independent
readback/restore commissioning. Return status/counts and timing, never credential values.

## Remaining work and acceptance boundary

Before trusting these observations for ML: dedicated new-format restore and remote
receipt audit, supervised provider-revision/restart experience, future-paper outcome
tracking with executable instruments and dated costs, and explicit research governance.
The recipe does not turn the parked rules into a profitable strategy. No 2025/2026
historical data is read. Storage custody, alerts, guarded writer/cold-reader wiring and
bounded retention remain required; capture-first is an ordering decision, not abandonment.

## Completed validation and self-review

31 new tests passed (29 producer/launcher and 2 packaging). The combined disposable
public-tree candidate, including the previously prepared but unuploaded custody/alert
package, passed 3,336 tests / 4 skipped / 2 subtests in 623.10 seconds. It used synthetic
fixtures and the existing offline SQL harness; no live capture state or hosted resource
was accessed. The eight-file package has no dependency on that custody/alert package.
Require exact-main PR CI as well; these counts do not claim those pending files are on main.

Whole-candidate pyflakes passed; strict typing passed for all six new Python files and
the existing 19-file automation set. New imports, deployed app import and suite boot
checks passed. Package identities verified. Equity fingerprint remained
`03ad7baa68ebaad1f64b1cd3c356455e1c18cb8f23f027652de303b64b4f8478`;
do not change Streamlit expectations or the release hold.

Self-review corrected missing-journal accidental recreation and missing append-only
guard detection, with tests. Revision/restart, atomic failure, separate original state,
readback mismatch, unchanged-job integration, clock/pre-open freeze, full 75-slot session,
postclose audit and packaging cases passed. No additional defect was found in the final
review. Real owner supervision and the explicitly uncommissioned custody/restore work
remain acceptance boundaries, not claims supplied by offline tests.
