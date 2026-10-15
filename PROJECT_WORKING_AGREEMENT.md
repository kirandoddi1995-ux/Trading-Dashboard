# Project working agreement — 15 October 2026

The ambition is a trusted daily dataset with one understandable daily go/no-go,
followed by independent encrypted custody and demonstrated restore, a frozen
prospective paper study, and only then ML. Success means reliable evidence and
honest decisions; neither an attractive backtest nor autonomous trading is an
acceptance shortcut. All work must have zero incremental monetary cost.

## Persistent front door and bounded roles

`project_conductor.py` holds immutable project memory and deterministic routing.
It imports the existing `programme_agent_team.py` contracts. It is contract/tooling,
not an active LLM, installed custom-agent configuration, scheduler or API client.
It never invokes a role, reads a report path, accesses credentials or creates a
network connection. Prompts are not a sandbox. Actual tools and host permissions
must independently enforce the same limits. No API key or new account is needed.

The conductor holds the ambition, rules and first unproved milestone stage.
The builder implements one bounded offline change and failure tests. A separate
reviewer challenges that exact candidate without editing it. The Windows/Linux
verifier records reproducible commands, environments, source pins, collection
identities, counts and explicit skips. Morning ops interprets supplied dated
redacted readiness reports; the evidence auditor checks supplied summaries for
gaps, forks and custody scope; the post-session reporter separates recorded,
raw-only and missing slots, and distinguishes integrity, readback, custody and
restore. These runtime roles only monitor and report supplied redacted evidence.
They cannot operate capture, repair state, read private data, notify externally,
place orders, approve trades or activate models.

## Mandatory milestone handoff

For every milestone, the order is technology radar → builder → independent
reviewer → Windows verifier → Linux verifier → owner commissioning. Scouting
precedes implementation: research existing primary best practice, record each
choice as adopt, adapt, defer or reject, explain why, and establish zero incremental
cost. Unknown costs block adoption. A fresh milestone needs fresh scouting;
this dated radar is a starting point, not perpetual approval.

`plan_milestone(Candidate(...), receipts)` returns the next stage and role, or a
blocking reason. No receipts means radar pending. `delegate(Role.MORNING)` (or
AUDITOR/POSTSESSION) returns the existing immutable role contract.
`delegation_allowed` is only a planning predicate; runtime reporting also needs
`supplied_redacted=True`. That boolean cannot perform or prove redaction.

Each receipt binds milestone ID, exact public source revision, frozen candidate
closure SHA-256, canonical principal ID and redacted evidence SHA-256. Receipts
must be a contiguous ordered tuple. Source or candidate changes invalidate the
chain: rebuild it from radar, never rewrite old proof identities. The builder and
reviewer must differ; verifiers must differ from both; the named owner must differ
from every prior actor. One independent verifier may test both platforms. Persona
names do not establish independent people or independent review; the caller must
bind canonical principal IDs to real identities and prevent alias impersonation.

Platform proof requires hosted Windows and hosted Ubuntu evidence for that exact
candidate and source pin, matching canonical collected-test IDs and counts,
commands and explicit Python/dependency environment versions. Zero tests, failures,
missing counts, unexplained skips and a local Debian pass do not meet that gate.
Documented skips remain skips; the owner must assess them in the commissioning
evidence, not count them as passes. A local Windows pass is useful local evidence
but does not claim hosted CI. No new hosted workflow or dispatch is authorized here.

Receipt fields are supplied attestations. The code validates structure, bindings,
ordering and separation, not report authenticity, primary-source authorship,
identity, execution, signatures or delivery. `verified=True` must come from actual
evidence reviewed outside this module; owner-reported and unknown are distinct.
`CONTRACT_COMPLETE` describes this supplied proof chain only. Every result has
`execution_authority=False`; completion grants no live action or deployment right.
No real commissioning or current platform acceptance is asserted by synthetic tests.

## Daily evidence and owner authority

One daily go/no-go must bind session date/calendar, deadline, exact source and
recipe pins, task binding, fresh independent clock measurements and notification
acceptance. Any missing/stale requirement means NO_GO. Preserve partial evidence
and choose a later eligible session. Never catch up missed observations, retry
the same capture slot, rewrite timestamps, loosen a clock gate or remove a source
pin to get green. A queue/launch receipt is not human delivery proof. Counts are
recorded, raw-only and missing separately; missing proofs always remain missing.

No credential reads, real capture access, trading, real training or access to
sealed historical 2025/2026 data is delegated. Public and synthetic fixtures or
explicitly supplied redacted reports are the only agent inputs. No permissions
changes or hosted writes without explicit owner authorization; even owner consent
does not silently expand these contracts. A separately scoped reviewed procedure
and external permissions would be needed for any future owner operation.

Custody requires exact object-set identities, independent encrypted replication,
key availability through an owner-controlled procedure, and a demonstrated restore
with recorded scope. A local hash or remote readback is not independent custody
or restore. No retention/delete/factory switch before the applicable real proofs.
Preservation and restore procedures remain owner operations.

The prospective paper study freezes its registration, cohort, schema, features,
labels, costs, exclusions, baseline, evaluation and stopping rules before results.
Index observations do not invent executable derivative prices, fills, depth,
margin or labels. ML follows sufficient eligible prospective evidence, licences,
restorable custody and the frozen study gates. Use chronological validation,
training-only preprocessing and overlap-aware exclusions; an engine is not a
substitute for executable data or independent validation.

## Current boundary and next milestone

Adopt a lightweight native PowerShell owner guide plus deterministic Python
policy checks for the next guided daily readiness milestone. The main agent owns
the separate Friday guided launcher. This sidecar neither implements nor installs
it. No general workflow service, package installation, account creation, paid
notification plan, model download or local/hosted LLM setup is recommended now.

The existing twenty-file continuity package remains frozen as listed in
`CONTINUITY_UPLOAD_2026-10-15.md`. Do not add these four files to that manifest,
recompute its pins, modify its checkers or sweep held workspace changes. This
agreement supplements continuity; it does not override its release holds.

The only sidecar paths are `project_conductor.py`,
`tests/test_project_conductor.py`, `PROJECT_WORKING_AGREEMENT.md` and
`TECHNOLOGY_RADAR_2026-10-15.md`. Focused verification uses the existing Python
environment with bytecode and pytest cache writes disabled. Report actual local
test results and pending platform proofs without inventing acceptance.
