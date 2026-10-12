# Next storage package: two-copy restore evidence and alert boundary

Refreshed 13 Oct 2026 after Upload 10. Keep the existing filenames below: this
is the same eight-file unuploaded package, not an additional successor package.
The manifest and checker already exist. Only this runbook and its manifest hash
needed refreshing; the two implementations, checker and three tests are unchanged.

## Compatibility and timing after Upload 10

All eight pinned prerequisite identities match the local reviewed Upload 10
sources and the disposable public-tree candidate that passed the combined suite.
None is a version-aware capture module. The package does not import or activate
the new producer, and no existing app, capture, workflow or factory imports these
new modules. Exact latest-main compatibility is checked again in the owner's
clean clone before committing; do not treat a local check as a GitHub SHA audit.

It may be reviewed and uploaded during Tuesday's capture because merging adds
inactive files only. There is no need to wait until market close for the PR.
Do NOT copy it into the installed capture folder or rebuild/update that folder
while a session is running. Keep capture supervision first if owner time conflicts.
The release hold, fingerprint expectations and all current tasks remain unchanged.

The three owner prerequisites do not block upload, imports, synthetic tests or CI.
They DO block real custody commissioning. Key availability is required to verify
the original signed generations; the dummy disk drill is preliminary and does not
prove a full-generation restore; Drive capacity/retention must be measured before
real archive cadence is agreed. None of those owner attestations turns this package
into permission to delete data. The alert component still needs a real independent
runner/transport, durable journal and owner-visible delivery/heartbeat tests.

## Decision and scope

One PR, eight paths, two independent components. Custody is first in the build
chain because verified copies and a successful restore are prerequisites for
removing hot data. Alerts are a separate component in the same upload, not a
dependency of restore verification. Neither component is automatically activated.
This package does not commission custody, deletion, notifications or live writers.

Existing exporter/materializer/copy auditor are reused unchanged. The new
recovery_custody_rehearsal joins their real verifications: both extracted copies
must authenticate against the externally retained backup contract/checkpoint;
each is restored into its own NEW directory; both witnesses, original signatures
and whole-image identity are rechecked. Source and extracted copies are re-read.
Only then is a report signed through the existing catalog receipt codec. It binds
the bundle digest/root/receipt, generation, replica names, two restores and time.
Verification needs independently retained report anchors AND full bundle digest.
Signed evidence is a proposal, not a committed/durable independent anchor.

Paths must be absolute, mutually non-overlapping and not links/junctions. No
overwrite, cleanup, retry-in-place, source deletion, checkpoint advance, ACK or
live factory is supplied. Failure names its stage but hides underlying exceptions.
Partial targets are retained. Caller protects ACLs and excludes concurrent file
mutation; this is not an adversarial filesystem/power-loss custody implementation.
An extracted Drive copy and disk copy on this PC are byte checks, NOT proof of
their remote origin, encryption or separate physical custody. Those flags stay
false. A six-table SQLite cut is NOT a full Supabase/application restore.

storage_alert_delivery uses the existing storage_capacity_watch evaluator, not
a second threshold policy. UNKNOWN/stale/missing inputs produce an alert envelope.
Monitor/schedule identity, evaluation time and the redacted report are content
bound. One injected transport attempt distinguishes exact acceptance from an
ambiguous/lost reply. No blind retries. Exceptions never print URLs or credentials.
The runner must durably retain the envelope BEFORE sending, then reconcile by
its exact ID. This package supplies no provider transport, durable alert journal,
scheduler or independent heartbeat host. Acceptance is not owner receipt. All
delivery commissioning, authenticated-input and global-enforcement claims stay
false. A stopped monitor cannot detect itself: external missed-heartbeat coverage
is a mandatory later acceptance case, not an optional dashboard warning.

## Why not wait for owner prerequisites?

Synthetic six-table generations and injected transports can prove the byte,
identity, error and timing contracts now. They cannot prove encrypted key/device
custody or delivery to the actual owner. Build those contracts first, then run
real commissioning once the owner prerequisites exist. Do not pass an attestation
boolean into a deletion gate and call it encryption verification.

## Zero-cost deployment choice (unchanged)

Keep Supabase as the bounded hot store; keep existing private Drive plus the
independent encrypted external disk for cold generations. No additional cloud
service or paid plan is commissioned. Google free storage is up to 15 GB shared
across Drive/Gmail/Photos, not 15 GB dedicated to this project:
https://support.google.com/googleone/answer/9004014 . Owner-measured usable free
space and written retention are still missing. Two folders in the same account
are not independent custody. Offline disk copies must cover the EXACT generation
being considered for removal; an old disk copy cannot authorise a new generation.
Until generation-specific custody/restore and live gate wiring are proven, no
removal. Expected operational cadence/RPO must be agreed before scheduling it.

