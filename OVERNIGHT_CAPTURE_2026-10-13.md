# Overnight capture work: A, B, O, P

This is an additive offline package. Existing Python, manifests, installed capture
folders/state/tasks, credentials and hosted resources were not changed. No private
capture state or network market data was read. Runtime artifacts in tests are
synthetic and use isolated temporary directories. Main owns package manifests.

## Files and contracts

| Item | New file | Result |
| --- | --- | --- |
| A | `overnight_capture_audit.py`, `overnight_capture_planning.py` | Exact-generation audit/readback and logical restoration; date-pinned disabled owner task action/arguments/recurrence |
| B | `overnight_capture_planning.py` | Prospective preregistration and research-review readiness with explicit insufficient-evidence inputs |
| O | `overnight_capture_calendar.py` | Daily NSE source preparation diagnosis: browser/Python distinction, uncommissioned automated route, reviewed explicit owner-file route |
| P | `overnight_capture_calendar.py` | Offline Upstox NSE/NFO timing parser and source-specific close analysis |
| Tests | `tests/test_overnight_capture_audit.py`, `tests/test_overnight_capture_planning.py` | Deterministic synthetic replay and failure coverage |

| Item | Offline completion | Owner-blocked next step |
| --- | --- | --- |
| A | Exact generation audit/readback/restoration and disabled date-pinned task action/arguments/recurrence complete offline | Actual authorized remote reads, signer trust, custody and persistent restoration; owner source preparation, supervised polls and separately authorized scheduling; no installation here |
| B | Preregistration and insufficient-evidence review gate complete offline | Genuine prospective sessions, validated licence/calendar/outcome/reviewer evidence and study design judgment |
| O | Daily NSE source diagnosis and reviewed owner-file preparation handoff complete offline | Licensed zero-cost unattended transport remains BLOCKED on terms and commissioning/network evidence |
| P | NSE/NFO offline parser and 75/77-window distinction complete | Dated source/holiday/special-session evidence, original NSE circular readback and applicable data agreements |

Read before implementation: forward_versioned_producer/capture,
forward_revision_quarantine/evidence/policy, forward_nifty_producer/schedule/archive,
forward_drive_probe, cold_drive_objects, Drive download implementation and task
registration helper. Existing publisher manifests hash **exact bundle bytes** and
pin the recipe hash, data ID and decision count. The new remote adapter uses that
schema, rather than trusting a local saved receipt or a folder-access check.

### A: Audit and logical restoration

`audit_bytes(raw)` calls the existing versioned replay verifier. Counts retain raw
polls versus recorded and missing decisions; blocked input is not a missed decision
silently repaired. Recipe, policy and exact generation hashes are separate.
`audit_lineage(tuple_of_raw_generations)` requires one config/recipe and strictly
growing immutable poll prefixes. Duplicates, rollback and forks fail.

`journal_bytes(path, config, frozen)` never constructs Producer. It requires an
existing absolute non-alias journal, no producer lock or SQLite sidecars, a read-only
connection, query_only, a consistent SELECT transaction, append guards and row hashes.
Owner must pause writers first; a lock absence alone cannot prove they are stopped.
`audit_file` refuses symlink/junction ancestors and bounds reads to 8 MiB. These are
explicit-call adapters, not private-state discovery. They were exercised only on
synthetic files here. Path checks assume a trusted paused owner environment; they
do not defeat a hostile concurrent filesystem replacement.

`audit_remote(injected_download, manifest_id, expected_sha256)` retrieves both
objects and binds their exact hash, recipe and count. It sanitizes transport failures.
There is no credential loader or live transport constructor. Even successful injected
readback leaves remote_custody_verified and independent_custody_verified false: it
does not establish ACLs, retention, continued availability or independent custody.

