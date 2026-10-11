# Owner procedure: rotate only quant_app_runtime

The reported exposed password must be retired promptly. Do this before admitting
new storage writers. This is a short planned service interruption, not a promise
of zero downtime. No password or connection URL belongs in chat, files in this
repository, screenshots, terminal arguments, SQL Editor history or CI logs.
Do not reset the project's postgres password: that is a different account.
Do not change ledger signing keys, Streamlit fingerprint expectations or release
settings. Do not restore the compromised password if a consumer fails.
Choose a quiescent SAME-role rotation, not an improvised blue/green role: the
current credential inventory, grants and RLS policies were commissioned around
quant_app_runtime. Introducing a new role needs separately reviewed permissions
and restricted-role acceptance. The generic URL check rejects owner identities;
it does NOT enforce that one exact role name. Supabase suggests a new-role rollout
for zero downtime generally; that is not an already-verified drop-in here.

## 1. Inventory by names, not values

Source inspection identifies these DATABASE_URL consumers:

- Streamlit app/runtime repository and evidence services (Streamlit Secrets).
- GitHub scheduled-collector.yml, model-training-readiness.yml,
  model-training-smoke.yml and production-promotion.yml (Actions DATABASE_URL).
- Owner local tools/processes using DATABASE_URL, if any. Their presence is
  unknown; check account/entry names privately, not a recursive credential scan.

ARCHIVE_DATABASE_URL, EQUITY_RESEARCH_DATABASE_URL, DR_DATABASE_URL,
DERIVATIVE_REFERENCE_DATABASE_URL and DATABASE_MIGRATION_URL are separate names.
Do not assume they use another role just because the name differs. Privately
confirm only the username of each configured entry. Update an entry ONLY if it
really authenticates as quant_app_runtime. Previously reported archive/research
roles were separate, but that observation is not a fresh credential inventory.
The forward PC collector's Upstox/Drive credentials are not database passwords;
the installed capture folder remains untouched.

## 2. Hold dispatch and all consumers during the maintenance window

1. Keep DASHBOARD_RELEASE_ENABLED=false and held collector modes held.
2. Supabase -> Integrations -> Cron: note the current active states and schedules;
   pause the two active scan jobs. Do not enable the four held jobs afterwards.
   Pause any other confirmed quant_app_runtime dispatcher, including a housekeeping
   job if its SQL actually authenticates as this role (cron owner postgres alone
   is not this role). Do not change unrelated cron jobs just by name.
3. GitHub -> Actions -> Scheduled evidence collector -> menu -> Disable workflow.
   Wait for in-progress collector/model/promotion runs using this role to finish.
   Do not start manual runs during the window. Temporarily disable any scheduled
   workflow confirmed to use the exposed role; record its previous state.
4. Stop owner-local processes using this role. For the app, privately retain its
   current database entry outside the repo, then temporarily blank ONLY that
   DATABASE_URL value in Streamlit Secrets (an empty TOML string), save and reboot
   the SAME app/release. Preserve every other key/section. Confirm the app reports
   an unconfigured restricted connection and stops database sends. A sleeping app
   is not enough: a visitor can wake it. If a separate environment/section fallback
   keeps it connected, stop and identify that source; do not claim quiescence.
5. As the database owner, inspect session metadata only. Do not select query text:

```sql
SELECT usename, state, count(*) AS sessions
FROM pg_catalog.pg_stat_activity
WHERE datname=current_database() AND usename='quant_app_runtime'
GROUP BY usename,state;
```

Unknown consumers or active transactions mean stop and investigate before the
planned cutover. If misuse is suspected, immediate revocation takes precedence
over avoiding interruption; involve Supabase support rather than leaving the
exposed credential active indefinitely.

## 3. Change the role password using a hidden interactive prompt

1. Generate a new strong random password in the owner's password manager and
   retain it there. Keep the password manager note encrypted.
2. Open an interactive psql owner connection with separate host/database/user
   fields from the Dashboard Connect dialog, SSL verify-full and the reviewed
   CA file. Use psql -X and -W; enter the owner password only at its hidden prompt.
   Do not use a URL containing a password, paste a password into a shell command,
   or use a transcript/recording. This is an OWNER action, not an agent command.
