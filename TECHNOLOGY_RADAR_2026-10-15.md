# Zero-cost technology radar — 15 October 2026

Scope: choices for the next milestone and later research gates. Primary publisher
documentation below was opened through research tools on 15 October 2026. These
are living documentation URLs, not immutable version pins or proof of installed
versions. Recheck and record exact versions/revisions at the relevant milestone.
No installs, accounts, subscriptions, notifications or hosted writes are proposed
for execution now. Zero incremental monetary cost is a project constraint, not a
claim that every hosted service or piece of hardware is free forever.

## Next milestone: adopt native guidance; adapt deterministic checks

ADOPT the existing native PowerShell owner workflow and deterministic Python
contracts for guided daily readiness. ADAPT scheduler best practice to our strict
clock/deadline and no-catch-up/no-same-slot-retry rules. Microsoft documents that
StartWhenAvailable permits execution after the scheduled time; its settings API
also exposes restart and multiple-instance controls. Our policy requires explicit
bounded owner review of those settings, not enabling late execution or retries.
This is a design choice, not a claim about the installed tasks. Source:
[Microsoft ScheduledTasks settings](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset?view=windowsserver2025-ps).

DEFER a general workflow service. Current work needs a small auditable readiness
sequence and evidence handoffs. Another service would introduce state, deployment,
credentials and operational obligations without resolving absent clock, delivery
or custody proofs. Reconsider only when measured multi-host coordination needs
exceed the native approach and a bounded zero-cost alternative is demonstrated.
REJECT automatic late capture, same-slot retry and self-approval, regardless of
which scheduler or agent proposes them. The separate Friday launcher belongs to
the main agent and remains subject to owner commissioning.

## Analytical storage: adapt the pattern; defer new dependencies

