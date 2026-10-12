# Provider close revision: preserve evidence and resume raw-only collection

## Decision and evidence

The owner's 10:10:30.172 poll found one retained closed bar, zero exact matches,
one revision and no missing retained bar. Only `close` changed for
2026-10-12T03:45:00Z (09:15 IST). The first receipt was at the 09:20:30 poll;
the fresh response differed. This confirms a provider-returned close change,
not timezone formatting, receipt metadata or int-versus-float equality.
It does not establish which close is independently correct or exactly when the
provider changed it. No prices were printed, no accepted evidence was rewritten.

Keep the original config, observation, input file, journal and verified receipt.
The first observation remains a record of what was received at that time, not
proof the provider had finalised the bar. Do not delete it or replace its close.
Do not ignore price, volume or OI revisions. Today's frozen decision producer
remains blocked; missed decision slots remain missing.

The additional recorder saves future source snapshots only. It is **not** a
repair that resumes decision scoring. Each snapshot includes both the original
accepted baseline and the newly returned rows with the actual new receipt time,
content hashes, original recipe identity, capture-code identity, changed-field
report, and explicit `training_eligible=false`, `decisions_added=0`,
`approval_authority=false`, `fill_evidence=false`, `finality=NOT_ESTABLISHED`.
New versions do not inherit an earlier availability time. Missing earlier raw
responses are not reconstructed from today's later full-history response.

The unchanged scheduler and job still perform calendar, slot/lateness, frozen
source, licence, token expiry, session and clock admission. This additive adapter
substitutes only a raw-only persistence/publication path in its isolated process.
It restores the process-local substitutions on exit. No installed source file,
task, secret, hosted setting, original input or accepted journal is edited by it.
It rejects malformed rows, stale locks, changed raw policy and duplicate slots.
It stores a snapshot before Drive publication and checks downloaded data and
manifest bytes before writing a raw-only receipt. On transport failure preserve
the local snapshot and stop; do not reset state, retry the same slot, or treat
an unacknowledged snapshot as remotely backed up.

## Today's owner steps

Owner evidence at 10:30:30.344 IST: preview zero reads/network/writes; first
raw-only poll REMOTE_VERIFIED / QUARANTINE_ONLY, decisions_added=0,
training_eligible=false, accepted recorded_decisions=1 / missing_decisions=74.
Second supervised slot 10:35:30.473 also verified. The owner exported the original
task to `forward-poll-original-20261012.xml`, changed only its action to the
date-pinned raw launcher and enabled it. Scheduled 10:40:30 returned exit 0;
three snapshots and three receipts were present. This establishes recurrence,
not complete-session coverage. The owner scheduled disabling at 15:32 after
the last 15:30:30 slot; it must disable future starts, not terminate an active poll.
The historical installation steps below are not instructions to repeat them.

Keep the poll task disabled while installing and supervising. Prepare stays
disabled. The original audit can remain enabled; raw-only snapshots do not alter
its counts. No credential re-entry or Drive-folder change is needed.

Copy ONLY these additive helpers beside the installed scheduler:

- C:\Users\banga\Desktop\kiran_share_market\forward_local_diagnostic.py
- C:\Users\banga\Desktop\kiran_share_market\forward_revision_quarantine.py

Destination for both: C:\Users\banga\Desktop\kiran_forward_20261007\.
Replacing the existing additive diagnostic is permitted; replace no frozen file.
Compare SHA256 of each source/destination pair. A mismatch blocks execution.

From the installed folder, with the existing `$forwardPrivateState`:

```powershell
.venv/Scripts/python.exe forward_revision_quarantine.py --root "$forwardPrivateState"
.venv/Scripts/python.exe forward_local_diagnostic.py --root "$forwardPrivateState" --mode inspect --session-date 2026-10-12 --confirm-run
```

Preview must show zero reads/network/writes. Inspection must pass with no producer
lock. At ONE next future five-minute boundary plus 30 seconds:

```powershell
.venv/Scripts/python.exe forward_revision_quarantine.py --root "$forwardPrivateState" --session-date 2026-10-12 --confirm-raw-quarantine
```

Expected: `mode=QUARANTINE_ONLY`, then `REMOTE_VERIFIED`,
`capture_status=QUARANTINE_ONLY`, recorded_decisions=1, missing_decisions=74.
These counts describe the unchanged accepted journal, not new decisions. The
raw-only data/manifest acknowledgment is in:

