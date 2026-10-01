# Read-only diagnostics handover — October 1

## Recommended quick setup: project-scoped read-only Supabase MCP

The existing connector can list the Trading-Dashboard project, but exposes write
tools and account-wide discovery. It has NOT been established as read-only.
No database SQL has been run through that broader connection for this request.
Do not use the application or owner password as a workaround.

Configure a separate read-only connection with this non-secret endpoint:

```
https://mcp.supabase.com/mcp?project_ref=jocpxonpjegfvaseshgd&read_only=true&features=database
```

Authenticate through Supabase's browser OAuth flow, not by pasting credentials in
chat or files. Disable the broader connection for diagnostic sessions. Confirm the
new connection is available before asking the assistant to run the checks.
Supabase documents that read_only=true executes queries as a read-only Postgres
user; project_ref scopes access. This is not the same as merely promising to use
SELECT through an owner connection.

Reference: https://supabase.com/docs/guides/ai-tools/mcp

## Query contract

Only use the approved project and the named read-only SQL files. Every call must
wrap ONE reviewed SELECT (or small related SELECT block) as follows:

```sql
BEGIN READ ONLY;
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '1s';
-- exact reviewed SELECT here
ROLLBACK;
```

Start with block A of sql/storage_relief_access_checks_read_only.sql to verify
identity/settings. Stop if the identity is owner/superuser/BYPASSRLS or the
connector cannot establish the required read-only transaction and timeouts.
Do not test protections by attempting writes. After an error ensure ROLLBACK;
never retry automatically with a longer timeout or a more privileged login.

Then run blocks 1–6 of sql/storage_relief_checks_read_only.sql and B–G of
sql/storage_relief_access_checks_read_only.sql, separately. The SQL is the exact
query inventory; record the actual query, execution time, result summary or
permission/timeout outcome for every call. Return aggregate/catalogue results,
not candle arrays, credentials, raw connection errors or SQL query text from
other users' sessions. Access-denied is not evidence that no rows exist.

Some current checks may exceed five seconds because they scan compressed outcomes.
If so, report the timeout and let the owner decide whether to run it manually
off-hours. Long-transaction details for other roles, prepared transactions,
replication slots and vacuum progress may be hidden from the read-only role:
the owner should run block 3 if results are restricted. An owner also needs to
confirm complete visible outcome counts where RLS filters a diagnostic role.
Do not grant pg_monitor/pg_read_all_data or BYPASSRLS simply to avoid that handoff.

## Dedicated login alternative (not provisioned)

If MCP cannot be configured quickly, retain manual SQL-editor execution for this
cleanup. A later dedicated diagnostics login should have explicit necessary
SELECT/column grants and matching SELECT-only RLS policies, no schema CREATE,
no write grants, no role memberships or BYPASSRLS. Audit callable SECURITY DEFINER
functions too: SELECT-only table grants alone do not neutralize such functions.
Role-default read-only/timeouts are defense in depth, not a replacement for grants.
The owner must review and create it; no role or credential was created here.

Prefer Windows Credential Manager (OS-managed storage) for its password. Do not
store it in the repository, Desktop text files, environment dumps, command-line
arguments, GitHub or this chat. An approved local connector would retrieve it
without displaying it. Do not send the password or full connection string to the
assistant. No database password is needed for the recommended OAuth MCP route.

## Timing and execution status

Leaving the already-deployed archive running overnight is appropriate. Local edits
do not affect it. On October 1, run read-only checks before migration; then follow
the revised STORAGE_RELIEF_RUNBOOK.md. Temporarily suspend scheduled ARCHIVAL only
during the reviewed SQL/code handover; no collector pause is proposed.

No unattended morning execution has been scheduled: this session has no callable
scheduling tool. If read-only connection setup is not ready, run the two SQL files
manually that morning to keep the cleanup on schedule. Do not rely on an assistant
promise of a future automatic run. Once connected in an active session, the assistant
can execute and report the approved read-only checks directly.