ADAPT the separation of immutable analytical files from query/processing tools.
Apache Parquet is a column-oriented format with compression/encoding support;
DuckDB documents direct Parquet reads/writes and projection/filter pushdown.
Future candidate: Parquet for a frozen derived research export, DuckDB for bounded
local SQL over it. This is not adoption into live capture or a claim of custody,
atomic publication, licence compliance or restore. Sources:
[Apache Parquet overview](https://parquet.apache.org/docs/overview/) and
[DuckDB Parquet documentation](https://duckdb.org/docs/current/data/parquet/overview).

DEFER installing DuckDB or changing storage formats until exact-cut completeness,
schema/version/hash identity and restore evidence are accepted. Before adoption,
benchmark only public/synthetic fixtures with explicit memory/disk budgets and
cross-platform parity; preserve nulls, timestamps, decimals and missingness.
No managed DuckDB service or cloud account is needed for this design.

DEFER Polars. Its lazy API builds a plan before execution and supports query
optimization; that is useful when future measured transformations justify a
DataFrame engine. Avoid carrying both SQL and DataFrame stacks without a measured
need. Compare semantics and resource use against the simpler existing baseline
using synthetic data before making a dependency decision. Source:
[Polars lazy API usage](https://docs.pola.rs/user-guide/lazy/using/).

## Backtesting: learn the semantics; defer engine selection

ADAPT explicit spread, commission, order timing and margin assumptions from the
Backtesting.py API; it exposes these controls. Backtrader documents data feeds,
broker/commission concepts and strategy infrastructure. Neither documentation
establishes that our instruments, executable prices or labels are available.
Sources: [Backtesting.py API](https://kernc.github.io/backtesting.py/doc/backtesting/backtesting.html)
and [Backtrader documentation](https://www.backtrader.com/docu/).

DEFER both engine installations/integrations until the frozen prospective paper
study has eligible data and registered assumptions. First compare a tiny synthetic
golden event ledger across the existing deterministic baseline and an engine:
signal availability, next eligible execution, fees, spread, missing quotes and
expiry boundaries must match. REJECT treating a frictionless bar backtest or
index snapshots as derivative fills. Current task has no engine performance
benchmark or validated profitability result.

## ML validation: adopt leakage controls; defer training

ADOPT the validation discipline now; DEFER real fitting. Scikit-learn recommends
time-aware validation when observations have time dependence and training-only
preprocessing to prevent leakage. Pipelines help enforce preprocessing within
cross-validation. Sources:
[scikit-learn cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html)
and [common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html).

Project adaptation: register chronological splits, label horizons and an untouched
final holdout before inspection; exclude overlaps and use horizon-appropriate gaps
where necessary. An ordinary TimeSeriesSplit is not proof that overlapping labels,
irregular observations or repeated instruments cannot leak. Keep baseline, costs,
uncertainty, missingness and all attempted model choices visible. Training waits
for trusted daily data, demonstrated custody/restore, licensed executable labels
and completion of the frozen paper-study gates. Sealed 2025/2026 stays sealed.

## Off-PC alerts: defer ntfy and Telegram pending owner acceptance

DEFER ntfy integration. Its documentation describes HTTP publishing, authentication,
access controls and server configuration. Unauthenticated/default-open topics
must not be treated as private merely because their names are hard to guess.
Self-hosting also requires an available host and maintenance; a host on the same
failed PC cannot independently detect its outage. Sources:
[ntfy publishing](https://docs.ntfy.sh/publish/) and
[ntfy configuration/access control](https://docs.ntfy.sh/config/).

DEFER Telegram integration. Its bot FAQ documents rate limits and paid broadcast
options; its privacy policy describes data bots receive. Treat bot messages as
third-party disclosure and do not assume end-to-end secrecy for alert payloads.
Only a minimal redacted session/category/status could be considered later; never
tokens, capture data, positions or private paths. Sources:
[Telegram bot FAQ](https://core.telegram.org/bots/faq) and
[Telegram privacy policy, bot messages](https://telegram.org/privacy/eu#6-bot-messages).

For either option, free hosted access is not guaranteed forever and is not an
SLA. Independent always-on hosting, privacy, quota, delivery and incremental cost
must be established by the owner; unknown means defer. No account, bot, topic,
token, send or subscription is requested now. A successful API/launch receipt is
not observed delivery. Later acceptance needs owner-observed harmless rehearsal,
task-session delivery and an independent missed-run test before reliance.

## Agent tooling: adopt inert contracts; postpone installation and LLMs

ADOPT the existing role contracts and this deterministic conductor as tooling.
DEFER installing Codex custom roles. Official OpenAI documentation describes
custom agent files and states that agents inherit parent permissions: instructions
cannot create an independent read-only sandbox. The OpenAI Docs skill directed
verification against that official page; no user configuration was written. Source:
[OpenAI custom agents and sandbox controls](https://learn.chatgpt.com/docs/agent-configuration/subagents).

DEFER local LLMs. llama.cpp provides local inference tooling, but local execution
still needs model weights, licence review, sufficient hardware, resource budgets
and evaluation; local does not imply zero electricity or hardware cost. This task
needs no inference. Source: [llama.cpp maintainer documentation](https://github.com/ggml-org/llama.cpp).
DEFER paid/API-backed agents and provider setup. No model, key, backend or account
is activated. Runtime role input remains supplied redacted monitoring/reporting
only, with external tool permissions independently enforced.

## Evidence required at the next handoff

ADAPT a prepare/verify/commit boundary for scheduler control: perform slow health
and identity checks while polling remains disabled, retain a local immutable
admission/authorization witness, then submit enablement last. Scheduler submission
and acknowledgement are not enabled-state readback or execution. Unknown outcomes
must remain unknown and forbid retries; cleanup is best-effort, not a guarantee
under stalled RPC, forced termination or power loss. Existing producer gates are
unchanged. This follows the documented distinction between registering/running
tasks and the privileges/operations used to control them:
[Microsoft task security contexts](https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks).

The scout records dated primary sources, choice, rationale, zero-cost basis and
reconsideration trigger. The builder supplies bounded paths and exact candidate
and source pins. A separate reviewer verifies source relevance, the cost claim and
failure paths. The verifier supplies exact-candidate Windows and Linux results,
collection parity, versions, counts and explicit skips. The owner assesses real
clock, notification and commissioning evidence separately. Documentation research
and synthetic contract tests do not establish runtime readiness or authorize any
capture, hosted write, permissions change, retention, trading or real training.
