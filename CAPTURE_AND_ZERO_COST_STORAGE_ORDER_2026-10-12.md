# Capture correctness first, then bounded zero-cost storage

## Decision and tomorrow

Build a small version-aware input foundation first; do not delay the permanent
storage chain behind a large strategy/model project. Tomorrow, Tuesday 13 October,
keep the tested raw-only fallback from FORWARD_REVISION_RECOVERY_2026-10-12.md.
Owner-file prepare -> new empty journal before 09:15 -> supervised raw-only polls
09:20:30 and 09:25:30 -> explicit date-pinned recurrence after both verify.
Do not restore the original decision action. Accepted coverage remains zero for
that raw-only session, even if all 75 raw slots verify. Missing evidence is real.
Nothing here changes installed capture, tasks, Streamlit expectations or holds.

This new package is inactive. It does NOT restore decisions tomorrow, commission
storage, or declare provider bars final. Upload 8 and its two running helpers
remain unchanged. Today's original close, observation and receipt stay immutable.

## Version-aware policy

Keep original exact source bytes plus receipt times. Future decision inputs should
use the latest version actually received by that particular cutoff, including
earlier bars corrected before the cutoff. Bind every decision to an immutable
input projection/hash, policy version, source objects and computation time.
A later revision creates a new version, never changes an old decision input or
earlier outcome. Missing earlier responses are not reconstructed as past evidence.

The new pure module implements a REVIEW-ONLY projection foundation, not signals:

- Hash-bind policy, available source snapshots, cutoff and selected input values.
- Exclude source snapshots received after the cutoff; mark an empty source missing.
- Block candidate inputs on missing completed prefix, stale source, invalid source,
  conflicting identities/versions or times outside the original frozen window.
- Annotate every exact numeric change. There is no epsilon, arbitrary percentage,
  or assumption that a small price change is economically trivial near a threshold.
- Numeric equality (including int/float representation) is the only trivial numeric
  case. Exact raw versions still stay archived; no rounding or destructive dedup.
- Genuine source revisions are distinguished from journal corruption. In the future
  commissioned policy, a valid correction need not halt every subsequent capture;
  whether it changes a signal requires recomputation against that immutable cutoff.
- No signals, orders, journal writes or training admission. All authority and
  decision/training eligibility flags remain false, even for INPUT_CANDIDATE_ONLY.

Before decision commissioning: frozen implementation/environment identity,
durable version-index/journal schema, crash/restart
and unknown-write reconciliation, original-source custody binding, chronological
replay equivalence, source/clock admission, gap/duplicate/revision tests, and explicit
owner freeze of a future recipe. Threshold sensitivity may inform review priority,
but cannot erase a correction. Strategy rules remain parked; no retuning or access
to sealed 2025/2026 history. The current producer's rejection is not loosened.

The [Upstox V3 documentation](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/)
describes intraday candle data. It is not evidence of a guaranteed final close
30 seconds after bar end. Today's observed revision proves at least one correction,
not its frequency, cause, or independently correct price. A longer delay is not
commissioned merely to make a poll pass.

## Session hours are source-specific

