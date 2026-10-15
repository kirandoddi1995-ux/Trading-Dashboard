# Standing programme team — inactive, owner review

## Purpose and boundaries

The lasting deliverable is a dependable daily dataset, not a larger collection of
agents. The team is a support mechanism: build → independent review → exact-byte
Windows/Linux verification → morning go/no-go → evidence audit → post-session
report. Humans retain commissioning and all trading decisions; paper comes first.

Six role contracts and copy-ready TOML strings are implemented in
programme_agent_team.py. No agent configuration is installed, no automation is
created, no model/API backend or paid account is used, and no runtime agent runs.
The pure proposal guard is tested but is NOT a sandbox or security boundary.

Roles:

1. Builder: one offline reviewed package, tests and paths; cannot approve itself.
2. Independent reviewer: read-only falsification and findings; cannot edit its
   reviewed patch or infer private evidence acceptance.
3. Windows/Linux/CI verifier: disposable tests of exact candidate bytes; records
   versions/counts/skips and requires hosted checks for exact final owner SHA.
4. Morning ops guide: supplied dated reports only; missing/stale facts mean NO_GO,
   never enabling, resyncing, retrying or fixing live capture.
5. Evidence auditor: hashes, generations, gaps, forks and custody scope; no prices
   or data need be sent to an LLM. Cannot manufacture labels/licences or missing rows.
6. Post-session reporter: actual coverage, raw-only/missing slots and operational
   failures; no catch-up, deletion, training or trading authority.

Runtime roles 4–6 can ONLY read explicitly supplied redacted reports and report.
Engineering roles run separately in a clean public clone, not the capture capsule.
Reviewer identity must differ from builder and review hash must match built bytes.
An identity string alone is not independent human or organizational governance.

## Why not install a prompt and call it secure?

Current official guidance says custom agent TOML inherits parent permissions,
provider and MCP servers; custom files cannot override these settings. The older
local create-subagent skill's .cursor/agents recipe is not used as Codex truth.
Source: [official custom agent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents).
Use parent read-only sandbox/tool allowlists, no secret-bearing connector, only
redacted input mounts and explicit output location. Verify deny behavior in an
isolated rehearsal before any runtime commissioning. A prompt saying “read-only”
alone is not protection. No unreviewed MCP/plugin installation is required now.

## Owner steps — can wait until capture is safely closed

1. Merge the reviewed package with all exact-head checks green.
2. Ask the agent to render `role_templates()` for review. It returns six TOML
   strings only; it never writes your .codex/agents directory or global settings.
3. Decide whether your existing signed-in Codex access supports custom agents.
   Do not buy an API subscription or create keys to satisfy the zero-cost programme.
4. In a separate read-only parent session, rehearse runtime roles with synthetic
   redacted reports. Confirm attempts to edit, access credentials, enable tasks,
   call trading tools or change hosted resources are denied by actual permissions.
5. Only then owner installs the reviewed templates in the documented location and
   commissions manual report-only use. No runtime schedule is supplied tonight.

No extra account is needed for the offline policy/template tests. Availability
and usage limits of the owner's account are unverified; “zero running cost” is
not a promise of unlimited hosted-agent inference.

## One morning report target, not yet commissioned

GO requires a dated licensed/source-ready session, fresh measured clock, immutable
recipe/policy, exact disabled/enabled task state appropriate to commissioning,
disk/provider/Drive checks and independently tested alerts. Sources disagreeing,
missing or stale ⇒ NO_GO with a plain cause and owner action. A report cannot
enable tasks or turn a late recipe into pre-open evidence. Once real scheduler/
notification/custody and permitted-close-source acceptance are proven, the
supervised daily ritual can be reduced. This run does not remove it prematurely.