3. Confirm current_user is postgres and the intended database is selected.
   Then enter this command, which contains no secret:

```text
\password quant_app_runtime
```

Enter the new password twice at psql's prompts. Do not use ALTER ROLE PASSWORD
with a plaintext literal in SQL Editor. PostgreSQL documents that \password
avoids plaintext in command history/server logs. Leave all privileges unchanged.
See [PostgreSQL psql](https://www.postgresql.org/docs/17/app-psql.html)
and [ALTER ROLE](https://www.postgresql.org/docs/17/sql-alterrole.html).

## 4. Retire sessions and update consumers while recurrence remains paused

Password rotation does not establish that every already-authenticated client or
pool is gone. After the writers are quiescent, the owner may run the following
targeted session termination. It interrupts this role's connections/transactions;
it must never be run casually during a scan or on all database users:

```sql
SELECT pg_catalog.pg_terminate_backend(pid)
FROM pg_catalog.pg_stat_activity
WHERE datname=current_database() AND usename='quant_app_runtime'
  AND backend_type='client backend' AND pid<>pg_catalog.pg_backend_pid();
```

If connections immediately reappear, find/stop that consumer; do not loop kills.
Supavisor also has client-side pooling/authentication behavior. Backend termination
alone does not prove pooler-client revocation. Test a fresh connection through the
actual configured pooler route; if the old credential is still accepted, leave
recurrence paused and ask Supabase support how to invalidate that role's pooler
authentication cache/client sessions. Do not reset unrelated accounts to force it.
References: [Postgres administration functions](https://www.postgresql.org/docs/17/functions-admin.html),
[Supavisor](https://supabase.com/docs/guides/troubleshooting/supavisor-faq-YyP5tI).

Current Supabase guidance also documents a brief pooler credential-cache delay
after rotation. If a NEW-password pooler login fails, try ONE direct login-only
check using the dashboard's direct route, verify-full and a hidden prompt. A direct
network/IPv6 failure is inconclusive, not evidence of a bad password. If direct
authentication succeeds, wait at least 15 seconds and make one fresh pooler
attempt. If necessary, wait a few minutes for one final controlled attempt;
then contact support rather than looping or rotating again. Keep producers paused
throughout. This avoids stale clients repeatedly tripping the auth circuit breaker.
[Official password-rotation troubleshooting](https://supabase.com/docs/guides/troubleshooting/supavisor-error-password-authentication-failed-after-password-rotation).

1. GitHub repo -> Settings -> Secrets and variables -> Actions -> DATABASE_URL ->
   Update. Privately construct the SAME route, role and SSL settings with the new
   password, percent-encoded once if using a URI. Never print/copy it into logs.
   Update other confirmed consumers of this role from step 1; no blind renaming.
2. Streamlit -> Manage app -> Settings -> Secrets: replace only the database
   credential value at its existing correct location; preserve all other keys,
   sections, OIDC settings and release expectations. Save/restart the SAME release.
3. Update any confirmed owner-local private entry. Do not store it in this repo.
4. One hidden-prompt login-only check through the configured route using the NEW
   credential must authenticate as quant_app_runtime, with no superuser/bypass RLS.
   One login-only check using the retired credential should fail authentication.
   Do not retry failed logins repeatedly or paste exception/URL details into chat.

## 5. Resume gradually, not all modes

1. Wake/restart the app; verify restricted connection, recovery/checkpoint, expected
   fingerprint matches and no authentication errors. Allow pending deliveries to
   drain. Do not scan repeatedly to diagnose configuration.
2. Enable the collector workflow for ONE supervised manual scan; apply_migrations
   remains unchecked. Fresh capacity admission must pass. Check successful capture,
   remote acknowledgement/drain and settled storage growth, not just exit status.
3. Restore ONLY the previously enabled two scan cron jobs and confirmed previously
   enabled consumers. Keep open/close/global/weekly, F&O ingestion and release hold
   unchanged. Record completion time and booleans, not secrets.
4. If a step fails, keep dispatch paused, repair that consumer's NEW credential
   configuration and investigate uncertain deliveries. No automatic resend,
   password rollback, privilege widening or safety-gate bypass.

This rotation does not require a code upload or a dashboard promotion first.