`audit_signed_remote` additionally verifies an Ed25519 signature using an explicitly
supplied, out-of-band trusted 32-byte public key. The signature covers canonical JSON
in a fixed body schema: manifest/data IDs, manifest and generation byte hashes,
recipe hash, decision count, signed_at/expires_at, ACL-evidence hash and retention-
evidence hash. Verification precedes claim interpretation; both downloaded objects
must match the signed bindings. Expired, future or more-than-24-hour-old reports,
wrong keys, altered signatures, valid signatures on incorrect object/count claims,
and caller-supplied verification flags fail. The output records signature_verified
and signer/report fingerprints as **computed results**, not input assertions.
Signature verification authenticates an attestation, not the truth or durability of
its ACL/retention claims. Remote and independent custody remain false. checked_at is
an explicit trusted-clock input; clock attestation and key distribution are owner work.
No signing credential is read or created. Tests use a fixed synthetic key only.
The implementation follows the [cryptography Ed25519 API](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/).
Installed cryptography 50.0.1 matches `constraints.txt:15`. Requirements files use
that constraints file; `requirements-option-capture.txt` includes
`requirements-archive.txt`, which requires google-auth 2.57.0. Its installed metadata
requires cryptography >=38.0.3 on Python <3.14 (>=41.0.5 on >=3.14), compatible with
50.0.1. Cryptography supports the tested Python 3.13.9. Constraints alone do not
install a dependency, but this capture/archive dependency chain does request it
transitively. Main owns any decision to make the direct dependency explicit and
all packaging/checker/manifest files. No dependency files were edited. This module
imports cryptography only on signed verification; missing dependency fails closed.

`restore_logical(raw, expected_sha256)` returns exact bytes in an immutable private
in-memory object whose representation hides the payload. It does not rebuild an
operational SQLite journal, write any files, resume capture or relabel observations.
Persisting restored data with proven private ACLs is outside this package.

### A continued: Date-pinned owner follow-through

`plan_tasks` receives an owner SID, new namespace, explicit open/close timestamps,
reviewed Python executable/working directory/private-root paths,
caller-supplied existing task names and reviewed calendar/licence/private-path gates.
Collision matching is case-insensitive and suppresses all proposals. Each proposal
is REVIEW_ONLY, disabled, InteractiveToken and LeastPrivilege. No task enumeration,
registration, enablement, deletion, XML installer or stored password path exists.
The existing index policy alone is supported: 09:15–15:30 IST / 75 slots. Paths
must be absolute, without traversal, with Python under the code folder and private
state outside it; filesystem existence/ACL/source identity are not inspected here.
Each action contains its exact executable, working directory and argument tuple
for `forward_versioned_capture.py`, including the explicit session date and mode.
Prepare-policy is 09:00 and requires completed usual owner-file base preparation.
Poll recurrence is date-pinned every five minutes, **09:20:30–15:30:30, 75 slots**.
Audit proposal is **15:40 IST**. The verifier's index close+5 minimum is 15:35;
that is not the owner's scheduled audit time. No catch-up, IgnoreNew, two-minute
execution limit, and disabled proposals remain explicit. Retain all old tasks and
folders and choose a separate name if there is a collision. No executable installer
or registration/replacement/enable/delete action is supplied or performed.

Use the reviewed Upload10 runbook
[VERSIONED_CAPTURE_2026-10-12.md](VERSIONED_CAPTURE_2026-10-12.md), owner installation
and supervision steps 1–6, together with
[FORWARD_DATA_RUNBOOK.md](FORWARD_DATA_RUNBOOK.md). The following are unexecuted,
date-pinned command references for **2026-10-14**, only if reviewed sources, calendar,
licence, paths and pre-open preparation succeed. Variables below are owner-selected
existing private values, never discovered/read by this agent. Run from the separate
reviewed capture code folder, not this development workspace.

```powershell
# Before open: existing reviewed explicit owner-file preparation; never late prepare.
.venv/Scripts/python.exe forward_nifty_schedule.py --root "$forwardPrivateState" --mode prepare --owner-close-file "$forwardOwnerCloseFile" --owner-download-at "$forwardOwnerDownloadAt" --attest-nse-source --confirm-run
# Preview, then owner-confirmed prospective freeze before 09:15.
.venv/Scripts/python.exe forward_versioned_capture.py --root "$forwardPrivateState" --session-date 2026-10-14 --mode prepare-policy
.venv/Scripts/python.exe forward_versioned_capture.py --root "$forwardPrivateState" --session-date 2026-10-14 --mode prepare-policy --confirm-versioned-research
# ONE supervised future slot at 09:20:30, then ONE at 09:25:30 after success.
.venv/Scripts/python.exe forward_versioned_capture.py --root "$forwardPrivateState" --session-date 2026-10-14 --mode poll --confirm-versioned-research
# At/after 15:40: owner audit, not a 15:35 schedule change.
.venv/Scripts/python.exe forward_versioned_capture.py --root "$forwardPrivateState" --session-date 2026-10-14 --mode audit --confirm-versioned-research
```