[NSE's current CAS page](https://www.nseindia.com/static/products-services/closing-auction-session)
explicitly lists equity derivatives 09:15–15:40, non-CAS cash securities through
15:30, and CAS cash stages through 15:35 with a later post-close session. It lists
NSE/FAOP/74467 of 29 May 2026. This is stronger than relying only on a broker notice.
The direct circular PDF fetch failed in this research run; its effective-date text
was not independently read. Do not present that failed fetch as verified provenance.
The [official Upstox CAS announcement](https://upstox.com/developer/api-documentation/announcements/closing-auction-session/)
states an effective date of 3 August 2026 and F&O segment NORMAL_CLOSE at 15:40.
Thus the current exchange schedule and broker's dated API change are established;
the original exchange circular file still belongs in transition provenance.

The existing recorder is NSE_INDEX|Nifty 50, not an executable derivative feed.
Its 09:15–15:30 / 75-slot window remains a named partial research window; it is NOT
certified complete F&O session coverage. Separate index publication/auction
semantics, derivative contract trading times and broker intraday square-off deadline.
Retain early exits as a conservative research restriction, not proof of the market
close. Before any extension, retain official circular and index-methodology source,
confirm provider timestamps/output, update calendar/config/slot-count/audit together,
and test dated pre/post-change, special/expiry days and broker exit deadlines.
Do not silently relabel old 75-slot sessions as 77-slot sessions or rewrite frozen
research. Tomorrow's fallback window and installed task schedule stay unchanged.
The CAS transition is also a distinct market regime/data-semantics change: confirm
whether an index API reports indicative or published values during those phases,
rather than assume its bars are interchangeable with executable futures prices.
No observations from sealed 2026 history are required for this verification.

## Permanent zero-cost design and order

Use one small operational Supabase database, existing private Drive cold objects,
local exact originals plus derived Parquet, and a verified encrypted external-disk
replica. Parquet is an analysis view, not a replacement for original signed ledger
bytes or exact JSON needed for recovery. Two folders in one account are not
independent account custody. A local file on the producer PC is not off-host backup.

The [official Supabase quota documentation](https://supabase.com/docs/guides/platform/database-size)
states the Free database quota is 500 MB and exceeding it can trigger read-only
mode; database size is distinct from physical disk. Keep the conservative existing
500,000,000-byte planning ceiling and 24,000,000-byte admission reserve unchanged.
394 MB is the owner's older dashboard observation, not a fresh SQL measurement.
At 1.5 MB/day, (500-394-24)/1.5 is about 54.7 trading days to the admission floor,
not guaranteed runway: other writers and bursts shorten it. Alerts and monitoring
cannot wait until the quota is almost exhausted.

1. **Custody and capacity visibility.** Finish signed six-table/full-image binding,
   historical signing-key coverage, encrypted independent restore rehearsal and
   independently delivered quota/missed-run alerts. Owner completes key/disk steps.
2. **Native acceptance and every factory.** Receipt immutability, takeover and
   unknown COMMIT proof, then guarded writes and cold-aware recovery/readers across
   app, collector modes, research, archive, purge and maintenance. No HTTP under SQL
   locks; unresolved outbox/checkpoint dependencies remain hot.
3. **Universe shadow dedup.** Content-address exact raw payloads; preserve snapshot
   headers, member identities and effective/available timestamps. Compare complete
   point-in-time reconstruction before switching writers/readers. No stripping fields.
4. **Bound each source.** Ledger sealing + exact cold lookup/root anchors; session-
   based volume lookbacks; outcome provenance; quote/scanner dependencies. Archive,
   independently restore/verify required generations, then owner-approved pruning.
   If either replica is unavailable/stale, deletion stops. A disconnected disk means
   an owner cadence, not invented unattended daily replication.
5. **Physical transition and steady-state acceptance.** Peak old+new+indexes/TOAST+
   scratch+reserve must fit; credit no future savings. Suitable time partitions need
   PK/FK review; never date-partition a global ledger identity by assumption. One
   reviewed reclaim can follow structural proof, not substitute for it. Observe at
   least a full retention cycle: bounded allocations, archive/catalog growth,
   original-identity restore and alarms actually delivered.
6. **Analysis/ML.** Exact cold/hot research reconstruction and frozen data-quality
   admission before experiments. No automatic rule tuning; no missing fills invented.

Free archive storage is finite. [Google's free allowance](https://support.google.com/googleone/answer/9004014)
is up to 15 GB shared with Gmail and Photos: check actual unused space and licence/
retention permission privately. Set byte budgets and stop-before-full admission for
archive, metadata and request volume as well as the database. Keeping all raw history
forever at ever-increasing ingest cannot be guaranteed with finite free resources;
explicit source selection and licence-approved retention are required.

[R2 pricing](https://developers.cloudflare.com/r2/pricing/) includes Standard free
usage of 10 GB-month, 1 million Class A and 10 million Class B operations; overages
are billable. A free allowance is not a zero-billing guarantee. Therefore do not
commission R2 under a strict zero-cost constraint without a verified hard no-charge
mechanism. No new account, paid database, second Postgres or object service is needed
for this package. Drive plus encrypted independent disk is the initial choice,
subject to custody, available capacity and licence checks; no deletion is authorized.

## Owner and upload steps

Use a fresh exact green-main clone after Upload 8. Copy only these three new paths
from C:\Users\banga\Desktop\kiran_share_market\ to the identical relative paths:

| Source relative path | Clean-clone destination |
|---|---|
| forward_revision_policy.py | forward_revision_policy.py |
| tests/test_forward_revision_policy.py | tests/test_forward_revision_policy.py |
| CAPTURE_AND_ZERO_COST_STORAGE_ORDER_2026-10-12.md | CAPTURE_AND_ZERO_COST_STORAGE_ORDER_2026-10-12.md |

Package check: `git status --short` must list exactly those three paths. No copies
of private state, credentials, unrelated unfinished storage files or installed code.

```powershell
python -m pytest -q tests/test_forward_revision_policy.py tests/test_forward_revision_evidence.py tests/test_forward_revision_quarantine.py --tb=short
python -m mypy --strict --follow-imports=silent forward_revision_policy.py tests/test_forward_revision_policy.py
python -m pyflakes forward_revision_policy.py tests/test_forward_revision_policy.py
python -c "import forward_revision_policy; print('IMPORT_CHECK_PASSED')"
```

Require full quality/resilience/CodeQL checks on the exact PR and merge commit.
This module is not wired to the app or a writer; do not install it as tomorrow's
producer. No hosted SQL, migrations, credentials, release/expectation changes or
task actions are part of the upload. Tomorrow uses Upload 8's explicit owner steps.
Next owner prerequisites: finish encrypted signing-key custody and disk rehearsal;
check Drive unused bytes and retention permission, names/facts only, no secret values.

Validation status is recorded below before handoff. This is an inactive foundation,
not a claim that the pending storage chain or decision producer is commissioned.

## Validation and self-review result

Final public-tree candidate full suite: 3,257 passed, 4 unchanged skipped,
2 subtests passed (1,056.78 seconds). Combined policy/evidence/quarantine focused
suite: 60 passed (75.94 seconds), including 8 new policy tests. Strict mypy,
pyflakes and import check passed for the two new Python files. Existing full-suite
application/import and disposable SQL checks remained green. No real history,
private capture state, credentials or hosted resources were read by these tests.

Self-review corrected the source config field name before testing, deduplicated
version events before chronological comparison so repeated baseline copies cannot
create false reverse revisions, and detached returned candidate values so callers
cannot mutate original evidence by editing a result. Tests verify these boundaries,
hash stability when later receipts arrive, tiny numeric corrections, missing prefix,
staleness, UTC/IST equivalence, duplicate/identity conflicts, invalid source flags,
time/bounds rejection and deterministic input order. No epsilon or live gate change.

The candidate retains the reviewed equity fingerprint
03ad7baa68ebaad1f64b1cd3c356455e1c18cb8f23f027652de303b64b4f8478.
Do not update Streamlit expectations or promote release for this inactive package.
Owner exact-commit PR/main checks are still required; local acceptance is not
permission for installing a new producer, pruning data or commissioning custody.