Supabase documents the free 500 MB database limit separately from physical disk
and WAL, and dashboard disk metrics are updated daily:
https://supabase.com/docs/guides/platform/database-size . Retain the existing
500,000,000-byte planning ceiling and 24,000,000-byte admission floor; do not
replace SQL measurements with rounded dashboard readings. The owner's 55-day
estimate is a two-scan workload estimate, not a deadline guarantee. Measure all
writers and actual allocation; archive and maintenance can also temporarily grow
the database. This package does not change admission or grant capacity credit.

Changelog checked 12 Oct: HTTP cipher deprecation begins no earlier than 10 Nov
and explicitly excludes direct Postgres/pooler connections; no implementation
change applies to these offline components: https://supabase.com/changelog .

## Exact upload manifest — one clean-clone PR

Source root: `C:\Users\banga\Desktop\kiran_share_market`.
Each source below goes to the identical relative destination in the clean clone:

| Source | Destination |
| --- | --- |
| recovery_custody_rehearsal.py | recovery_custody_rehearsal.py |
| storage_alert_delivery.py | storage_alert_delivery.py |
| custody_alert_upload_check.py | custody_alert_upload_check.py |
| tests/test_recovery_custody_rehearsal.py | tests/test_recovery_custody_rehearsal.py |
| tests/test_storage_alert_delivery.py | tests/test_storage_alert_delivery.py |
| tests/test_custody_alert_upload.py | tests/test_custody_alert_upload.py |
| CUSTODY_ALERT_PACKAGE_2026-10-12.md | CUSTODY_ALERT_PACKAGE_2026-10-12.md |
| CUSTODY_ALERT_UPLOAD_2026-10-12.json | CUSTODY_ALERT_UPLOAD_2026-10-12.json |

No staged files, SQL, migrations, workflows, configuration, private data or old
packages are included. Uploads 7–10 and their manifests remain unchanged. Keep this
document as the current continuity checkpoint for this successor, rather than
silently changing old hash-pinned progress/manifests. New work is inactive.

In a CLEAN clone of exact green main after Upload 10, before copying, set
`$custodyAlertBase = git rev-parse HEAD`. Create the owner-reviewed branch normally,
then copy exactly the eight paths. Do not copy the entire local workspace.

Package check:

```powershell
python custody_alert_upload_check.py --base $custodyAlertBase
```

Expected `UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI`, blockers [], hosted_changes 0.
Checks include exact LF-normalized file identities, unexpected changed paths and
eight unchanged prerequisite modules. Missing files or outdated prerequisites
block; do not bypass. Commit only AFTER rehearsal, since base must still be HEAD.

Focused tests:

```powershell
python -m pytest -q tests/test_recovery_custody_rehearsal.py tests/test_storage_alert_delivery.py tests/test_custody_alert_upload.py tests/test_recovery_six_export.py tests/test_recovery_materialization.py tests/test_recovery_replica_audit.py tests/test_storage_capacity_watch.py
```

Wait for quality, resilience and CodeQL on the exact PR/merge SHA. No disposable
native rerun is needed for these Python-only contracts; no SQL changed. Green
CI alone does not commission any of the real-world custody/delivery claims.

## Owner steps — safe prerequisites, not commissioning

1. Keep Tuesday 13 Oct's installed version-aware capture and its reviewed procedure unchanged.
   Do not install these modules there or alter tasks, expectations or release hold.
2. Privately save the CURRENT ledger signing key in an encrypted password-manager
   note. Record its logical key name/version and date, not a public value/hash of
   the key. Do not rotate it. Check historical versions privately; report only
   available/unavailable by key ID. Unknown historical keys remain a restore block.
   Use the existing OWNER_KEYS_AND_BACKUP_RUNBOOK.md; do not paste any key in chat,
   GitHub, a command argument, terminal output, or the repository.
3. On the empty external disk, do the harmless encryption/restore rehearsal first:
   use 7-Zip from its official site, choose 7z / AES-256 / encrypt file names, and
   a unique strong password retained privately outside that archive. Use only a
   dummy text file. Close the application, reopen/extract into a NEW empty private
   folder and compare the dummy file; confirm a wrong password cannot extract it.
   7-Zip's format documentation describes AES-256:
   https://www.7-zip.org/7z.html . Do not archive live state or keys yet, and never
   include the only password/key copy inside the archive it unlocks. Disconnect
   the disk afterwards. This prerequisite is not the full-generation restore drill.