`$forwardPrivateState\2026-10-12\state\quarantine-v1\receipts\`.

Snapshots are separate immutable slot files under `quarantine-v1\snapshots\`;
`policy.json` binds the original recipe, accepted baseline and both helper hashes.
Do not change either helper after the first successful raw-only slot today.
Do not run the old decision poll concurrently with raw-only capture. The baseline
inspection assumes a paused original writer; it is not a concurrent multi-file
backup-cut proof. There is no automatic stale-lock deletion or same-slot retry.
Confirm the receipt's format is `forward-provider-quarantine-manifest-v1`,
status REMOTE_VERIFIED and decisions_added=0. Share only status/counts, not prices,
private files, Drive IDs or credentials. Verify a SECOND distinct future slot
before considering automatic recurrence. If either blocks, keep recurrence off.

### Optional recurrence, only after two supervised raw-only successes

This is a deliberate owner commissioning step for **raw collection today only**.
Do not simply enable the old task action: it would still call the blocked producer.

1. Open Task Scheduler and select `KiranTrading-Forward-poll`; confirm Disabled.
2. Export that task's XML to a private location outside the repository, with a
   new filename such as `forward-poll-original-20261012.xml`. Retain it unchanged.
3. Properties → Actions → Edit: retain the installed Python executable and the
   existing installed working directory. Set arguments to:

```text
"C:\Users\banga\Desktop\kiran_forward_20261007\forward_revision_quarantine.py" --root "C:\Users\banga\AppData\Local\KiranTrading\Forward" --session-date 2026-10-12 --confirm-raw-quarantine
```

4. Leave triggers, least-privilege account, IgnoreNew, no catch-up and execution
   timeout unchanged. Do not press Run outside a future slot. Enable the task.
5. Observe the next scheduled slot, LastTaskResult=0 and a NEW raw-only verified
   receipt. A green result means raw custody, never restored decision coverage.
6. After the last 15:30:30 slot today, disable the poll task. The explicit date
   also blocks this launcher tomorrow if disabling is forgotten. Do not restore
   and enable the old action for tomorrow until the prospective policy is reviewed.

At 15:40 retain the original audit result: expected SESSION_CAPTURE_INCOMPLETE
(exit 1), one accepted observation and 74 missing decisions. That nonzero audit
result is truthful missing decision coverage, not a reason to reset the journal.
Count raw snapshots and raw verified
receipts separately. There is no catch-up, no training admission and no claim of
independent backup custody. If today's remaining supervised slots are too few,
keep manual operation and skip recurrence entirely.

### Separate offline audit after capture stops

`forward_revision_evidence.py` is an additional read-only tool, not a change to
either frozen raw helper. Install it beside the helpers if wanted. After disabling
poll and verifying no poll/audit process is running, run:

```powershell
.venv/Scripts/python.exe forward_revision_evidence.py --root "$forwardPrivateState"
.venv/Scripts/python.exe forward_revision_evidence.py --root "$forwardPrivateState" --session-date 2026-10-12 --confirm-read
```

It must report QUARANTINE_LOCAL_EVIDENCE_CHECK_PASSED, accepted_observations=1,
missing_accepted_decisions=74, raw_snapshots=N and
locally_recorded_remote_verifications=N if all raw backups have acknowledged.
Any raw_snapshots_without_verified_receipt is real outstanding custody; preserve
those files for reviewed backup recovery. Corruption, orphan receipts, policy or
original-journal mismatch blocks; it never repairs or ignores failed evidence.
It reports only counts/classification, not field values or Drive IDs. It makes
no network calls, credential reads or writes. Local receipt checks do NOT freshly
verify Drive existence, source authenticity, or independent encrypted custody.

The same module implements a pure, inactive as-of source-version projection.
It selects only versions whose real known_at time is <= the requested cutoff;
later corrected closes cannot enter an earlier cutoff. It stays
decision_eligible=false and training_eligible=false. It is groundwork for a
future reviewed decision-input contract, not a newly approved research strategy.

## Settling-time rule and permanent next step

[Upstox V3 intraday documentation](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/)
documents bar-start timestamps but does not give a hard finalisation guarantee
at close plus 30 seconds. Moving to plus 60/90 seconds cannot honestly be called
a finality fix from this one incident. Raw-only capture retains plus 30 seconds
and real receipt times, with finality explicitly unestablished. Do not widen the
existing two-minute admission window to force success.

Before a new decision recipe is commissioned:

1. Obtain/document the provider's correction/finality semantics and use the
   raw versions to measure revision incidence and observed latency prospectively.
2. Specify an explicit as-of input policy: only versions actually received by
   that decision cutoff, never a later corrected close. Freeze it before a new
   session. Keep source revisions distinct from journal corruption.
3. Build a versioned reader and acceptance tests across successive revisions,
   missing bars, gaps, late responses, expiry/special days, restart and ambiguous
   writes. A corrected price must never rewrite an earlier outcome or input hash.
4. Reconcile revised bars against an independently sourced exchange/provider
   reference where available. If unavailable, record that absence honestly.
5. Commission separate raw coverage, accepted decisions, availability/finality,
   source revision, remote custody and fill-evidence reporting. Raw-only records
   remain excluded from analysis/ML until a reviewed, explicit admission exists.

This package implements source preservation and an offline as-of reader, not that full decision-policy
commissioning. No 2025/2026 historical holdout data is examined or retuned.

## Tomorrow: raw-only fallback, not restored decision scoring

After today's last poll has finished, confirm the task is Disabled. Keep the
exported original task XML privately. Do not restore its decision action for
tomorrow: the unchanged revision rejection would recur. Do not edit today's
helpers, config, journal or policy, or catch up missed slots.

Copy only the new `forward_quarantine_prepare.py` beside the installed scheduler
(compare source/destination SHA256). It is separate from the two frozen raw
helpers and does not change today's policy hash. No capture-folder change is
made by the agent. After the owner's usual **tomorrow's** owner-file preparation
has succeeded, and strictly before 09:15 IST, run from the installed folder:

```powershell
.venv/Scripts/python.exe forward_quarantine_prepare.py --root "$forwardPrivateState"
.venv/Scripts/python.exe forward_quarantine_prepare.py --root "$forwardPrivateState" --session-date 2026-10-13 --confirm-prepare-empty-journal
```

Expected: PREVIEW with zero reads/network/writes, then
EMPTY_QUARANTINE_JOURNAL_PREPARED, 0 recorded / 75 missing, credential/network
reads zero. It creates only a new empty journal/schema and inputs directory. It
does not record prices, decisions, source retrieval or a clock measurement.
All the actual poll's existing source/licence/auth/clock guards still apply.
If state already exists or anything blocks, keep tasks disabled and share only
redacted output. Partial new state is retained for review, never deleted/reset;
do not retry initialization. It cannot initialize after the market opens.

At 09:20:30 run ONE supervised future slot:

```powershell
.venv/Scripts/python.exe forward_revision_quarantine.py --root "$forwardPrivateState" --session-date 2026-10-13 --confirm-raw-quarantine
```

Require REMOTE_VERIFIED / QUARANTINE_ONLY, 0 decisions / 75 missing. Repeat at
09:25:30 only if the first succeeds. After two successes, explicitly change only
the disabled poll task's action date to 2026-10-13, retain the same executable
and working directory, then enable recurrence. Arrange a date-specific disable
after the last 15:30:30 poll (do not kill an active process). Leave the original
audit enabled; its truthful result is SESSION_CAPTURE_INCOMPLETE (exit 1),
0 accepted / 75 missing,
regardless of raw snapshot coverage. Prepare remains owner-supervised. No
standing decision-capture commissioning or automatic calendar-date rollover.

After capture stops, optionally copy the separate evidence reader and run its
read-only audit described above. Local verified-receipt counts are not a fresh
Drive check or independent backup-custody proof. A complete prospective versioned
decision policy, and its failure/restart/reconciliation tests, remain next; an
assumed delay or silently choosing the newest close is not the permanent fix.

## Consolidated upload group (one PR)

Upload 7 stays unchanged. Use a fresh, exact green-main clone; copy only these
ten paths from C:\Users\banga\Desktop\kiran_share_market\ to the same relative
destination. Do not copy local state, installed capture, secrets or dirty workspace.

| Source relative path | Clean-clone destination |
|---|---|
| forward_local_diagnostic.py | forward_local_diagnostic.py |
| forward_revision_quarantine.py | forward_revision_quarantine.py |
| forward_revision_evidence.py | forward_revision_evidence.py |
| forward_quarantine_prepare.py | forward_quarantine_prepare.py |
| tests/test_forward_local_diagnostic.py | tests/test_forward_local_diagnostic.py |
| tests/test_forward_revision_quarantine.py | tests/test_forward_revision_quarantine.py |
| tests/test_forward_revision_evidence.py | tests/test_forward_revision_evidence.py |
| tests/test_forward_quarantine_prepare.py | tests/test_forward_quarantine_prepare.py |
| FORWARD_LIVE_DIAGNOSTIC_2026-10-12.md | FORWARD_LIVE_DIAGNOSTIC_2026-10-12.md |
| FORWARD_REVISION_RECOVERY_2026-10-12.md | FORWARD_REVISION_RECOVERY_2026-10-12.md |

Package check: compare `git status --short` to exactly these ten paths in the clean
clone; no other paths may change. Require all PR checks on that exact tree. The
earlier three-file, six-file and eight-file lists are subsumed by this ten-file group, not an
additional upload. This package has no migration, hosted deployment, release
hold change or Streamlit fingerprint-expectation change.

```powershell
python -m pytest -q tests/test_forward_local_diagnostic.py tests/test_forward_revision_quarantine.py tests/test_forward_revision_evidence.py tests/test_forward_quarantine_prepare.py tests/test_forward_capture_diagnostics.py tests/test_forward_nifty_producer.py tests/test_forward_nifty_schedule.py --tb=short
python -m mypy --strict --follow-imports=silent forward_local_diagnostic.py forward_revision_quarantine.py forward_revision_evidence.py forward_quarantine_prepare.py tests/test_forward_local_diagnostic.py tests/test_forward_revision_quarantine.py tests/test_forward_revision_evidence.py tests/test_forward_quarantine_prepare.py
python -m pyflakes forward_local_diagnostic.py forward_revision_quarantine.py forward_revision_evidence.py forward_quarantine_prepare.py tests/test_forward_local_diagnostic.py tests/test_forward_revision_quarantine.py tests/test_forward_revision_evidence.py tests/test_forward_quarantine_prepare.py
```

Validation results and any remaining checks are recorded below before handoff.

## Validation and self-review

Final focused raw-only tests: 30 passed. Combined diagnostic, raw recorder,
producer, transport and scheduler tests: 169 passed. Strict typing and lint
pass for both modules and both test files; import checks pass without private
state or credential access. Tests use synthetic 2022 fixtures, not historical
2025/2026 datasets or today's private prices. The full field-diagnostic candidate
passed 3,185 / 4 skipped / 2 subtests; the six-file raw-only candidate passed
3,215 tests / 4 skipped / 2 subtests (770.66 seconds). The additional offline
evidence reader has separate focused/type/lint checks; its final eight-file
public-candidate full-suite status is recorded separately when finished.

Offline evidence-reader focused suite: 22 passed. Strict types and lint pass;
the corrected limits reject invalid read bounds before opening a file. Tests
cover exact receipt cutoffs, equivalent IST/UTC instants, no look-ahead, source
identity and same-receipt conflicts, original-journal baseline binding, damaged
snapshots, orphan/altered receipts, missing acknowledgments and no-write auditing.
The eight-file public candidate passed 3,237 tests / 4 skipped / 2 subtests
(830.23 seconds). The additive pre-open initialization suite passed 12 tests;
strict typing and lint pass across all eight Python module/test files. Import
checks pass. Self-review additionally bounded config reads before JSON decoding.
The final ten-file public-candidate full suite passed: 3,249 tests / 4 skipped /
2 subtests (938.57 seconds). This was a complete separate run of the final code,
not an inferred sum of focused counts. Require the owner's exact-tree clean-main
PR checks as well. All ten package files byte-matched the public candidate;
the candidate fingerprint was independently recomputed and remains unchanged.

The first bootstrap test attempt could not use the shared pytest temporary
directory (Windows permission denial); a dedicated new temporary directory fixed
that environment issue. Tests then exposed an incorrect inspection-result key,
which was fixed and covered by an end-to-end empty-journal/raw-poll test. New
failure coverage includes pre-open cutoff, naïve time, an existing state directory,
partial initialization, bad config, forbidden roots and crossing open while
initializing. No partial state is silently cleaned up or retried.

Next engineering order after this incident: freeze and test a version-aware
decision-input recipe separately from the original producer; then resume the
previous storage custody/writer/cold-reader/retention/alert chain. Upload 7 remains
unchanged. Raw capture functioning is not storage commissioning or ML evidence
admission. No new decision rule, settling delay or candidate tuning is introduced.

Self-review fixed two issues before handoff: real Drive transport accepts only
the `data` and `manifest` object kinds, and immutable policy creation must become
exact-byte verification on later slots rather than fail on every second poll.
Tests now enforce both, exercise two successive slots through the real job
boundary with fake transports, and assert original journal bytes stay unchanged.
Licence/auth/clock failures prevent market reads; remote data/manifest mismatch
retains local source bytes but writes no verified receipt. Duplicate slots and
changed code/baseline policy block. Unexpected errors remain redacted.

The reviewed public-candidate equity fingerprint is unchanged:
`03ad7baa68ebaad1f64b1cd3c356455e1c18cb8f23f027652de303b64b4f8478`.
This is not an instruction to update Streamlit; release holds and expectations
remain untouched. No hosted calls, installed-folder edits or task changes were
performed by the agent.
