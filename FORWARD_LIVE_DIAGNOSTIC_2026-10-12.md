# 12 October capture incident — additive diagnostic, not a guessed data repair

Upload 7 remains unchanged. This separate package adds a launcher and tests;
it does not edit frozen capture modules, today's config, journals or tasks.

## Evidence and decision

Owner reports first poll REMOTE_VERIFIED, followed by LOCAL_RECORD_POLL failures.
Owner-authorised read-only check of today's named journal found quick_check PASS,
observations=1, forward_context=1, expected columns, no producer lock and no
WAL/SHM sidecars. All 23 frozen installed source hashes match the prepared config.
No credential values, input prices, raw errors or connection strings were printed.
These checks do not reproduce the fresh provider response or prove no transient
SQLite lock occurred during a past poll.

The new bounded diagnostic was also run read-only against the specifically
authorised session with the installed interpreter/dependencies: structure PASS,
both counts still one, one input reference verified, no producer lock, zero
network calls, credential reads and writes. This did not install the launcher or
change a task. State verification is not provider-response finality verification.

The existing producer rejects any revision to previously committed closed-bar
values. Its generic failure classifier hides that code. A synthetic first-success
then revised-closed-candle poll reproduces the failure pattern. The owner's
09:55:30.501 supervised launcher poll subsequently confirmed
CLOSED_BAR_REVISION_REVIEW_REQUIRED at LOCAL_RECORD_POLL. The rejection is
confirmed; the actual revised fields are not yet known. Do not infer a provider
price revision until the redacted field report establishes it. Comparison is of
six numeric values, not receipt metadata. Ordinary int/float equality and equivalent
timezone offsets do not explain this rejection.