4. In your Google storage page, check actual used/free space and which account
   holds the private archive. Record measurement time, bytes where available,
   other account consumers, and agreed retention: preserve verified generations
   and anchors until a newer generation has independently passed restore/custody.
   No emptying Trash, automatic deletion or permission changes in this step.
5. Review/upload this eight-file group through one PR; this can precede steps 2–4.
   Report prerequisite results
   as status/counts only. Do not run a real rehearsal against installed capture or
   production state yet: the owner CLI, encrypted archive identity/remote-origin
   binding, protected durable anchors and full application drill remain to build.

## Next build sequence and acceptance requirements

1. Owner-facing custody adapter: explicit private source contracts, one frozen
   generation, original-key availability, encryption operation, exact encrypted
   file readback from Drive and disk, NEW extraction/restore on both, protected
   anchor persistence with crash/unknown-commit recovery. Bind original encrypted
   bytes to the authenticated generation; witness, image and topology tests above
   are prerequisites, not a substitute. Add cold catalog/segment custody too:
   six-table local recovery alone does NOT authorise ledger/archive pruning.
2. Independent alert runner: authenticated read-only fresh SQL measurement,
   reviewed session-aware job inventory, durable alert journal and real provider
   transport, exact request receipts, owner-visible delivery test, and external
   dead-man heartbeat proving watcher loss itself alerts. Operates independently
   of the producer/app and does not store growing alert payloads in Supabase.
   Zero-cost channel/host retention and availability still need verification.
3. All writer factories + cold readers + bounded recovery: prove there is no
   bypass writer/reader, and test restore before changing production factories.
4. Universe content-hash shadow normalization; no in-place historical overwrite.
   Validate byte/semantic parity and dependency-aware reference reachability.
5. Source-specific bounded retention and exact cold lookup: only generation-bound
   verified custody/restore permits archive-then-remove; ledger roots/chain and
   original ACK/fence semantics remain intact. Peak allocation must fit reserve.
   Prove steady-state under missed archives, Drive full, disk absent, alert outage,
   collector bursts and restore. Only then commission hosted changes as owner steps.

## Local validation / continuity

13 Oct refresh: all package and Upload 10 identities passed before edits. After
the documentation refresh, the manifest hash was regenerated: the focused
package/recovery suite passed **148 tests** in 24.91 seconds; pyflakes and strict
mypy on the six package Python files passed. Both package manifests passed and
an import search confirmed only tests import the new implementations. No runtime implementation
changed, so the successful 12 Oct combined candidate remains the runtime baseline:
**3336 passed, 4 skipped, 2 subtests passed** in 623.10 seconds, including both this
package and Upload 10. The full suite was not rerun for this documentation-only refresh. Actual
latest-main PR and post-merge CI remain mandatory.

Earlier storage-only public-code candidate: **3305 passed, 4 unchanged skips, 2 subtests passed**
in 392.89 seconds. Baseline 3257 + 48 new tests; no test-count reduction.
Focused combined recovery/custody/alert/package suite: **148 passed**.
Whole public-root/tests pyflakes PASS; strict mypy on all six new Python inputs
PASS; existing automation mypy (19 inputs) PASS; new inactive imports PASS.
Full suite includes offline app import/Streamlit boot and disposable SQL tests.
No native SQL implementation changed, so no native race claim is added.

Final self-review corrected UTC normalization of signed report time, separated
full bundle digest from the embedded root-receipt digest, pinned both identities,
made post-send clock failures redact to unknown rather than driver text, and
checked that report claims cannot silently grant custody/deletion/approval.
Preflight validates both new targets before the first restore; final readbacks
cover both extracted copies and both restored targets. Failure retains partials.
All fixes were included in the successful full candidate suite.

Reviewed public equity fingerprint unchanged:
`03ad7baa68ebaad1f64b1cd3c356455e1c18cb8f23f027652de303b64b4f8478`.
No Streamlit expectation change or release promotion is requested. Final-only
documentation/manifest updates are checked again with exact-file focused tests.

No credentials, private state, installed capture, hosted resources, sealed
2025/2026 data or real notifications were accessed. The storage objective remains
unfinished; review-only work must not be mistaken for commissioned deletion.