Before any recurrence, require both future supervised polls to verify local
evidence and the publisher's exact downloaded data/manifest acknowledgements.
Then review the disabled date-pinned action/recurrence above as a separate owner
step, without installing/deleting/replacing old tasks or folders in this assignment.
Do not run raw-only and versioned poll writers together. No same-slot retry or
catch-up; if pre-open commissioning fails, use only the previously reviewed
raw-only procedure for that date. Retain Monday's original journal unchanged.
The local audit reports actual counts and remote_custody_verified false. The
signed remote adapter still needs a real authorized transport, trusted key and
signed attestation supplied by the owner; no real remote check has occurred here.

### B: Prospective research eligibility review

Preregistration contains a shared **policy hash**, registration time, first future
session, minimum session count, hypothesis, outcome definition, missing-data and
split policies. A shared policy hash is deliberate: per-session recipe hashes also
contain session-specific config and freeze time and cannot identify a multi-day study.

The gate requires licence, calendar, independent-review and outcome evidence hash
references; complete distinct prospective audited sessions; and matching policy.
These references and Generation objects are inputs to review, not authenticated
attestations or independently inspected evidence. Missing references, partial capture,
duplicates, wrong policy, pre-study dates and late registration block readiness.
The example minimum of two is a mechanical floor, not a statistical sufficiency claim.
Even RESEARCH_REVIEW_READY requires human evidence review and study-design judgment.
Original training_eligible and approval_authority remain false in every output.
Monday 2026-10-12 is outside a newly registered prospective study and cannot be
retrospectively relabelled. Nothing grants trading, fill or training authority.

### O: Daily NSE source preparation diagnosis

`diagnose_nse_source` accepts only redacted caller-supplied browser/Python transport
observations and produces an offline diagnostic with zero IO. Browser success
with Python connection/read failure is evidence of a client/route difference;
it does not establish CDN blocking, DNS failure, a bad token or a specific proxy/TLS
cause. If both fail, source/connectivity is unavailable with cause unproven. A
successful Python HTTP body is not CSV/date/origin validation or prepared-session
evidence. Unknown input remains blocked; raw exception text is rejected.

The existing source is the calendar-derived exact prior-session index CSV URL
in `nifty_previous_close.source_url`. The previously recorded browser/Python
difference is from the reviewed transport runbooks, not a fresh probe in this
assignment. No market file or private state was opened, no GET was repeated, and
no new transport success is claimed. See
[NSE_CLOSE_TRANSPORT_2026-10-07.md](NSE_CLOSE_TRANSPORT_2026-10-07.md) and
[COLLECTOR_TRIAL_ACCEPTANCE_2026-10-07.md](COLLECTOR_TRIAL_ACCEPTANCE_2026-10-07.md).

The **licensed zero-cost safe unattended daily route is BLOCKED** pending
source-specific permitted-use terms and reviewed network/transport commissioning.
NSE's subscription SFTP product is not a proved free entitlement. Public download
availability is not permission for this project's retention/research/ML purposes.
No anti-bot circumvention: no browser-cookie/fingerprint impersonation, IP rotation,
proxy/security/TLS weakening, retry loop, deadline expansion or alternative-price
substitution. Terms and ordinary authorized connectivity must resolve the route.

The existing **explicit reviewed owner-file mode remains the preparation route**,
not an automatic fallback. `nse_owner_close.py` retains original bounded CSV bytes,
exact prior-session date, NIFTY 50 price-index close and actual owner-observed
download/read/freeze times before open. Its source authenticity stays
OWNER_ATTESTED_NOT_INDEPENDENTLY_VERIFIED; publication time remains unknown.
Keep the reviewed `--owner-close-file`, `--owner-download-at`, `--attest-nse-source`
procedure above. No guessed close, file-mtime substitution or retroactive preparation.

### P: Official source findings and limitations

