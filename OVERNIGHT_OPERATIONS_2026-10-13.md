# Durable alerts and owner custody prerequisites — inactive

Nothing here is installed in capture, imported by the live app or scheduled.
No real database connection, Drive quota request, alert or backup was performed.
The programme remains zero-cost. Upload is not commissioning.

## What is executable offline now

`overnight_operations_inputs.measure_capacity` accepts an explicit DB-API adapter,
opens one short READ ONLY transaction, measures the sum across all databases and
rolls it back. It rejects stale/future/invalid measurements and redacts exceptions.
It does not read a connection string or claim server identity was authenticated.

`overnight_operations_watch.cycle` joins that measurement to the existing explicit
session/deadline inventory and capacity watch. Missing measurements generate an
UNKNOWN warning, not a green badge. Default preview invokes no callbacks. Execution
without delivery commissioning persists the alert but never sends it.

`overnight_operations_alerts.AlertJournal` persists the exact envelope before its
one-attempt claim. INTENT is durable before transport. Concurrent callers cannot
send twice. Restart, lost response or unknown commit requires read-only
reconciliation; no automatic retry. Immutable event and envelope records preserve
the history. Keep this journal in a private directory outside the repository.

`TelegramSender` is an optional fixed-host HTTPS adapter, supplied credentials by
the future commissioned caller. It has no automatic credential lookup, redirects
or retries; it sends a constant health notice and alert ID, not prices or private
provider payloads. Paid broadcast is explicitly disabled. It validates the reply
chat, message and time, but acceptance is **not** proof you received it. Telegram's
ordinary bot messages are free, subject to rate limits; paid broadcast is a
separate opt-in mechanism. [Official Bot FAQ](https://core.telegram.org/bots/faq)

## Minimum owner prerequisites (do these separately from Tuesday capture)

1. In the password manager, save the current ledger signing key in an encrypted
   private note; do not paste it into this chat, a command, repository or screenshot.
   Save its key ID and applicable release/date alongside it. Search previous note
   versions for original IDs required by old event signatures. A current key
   cannot replace a missing historical key. No key material was inspected here.
2. Keep an independently retained signed checkpoint/contract inventory, separate
   from the objects being verified. Do not derive the trusted expected root from
   an untrusted downloaded copy; matching a copy to itself proves nothing.
3. Install 7-Zip from its official site if needed. Start with a dummy, non-sensitive
   folder on the empty external disk: Add to archive → 7z → AES-256 → strong private
   password → Encrypt file names. Close it; open it again with the password; extract
   to a new dummy directory and compare the exact files. Do not put the password
   beside the archive. This run did not operate the disk or test encryption.
   [7z format and encryption](https://www.7-zip.org/7z.html)
4. After that rehearsal, use the already reviewed full-image/six-table custody
   export and restore tooling on one new private generation. Retain exact image,
   signed bundle, six-table witness and independently trusted checkpoints. Encrypt
   the independent copy, disconnect the disk, reconnect for a restore rehearsal
   into NEW private targets, then retain the signed result externally. Never
   restore over the running capture or delete its source.
5. Check Google account storage, including Gmail/Photos and trash; report only
   used/limit bytes and measurement time. `drive_quota` validates the official
   `about.storageQuota` response if a reviewed adapter is later supplied. A missing
   limit remains UNKNOWN, not an assumed unlimited/15-GB allowance. Storage is
   shared across services, and trash can still consume quota. Record a retention
   policy that protects original generations/checkpoints until verified replacement
   custody and restore exist. [Drive quota schema](https://developers.google.com/workspace/drive/api/reference/rest/v3/about),
   [Google storage guidance](https://support.google.com/drive/answer/6374270?hl=en)

These are factual prerequisites, not flags to tick to bypass a safeguard.
`prerequisite_blockers` reports inventory gaps but never issues deletion authority.

## Capacity and independent delivery commissioning — still held

Use fresh SQL measurements, not a cached dashboard. Supabase distinguishes
database allocation from physical disk/WAL; ordinary VACUUM can leave reusable
space allocated, while rewriting has locking and peak-space costs. Do not credit
anticipated deduplication or reclamation in admission. Keep the existing 500M-byte
planning quota and 24M-byte admission floor; obtain physical free disk separately
before a rewrite. [Supabase database/disk sizing](https://supabase.com/docs/guides/platform/database-size)

A real rollout needs an authenticated verify-full, restricted read-only SQL
connection, a reviewed complete writer/deadline inventory, measured growth bounds,
a private durable journal, and an explicitly commissioned host and destination.
The watcher must not rely solely on the producer it watches. A PC watcher cannot
tell you the PC is off; GitHub schedules can be delayed. A genuinely independent
dead-man/heartbeat receiver plus owner-visible test is required before claiming
independent alert coverage. No new account, secret or schedule is configured here.

For first commissioning: test one synthetic notice, confirm it arrived, inject a
missing-run/measurement failure, confirm an UNKNOWN notice, then test the watcher
not running at all. Retain dated redacted receipts. Do not resend an uncertain
alert ID: reconcile its journal/provider record first. All global enforcement,
owner-delivery and custody flags remain false until their own evidence exists.

## Free historical source research and admission

NSE's daily F&O reports include UDiFF bhavcopies, contract and settlement/risk
files; older bhavcopy formats changed in July 2024. These can help reconcile daily
prices/contracts, but are not intraday bid/ask history or fill evidence.
[Official derivatives reports](https://www.nseindia.com/all-reports-derivatives)

Public availability is not a blanket licence. NSE's research route restricts
purpose and eligible researchers, and the broader policy governs handling and
redistribution. Obtain source-specific permission for private trading/ML and
archival copies; do not assume the academic route applies to this project. This
is a terms question for NSE/broker and, if needed, professional advice, not a legal
conclusion about the owner's actual rights.
[NSE disclaimer](https://www.nseindia.com/static/nse-disclaimer),
[NSE data policy](https://www.nseindia.com/static/market-data/nse-data-policy),
[SEBI research-data circular](https://www.sebi.gov.in/legal/circulars/dec-2024/policy-for-sharing-data-for-the-purpose-of-research-analysis_90088.html)

Upstox documents 5-minute expired-contract candles but also a Plus-only error.
Existing account entitlement and permission are unverified; buying a plan is not
a zero-cost solution. OHLC alone still cannot supply historical executable spread,
liquidity or margin. [Expired historical API](https://upstox.com/developer/api-documentation/get-expired-historical-candle-data/)

`overnight_history_admission.admit_csv` is a tested **offline** admission adapter:
externally authenticated permission, zero-fee and byte/date/schema scope, bounded
single-file ZIP parsing, exact originals and separate provenance. Development
scope is 2022–2024 only. It downloads nothing, fabricates no source authenticity,
and leaves row-date reconciliation/training/fill eligibility false. A future
source-specific parser must reconcile the dates/contracts and retain official
schema versions before dataset use. No current/private historical data was opened.

## Verification and remaining boundary

Initial operations tests: 54 passed. Historical admission tests: 25 passed.
Strict typing and lint passed on these modules/tests; final combined regression
is recorded in the programme handoff. No native/hosted acceptance or actual alert
delivery is inferred from these deterministic fake adapters.

The next owner-facing release remains inactive: custody keys/disk/quota evidence,
independent host/secret provisioning, and the first supervised real readback/notice
are external blockers. Source rights, dated execution inputs and enough genuinely
independent prospective sessions block economic/ML claims.
# Adversarial verification update

The second review reproduced malformed envelopes/permissions, a reset state that
contradicted immutable delivery history, a removed SQLite guard, and a Telegram
response referring to unrelated text. All were fixed before packaging. Claims now
reconcile the complete event sequence within the claim transaction; reopened
journals verify actual trigger definitions; returned Telegram text must match the
exact alert notice. Permission v1 has exact keys and explicit storage permission
and non-revocation. Mutable credential-like permission bytes, nonboolean ZIP flags
and invalid schema field types fail with redacted errors. Availability cannot
precede the supplied session; source-specific publication reconciliation remains
unverified rather than inferred. Tests cover accepted SQLite COMMIT followed by a
lost reply both before sending and after provider acceptance: no automatic resend.

The operations/history aggregate passed **96 tests** after these fixes; strict
typing passed on all eight Python source/test files. This supersedes earlier
intermediate counts above. No provider send or hosted write was performed.

Final manual review added explicit transition-clock validation and idempotent
watch-cycle recovery: an already attempted alert reports its existing ACCEPTED,
INTENT or UNKNOWN state without a resend. Connection/sender attempt counts are
measured at the callback boundary, not assumed. The current operations/history
group has 98 tests; final full-candidate checks are in the programme ledger.

