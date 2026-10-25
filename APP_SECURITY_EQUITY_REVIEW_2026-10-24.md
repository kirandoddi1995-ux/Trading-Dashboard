# App security profile and equity replay foundation

Review base: 563665a32e5454633b0c27256072a7249503c520.
No installed runtime, task, database, release switch or expectation changes.

## Changes

The app profile now selects Streamlit1.66.1/Pillow13.0.0, certifi2026.10.23 and
the consistent OpenTelemetry1.45.1/0.66b1 family. Previously unconstrained runtime
dependencies selected by the new clean resolution are frozen explicitly. The
app-repository future-operations certifi source/profile pins move together.
They are NOT the separately installed capture repository or its frozen capsule.

The long-only OHLC scenario engine advances to event-driven-bracket-v2: an adverse
gap exits at the opening price, not an unavailable stop; an opening price above
a target gets only the target price before subsequent intrabar movement; a bar
opening inside the bracket retains conservative stop-first ambiguity handling.
Scenario fill_evidence is explicitly false. This is not a new trading rule,
an exchange-fill claim, an executable slippage model or a calibrated probability.

New tests verify the full selected dependency family, generated PNG round-trip,
actual Streamlit chart/image rendering and gap scenarios. Streamlit's newer test
runner needs asyncio loops. The offline boot harness preallocates exactly two
trusted framework loops before the application boundary (Windows wakeup pipes
use local socketpairs), latches exhaustion, restores the factory and closes unused
loops on failure. Connect/DNS/sendto denial during app execution is unchanged;
no blanket localhost permission or skipped boot test. Negative pool regression
catches an exhausted factory even when caller code catches its first exception.

## Acceptance remains separate

25 October follow-up: the first complete Windows summary was 13 failed,
7407 passed, 21 skipped (summary-only, without a retained raw log/JUnit). Eleven
were historical constraints pins; two were the cache lock protocol. This was NOT
acceptance. The profiling observer now forwards both acquire/release and context
manager protocols to the original lock, retaining miss serialization, cache hits,
clear(), return values and exceptions. New protocol and real contention tests
exercise those invariants. No cache policy or signal formula is changed.

Original historical manifests and upload admissions remain byte-for-byte frozen.
Only their current-tree regression checks enroll explicit successors. The fixed
record APP_SECURITY_SOURCE_TRANSITIONS.json embeds actual predecessor Git blob
bytes from the review base and raw successor hashes for exactly twelve paths:
constraints and the eleven changed regression modules. The regression-only helper
pins that record and rejects tampering or unknown predecessors; it grants no old
uploader permission to accept a new environment. Historical digest normalization
and raw current pins are kept distinct. No blanket pin fallback or skip is added.

Settings now displays local Git HEAD and an app-file SHA-256, with explicit
UNKNOWN when metadata is absent and NOT_ATTESTED integrity. This is useful build
visibility, not proof of clean source, hosting branch or deployment approval.

Synthetic replay example (one unit, entry 100, stop 95, target 110, round-trip
scenario cost 30 bps): the next bar opens at 90 and ranges 89–96. Previously it
exited at 95 (-5.3% net); now it exits at 90 (-10.3% net). The old stop price was
unavailable at the opening gap. If a bar opens inside the bracket and touches both
levels, stop-first remains unchanged. Opening above target is capped at target,
not credited with an improved fill. No claim of real exchange execution follows.

The replacement complete run must retain its raw log, JUnit, and matching start/end
source inventories. Any source change during that run invalidates the acceptance
receipt. Focused passing tests alone do not clear the complete-suite gate.

The exact current-main source was cloned for this review, not copied from a
mixed working directory. Full-requirements audits of app and forward-operations
profiles passed locally. A new disposable environment installed successfully and
pip check passed; selected native PNG/chart/replay tests and configured strict
typing were exercised. Private verification details and final counts live in the
owner's review record, not a claim of already-green hosted CI.

Before merge: exact candidate focused and complete suites, declared skip/failure
disposition, mandatory audit and exact-final-SHA Quality/Resilience/CodeQL including
code-scanning results. Native Linux and supported Python coverage still need their
actual evidence. A local Windows pass is not that evidence. No advisory ignore,
constraint relaxation or permission change is included. Do not close issue58
based only on this document or a dependency metadata result.

The repository's old tracked SHA256_MANIFEST is a historical release snapshot,
not a fresh assertion of this working tree. The release builder must generate
and verify a complete new artifact manifest from the reviewed closure. Never
patch a few digests into that old snapshot and call it current acceptance.
Owner separately authorises any deployment/expectation updates; release hold
stays in place. No installed environment is repaired in place by this PR.

## Next visible delivery, not claimed here

Cash-equity EOD development is the first study segment because it avoids derivative
DDL/roll/margin prerequisites. Build a fixed-input2022–2024 report independent of
today's picks, using a frozen rule/horizon and explicit data/universe/action/cost
assumptions. Existing recent400-day sanity tests are not that report. Prior use of
those years means retrospective development, not newly untouched test evidence.
Sealed historical periods stay sealed. This PR does not fit or promote a model,
download historical market data or claim a performance improvement.