[Upstox's intraday V3 documentation](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/)
defines the timestamp as the candle start and the seven OHLC/volume/OI fields.
That page does not establish a hard finalisation guarantee at bar-end plus
30 seconds. The first-receipt policy must not silently become a final-price claim.

Keep scheduled polling disabled for diagnosis. Do not clear locks, delete the
first observation, rebuild the journal, change its input values, re-prepare after
open, or weaken closed-bar checks. Missed decisions stay missing. Audit can stay
enabled; its success is not a permission to resume polling.

## Exact source → destination paths for the separate PR

Source prefix: C:\Users\banga\Desktop\kiran_share_market\.
Destination: root of the owner's fresh clean-main clone.

| Source | Destination |
|---|---|
| forward_local_diagnostic.py | forward_local_diagnostic.py |
| tests/test_forward_local_diagnostic.py | tests/test_forward_local_diagnostic.py |
| FORWARD_LIVE_DIAGNOSTIC_2026-10-12.md | FORWARD_LIVE_DIAGNOSTIC_2026-10-12.md |

This initial three-file list is now subsumed by the single ten-file manifest in
FORWARD_REVISION_RECOVERY_2026-10-12.md after the close revision was confirmed.
Do not upload both groups separately. Do not copy the dirty workspace or revise Upload 7.
Check `git status --short` in the clean clone against this list. Require PR CI on
the exact tree before merging. No hosted settings, SQL, release, Streamlit
expectation or migration changes belong to this package.

Focused verification:

```powershell
python -m pytest -q tests/test_forward_local_diagnostic.py tests/test_forward_capture_diagnostics.py tests/test_forward_nifty_producer.py -p no:cacheprovider --basetemp "$env:TEMP/forward-local-$([guid]::NewGuid().ToString('N'))" --tb=short
python -m mypy --strict --follow-imports=silent forward_local_diagnostic.py tests/test_forward_local_diagnostic.py
python -m pyflakes forward_local_diagnostic.py tests/test_forward_local_diagnostic.py
```

## Owner steps now: preserve today's frozen code

Use the existing `$forwardPrivateState` variable. With poll disabled and no manual
poll running, copy ONLY the additive launcher beside the installed scheduler.
The owner already installed its first version; replacing this unfrozen diagnostic
with the reviewed field-report version is authorised. No existing frozen module
or session configuration is replaced. Compare the two launcher file hashes after
copying; they must match.

```powershell
$newDiagnostic = 'C:\Users\banga\Desktop\kiran_forward_20261007\forward_local_diagnostic.py'
Copy-Item -LiteralPath 'C:\Users\banga\Desktop\kiran_share_market\forward_local_diagnostic.py' -Destination $newDiagnostic
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\Users\banga\Desktop\kiran_share_market\forward_local_diagnostic.py', $newDiagnostic
Set-Location -LiteralPath 'C:\Users\banga\Desktop\kiran_forward_20261007'
.venv/Scripts/python.exe forward_local_diagnostic.py --root "$forwardPrivateState"
.venv/Scripts/python.exe forward_local_diagnostic.py --root "$forwardPrivateState" --mode inspect --session-date 2026-10-12 --confirm-run
```

Preview: zero state/credential/network reads or writes. Confirmed inspection:
SELECT-only bounded checks of the explicitly named session, original observation
hashes, context hashes and archived input references. It rejects SQLite sidecars
rather than risking sidecar creation in a purported no-write check. It assumes
writers remain paused across reads; it is not an atomic multi-file custody proof.
No database is created if missing, no schema is repaired, no lock is removed.

If LOCAL_STATE_STRUCTURE_CHECK_PASSED and producer_lock_exists=false, run ONE
supervised poll at the next future five-minute boundary plus 30 seconds:

```powershell
.venv/Scripts/python.exe forward_local_diagnostic.py --root "$forwardPrivateState" --mode poll --confirm-run
```

This delegates to the unchanged scheduler, including its existing bounded-lateness,
calendar, session, licence, token, clock, source-hash and producer guards. It
adds an in-process failure classifier and a read-only comparison around the
existing market GET; both wrappers are restored on exit. No additional market
GET is made. The field report has stored/matched/revised/absent counts and the
names of changed fields, with timestamps but no prices or other field values.
It never authorises resumption, modifies a candle, or suppresses rejection.
If this extra diagnostic fails, its fixed error category is printed and the
unchanged producer still checks the original response. Existing
Drive/transport classifications take priority, so network exceptions do not become
mislabelled filesystem errors. The launcher is not imported by frozen seeds and
does not alter their source bytes. No after-open refreeze or catch-up mode exists.

Share only redacted JSON. Never share config, credential stores, prices, raw
exception text or private input files. Keep scheduled poll disabled until the
category is reviewed; a passed structural inspection does not authorise recurrence.

## Decision after the classified result

- REMOTE_VERIFIED / OBSERVATION_RECORDED: verify count increments and the Drive
  receipt, then decide recurrence after another supervised future-slot success.
- CLOSED_BAR_REVISION_REVIEW_REQUIRED: preserve original evidence and keep poll
  disabled. Do not substitute revised prices or ignore a changed volume field.
  Next engineering is a versioned/quarantined source-revision contract and an
  explicit prospective session policy; it cannot silently alter today's recipe.
  The field report distinguishes OHLC changes from volume/open-interest changes.
  A changed non-price field still breaches today's frozen six-field policy.
  Absence of a stored bar in a response is missing evidence, not a match.
- PRODUCER_ALREADY_RUNNING_OR_STALE_LOCK: verify no producer process exists and
  inspect the lock privately before any separately authorised repair. Never use
  an automatic unlink/retry.
- LOCAL_SQLITE_BUSY/LOCKED: identify the owning process; do not kill a writer,
  retry aggressively, or remove SQLite files. Recheck after a clean process exit.
- Corrupt context/journal/input or identity/constraint failures: preserve all
  files, quarantine the session and diagnose a private copy. No recreation/reset.
- Disk/permission/file errors: inspect free space and ACLs privately; preserve
  unknown commit status. Fix the resource cause, not the evidence records.
- Unclassified failure: keep blocked; the missing cause is still missing. Do not
  pretend the closed-bar reproduction explains an unrelated exception.

## Permanent repair and continuity

The classified launcher is usable without mid-session frozen-source changes.
After actual cause confirmation, build a regression reproducing it through the
real job boundary. Future direct classifier integration belongs to a reviewed
after-session package and a newly prepared next session, not today's frozen config.
No production safety gate is loosened to resume collection. Storage custody,
writer/cold-reader wiring, retention and alerts remain pending after the live issue.

The permanent design must separate received source snapshots from accepted
decision inputs. Each received revision needs its own immutable content hash,
actual receipt time, source/config/code identity and predecessor binding. A
replay may use only the version available at its decision time, never a corrected
bar received later. Missing historical receipt times cannot be invented. Changed
versions must not overwrite the journal or recompute previously published
decisions. Raw-quarantine coverage must have its own denominator and status;
it cannot reduce the original missing-decisions count or claim fill evidence.
This prospective design is NOT commissioned by this diagnostic package. There
is currently no reviewed raw-quarantine launcher authorising scheduled capture.
Until one exists, keep the poll task disabled if revision rejection persists.

Validation at initial handoff: combined synthetic suite 101 passed; corrected
strict typing and lint clean; field-report launcher suite 53 passed. The earlier
typing failures were fixed, not ignored. Complete public-candidate validation
is recorded below when finished. No agent live market request or credential read.

Full public-candidate check of the initial classifier/inspection version:
3,169 passed, 4 skipped, 2 subtests passed (777.76 seconds). The subsequent
field-report version has 53 focused tests passing, strict typing/lint/import
checks passing; its final full public-candidate suite passed 3,185 tests,
4 skipped and 2 subtests (745.46 seconds). A separate raw-only recorder was
subsequently added; its combined candidate has its own validation record in
FORWARD_REVISION_RECOVERY_2026-10-12.md. Do not mistake this result for full
verification of the later raw-only/evidence-reader candidate. Require clean-main PR checks.