[Current Upstox CAS documentation](https://upstox.com/developer/api-documentation/announcements/closing-auction-session/)
reports cash NORMAL_CLOSE at 15:30 and equity derivatives at **15:40 IST**. Eligible
cash equities end continuous trading at approximately 15:15, with separate auction
phases. This does not make a cash-index candle interchangeable with a futures candle.

[NSE's current CAS page](https://www.nseindia.com/static/products-services/closing-auction-session)
was read directly in this correction: it establishes the **09:15–15:40 derivatives**
window, non-CAS cash continuous trading until 15:30, CAS matching/confirmation
until 15:35 and a separate post-close session. These exchange phases differ from
the broker's NORMAL_CLOSE field. CAS capture remains blocked for separate policy;
the analyzer's CAS diagnostic now names the exchange's 15:35 confirmation phase.
[Upstox's platform announcement](https://community.upstox.com/t/closing-auction-session-cas-what-api-and-algo-developers-need-to-know/16893)
supplies the August 3, 2026 effective date. Original circular transition provenance
remains an external blocker; the current NSE schedule itself is directly verified.

[NSE FAOP74791](https://nsearchives.nseindia.com/content/circulars/FAOP74791.pdf)
independently references FAOP74467 dated May 29, 2026 as the CAS-related derivatives
modalities circular, but is a **mock-session** notice, not proof of regular hours.
The [original FAOP74467 PDF](https://nsearchives.nseindia.com/content/circulars/FAOP74467.pdf)
was inaccessible during this research; its full primary contents remain a verification
blocker. No mirror was used to claim NSE-specific confirmation of its effective date.

[Upstox date-specific timing schema](https://upstox.com/developer/api-documentation/get-market-timings/)
uses NSE and NFO as distinct exchange records with epoch-millisecond start/end times.
The offline parser accepts exactly one matching record; empty/ambiguous records or
wrong dates fail. It never turns missing response data into a confirmed holiday.

[Upstox historical-candle V3 schema](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/)
identifies the candle timestamp as its start and supplies OHLC, volume and OI fields.
Its published availability/retrieval limits do not establish provider finality or
prove which version was available at a historical decision time. The adapters retain
actual received versions and replay their original as-of decisions.

A reviewed regular 09:15–15:30 cash-index window has 75 five-minute intervals; a
09:15–15:40 derivatives window has 77. These are window arithmetic, not assertions
about daily provider completeness or finality. Dated reviewed evidence is mandatory;
special sessions and CAS equities are blocked for separate policy review. Existing
producer counts, calendar and close settings remain unchanged at 75 and 15:30.
`CloseAnalysis.verification_not_before` names only the close+5 replay minimum;
`owner_index_audit_at` is explicitly 15:40 for the index and absent for derivatives.
No derivative owner schedule or 77-slot producer is installed or authorized.

[NSE EOD transport specification v1.8, December 2020](https://archives.nseindia.com/content/press/EOD_CM_n_FAO.pdf)
describes a subscription SFTP service with supplied authentication and daily CM/F&O
files, including closing indices. Its approximate delivery times are historical
product details, not a current SLA or licence to fetch, redistribute or upload files.

[NSE data sharing and usage policy](https://www.nseindia.com/static/market-data/nse-data-policy)
makes permitted use, transmission, handling and dissemination agreement-specific;
redistribution needs agreement permission and market-data access confers no ownership.
Research access has documented conditions. Public daily reports, subscription EOD,
broker candles and index source files need separate provenance/licence review.
No SFTP/API connection, file download, credential creation or licence acceptance occurred.

## Validation and remaining boundaries

Pyflakes: clean on the five new Python files. Strict mypy: clean on those files using
`--strict --follow-imports=skip`; existing imported modules were not type-checked or
modified. The complete focused run passed **28 tests in 72.66 seconds**, including
lineage, Upstox segment parsing and signed-custody verification. Bytecode and
pytest cache writes are disabled. Windows sandbox temporary-directory creation
failed before audit fixtures ran; the focused synthetic test process was rerun with
ordinary writable temporary-directory access.
After separating those two timing fields, all eight planning/calendar tests passed
again in 1.99 seconds; pyflakes and strict mypy remained clean on all five files.

Owner-side blockers remain: dated source calendars, original NSE circular readback,
actual licence permissions, genuine outcome and prospective multi-session evidence,
and any private ACL/remote retention or independent custody verification. This package
does not claim those checks have happened. Git status is unavailable because this
workspace is not a Git repository. No package manifest changes are included.

Reproduce with Python module invocations on precisely the five Python files above:
`pyflakes`, `mypy --strict --follow-imports=skip --cache-dir <isolated-temp-cache>`,
and `pytest -q -p no:cacheprovider --basetemp <new-isolated-temp-directory>` on the
two new test files. Set PYTHONDONTWRITEBYTECODE=1. Temporary fixtures must be writable;
choose a new path, because pytest may remove an existing basetemp. Main's separately
reported operations and native PostgreSQL tests were not rerun or counted in these
28 results. A read-only collection found 25 history tests and 81 combined
history/operations tests; collection is not a passing test run.

## Read-only adversarial handoff to main: operations/history

Status of the original findings below: **RESOLVED by main**, including the
runtime-type probes. Main reported 94 regressions, then 96 after further tests;
the independent re-review also passed all 96 operations/history tests, together
with 16 packaging-helper and 28 capture tests (140 total, 71.56 seconds).
These fixes do not commission active use. The original reproduction table is
retained as historical review evidence, not a list of still-open defects.

Main's operations/history files were inspected but never edited. The cases below
were reproduced using synthetic bytes, fake transports/authentication callbacks
and a new temporary SQLite fixture only. No real alert, credential, permission,
private journal, hosted database or market transport was used. These are separate
from main's reported native PostgreSQL 6 guard / 8 ledger / 9 operational cases.

| Priority / location | Concrete reproduction | Observed result / requested fix |
| --- | --- | --- |
| P1 `overnight_operations_alerts.py:191` | Persist a valid synthetic alert; send with a fake accepting sender. Leave its PENDING, INTENT, ACCEPTED events intact, but simulate inconsistent recovery with `UPDATE alerts SET state='PENDING'`. Reopen and call send_once again. | Fake sender called twice for the same ID; state reports PENDING with three immutable events before the second send. Validate event transitions and reconcile state against history inside the claim transaction; conflict must block sending. Not a claim of protection from a malicious database administrator. |
| P2 `overnight_operations_alerts.py:108` | On a fresh synthetic journal, execute `DROP TRIGGER immutable_event_delete`, close the connection, then reopen AlertJournal. | Reopen succeeds. Validate actual schema/guard definitions, not only metadata version, before operations. |
| P2 `overnight_operations_alerts.py:280` | Fake HTTP 200 reply with ok=true, positive integer message_id, correct chat ID, current integer date, but `text='old unrelated notice'`. | TelegramSender returns Acceptance with the requested alert ID even though the returned message is unrelated. Bind reply text to the exact constant notice and alert ID; mismatch stays unverified/UNKNOWN. Acceptance still does not prove owner receipt. |
| P2 `overnight_operations_alerts.py:48` | Canonical JSON with version storage-alert-envelope-v1, aware evaluated_at, `monitor_id:null`, `schedule_sha256:'invalid'`, report containing only `alert_required:true, approval_authority:true`, and an unexpected field. Set Alert ID to SHA256 of those bytes. | validate_alert and a fake accepting delivery.attempt both succeed. Require the complete exact envelope/report schema, IDs and reserved false flags before journal/transport admission. Output authority flags remained false; this is malformed-envelope acceptance, not an observed grant of trading authority. |
| P2 `overnight_history_admission.py:97` | Admit `Date,Close\n2024-01-01,100\n` as nse_index_daily, session 2024-01-01, available_at 2023-01-01 UTC, received_at 2024-01-02 UTC, with otherwise matching fixture-authenticated permission and Date/Close schema. | Admission stores impossible EOD availability a year before its session. Add source-specific temporal plausibility or mark availability unverified pending reconciliation; contract-master pre-open timing must not receive a blanket EOD rule. Row-date and authenticity flags correctly stay false. |
| P2 `overnight_history_admission.py:112` | Add `storage_allowed:false` and `revoked:true` to an otherwise valid canonical, fixture-authenticated v1 permission record. | One row admitted; contradictory signed terms ignored. Reject unsupported keys for fixed v1, or implement explicit denial/revocation semantics. A synthetic authentication callback is not a commissioned licence verifier. |

Controls: duplicate-key and noncanonical alert JSON were rejected with
ALERT_ENVELOPE_INVALID; duplicate-key/noncanonical permission JSON was rejected
with HISTORY_USAGE_PERMISSION_UNVERIFIED. Missing permission was rejected with
HISTORY_USAGE_PERMISSION_MISSING. Those controls are not bug findings.
The report records snapshot locations; main may fix/reflow code while packaging.
Main owns fixes, their regression tests and the shared upload checker/manifest.

Additional runtime-type probes reproduced on the same synthetic history fixture:
`Permission(bytearray(valid_record), bytearray(valid_signature))` admitted one row;
`zipped='false'` with a valid ZIP admitted one row; `columns=([], 'Close')` leaked
`TypeError: unhashable type: 'list'` rather than a redacted HistoryError. Require
exact immutable bytes for permission record/signature, exact bool for zipped, and
validate each column's type before constructing a set. Authentication callbacks
should never receive mutable permission bytes. These probes did not alter any file.

Read-bound inspection found an 8 MiB input limit, one-member ZIP checks, expansion
ratio and bounded MAX_ORIGINAL_BYTES+1 decompression read, plus row/cell limits.
Admission takes already supplied bytes; it is not a bounded disk-file reader.
The packaging caller must bound disk reads before allocating/feeding those bytes.
No unbounded archive read was found in the inspected function.

Uncertain-commit review: claim commit failure raises CLAIM_COMMIT_UNKNOWN_DO_NOT_SEND
before transport; completion failure raises RESULT_COMMIT_UNKNOWN_DO_NOT_RESEND.
Lost replies become UNKNOWN; an intact INTENT prevents retry. The inspected test
suite covers lost reply and an INTENT restart, but no injected commit-then-raise
case was found. Add both claim and completion commit-then-raise regression cases;
this is a coverage request, not a reproduced commit-ordering defect. The reproduced
state/event disagreement above remains the recovery integrity defect.

### Independent re-review: four findings subsequently fixed

The previously requested claim/completion commit-then-raise probes were now run
on fresh synthetic journals. Claim reply loss made zero sender calls, retained
INTENT and raised ALERT_CLAIM_COMMIT_UNKNOWN_DO_NOT_SEND. Completion reply loss
made one sender call, retained ACCEPTED and raised
ALERT_RESULT_COMMIT_UNKNOWN_DO_NOT_RESEND. Both are safe reconciliation outcomes.
The original state/event disagreement and guard/alert/permission fixes are present.

| Priority / location | Reproduction and observed result | Needed correction |
| --- | --- | --- |
| P1 `overnight_upload_check.py:117` | In a fresh disposable Git repository with an empty base, retain manifest-approved `example.py` bytes in the working tree, but stage a different blob using `git hash-object -w --stdin` and `git update-index --add --cacheinfo`. The checker returned exit 0 / UPLOAD_FILES_VERIFIED_REQUIRES_TESTS_AND_CI although `git show :example.py` contained unreviewed code. | Bind the checked candidate to its index/tree bytes or reject all staged-versus-working-tree differences; path names alone do not bind the next commit's bytes. No user repository was touched. |
| P2 `overnight_operations_alerts.py:259` | Alert evaluation is NOW, persist at NOW+30 seconds, then send_once with clock NOW and a fake accepting sender. One send occurred; PENDING@NOW+30, INTENT@NOW, ACCEPTED@NOW were committed; only final state read raised HISTORY_CONFLICT_NO_RESEND. | Validate newly appended transition timestamps against the prior event before claim commit/transport, and validate completion before commit. A backward clock must not send and poison otherwise valid history. |
| P2 `overnight_research_trials.py:56` | Replace both trial guard definitions with same-name BEFORE UPDATE/DELETE triggers containing `BEGIN SELECT 1; END`. Registry reopened with one STARTED trial; DELETE FROM events then succeeded and reopened.events() became empty. | Audit actual guard/table definitions before append/read, not only trigger names; detect this corrupted schema before losing trials. This is corruption detection, not protection against a malicious administrator rewriting all evidence. |
| P2 `overnight_research_evidence.py:30` | Replace licensing payload's `speculative_use_permitted:true` with duplicate keys `speculative_use_permitted:false,speculative_use_permitted:true`, hash those exact bytes, and pass it with otherwise complete synthetic reports. | Gate returned REPORTS_COMPLETE_PENDING_INDEPENDENT_REVIEW. Reject duplicate keys recursively before interpreting rights/report claims; hashes authenticate supplied bytes, not an unambiguous JSON interpretation. Paper/training/authority flags still remained false. |

The shared helper's actual name is `overnight_upload_check.py`; no
`overnight_capture_upload_check.py` exists at this review snapshot. Both names
remain main-owned, and neither was edited here. No package manifest was changed.

Final capture file names remain stable: three modules, two tests and this document.
The aggregate-typing compatibility fix imports ROOT directly from its defining
`forward_nifty_producer` module and removes three redundant typed-bytes casts.
Pyflakes and strict mypy with **--follow-imports=silent**, not skip, pass on the
five capture Python files. The independent 140-test run includes all 28 capture
tests after these fixes. Main retains responsibility for the aggregate 45-file run.

Main resolved the four re-review findings with regression tests: the upload check
rejects index/worktree disagreement; alert claims and completions validate causal
transition clocks before committing or sending; the trial journal checks actual
trigger SQL definitions; and licensing/report JSON rejects duplicate keys
recursively. Failed preparation remains in the trial denominator. Final counts,
strict typing, lint and clean-public regression are recorded in the programme ledger.
