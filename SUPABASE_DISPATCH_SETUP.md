# Supabase Cron to GitHub collector dispatch

This deployment adds an authenticated Supabase Edge Function and six Supabase Cron jobs. It does not remove or alter the existing GitHub `schedule:` entries.

## Create the GitHub token

1. Open <https://github.com/settings/personal-access-tokens/new>.
2. Set the token name to `Trading-Dashboard Supabase Dispatcher`.
3. Set expiration to 90 days and create a reminder to rotate it seven days before expiry.
4. Set resource owner to `kirandoddi1995-ux`.
5. Choose **Only select repositories**, then select only `Trading-Dashboard`.
6. Under **Repository permissions**, set **Actions** to **Read and write**.
7. Leave every other optional repository, organization, and account permission at **No access**. GitHub's automatic read-only Metadata permission is expected.
8. Generate the token and immediately save it as the Supabase Edge Function secret described below. Never put it in this repository, a SQL query, chat, or a Cron request.

## Secret boundary

- `GITHUB_ACTIONS_TOKEN` is an Edge Function secret. Only the function runtime needs it.
- `collector_dispatch_shared_secret` is a database Vault secret used only to authenticate Cron to the function.
- `DISPATCH_SHARED_SECRET` is the matching Edge Function secret.
- `collector_dispatch_project_url` is the Supabase project URL stored in Vault for the Cron request.

The GitHub token must never be committed, placed in Cron SQL, sent in the Cron request, or printed in logs. It belongs in Edge Function Secrets rather than database Vault: the Edge Function is the only component that needs it. Vault holds only the separate Cron-to-function credential.

## Configure Supabase and deploy

1. In the project dashboard, open **Edge Functions**, then **Secrets** or **Manage secrets**.
2. Add `GITHUB_ACTIONS_TOKEN` with the fine-grained GitHub token as its value.
3. Use a password manager to generate a separate random value of at least 64 characters. Add it as `DISPATCH_SHARED_SECRET` in Edge Function Secrets. Keep it available temporarily for step 5; this is not the GitHub token.
4. Open **Integrations > Vault**. If Vault is unavailable, enable the Vault extension under **Database > Extensions**.
5. Create `collector_dispatch_shared_secret` with exactly the same random value from step 3.
6. Create `collector_dispatch_project_url` with the value `https://YOUR_PROJECT_REF.supabase.co`, using the project's real reference.
7. Open **Edge Functions > Deploy a new function > Via Editor**. Name it `dispatch-scheduled-collector`, replace the generated `index.ts` with `supabase/functions/dispatch-scheduled-collector/index.ts`, turn off **Verify JWT**, and deploy. The function performs its own shared-secret check.
8. Open **Integrations > Cron** and enable Cron if prompted. Enable `pg_net` under **Database > Extensions** if it is not already enabled.
9. Open **SQL Editor > New query**, paste `supabase/scheduled-collector-cron.sql`, and run it. The script contains secret names only and creates all six active jobs.

## Verification queries

```sql
select jobid, jobname, schedule, active
from cron.job
where jobname like 'collector-%-ist'
order by jobname;
```

```sql
select jobid, status, start_time, end_time, return_message
from cron.job_run_details
where jobid in (
  select jobid from cron.job where jobname like 'collector-%-ist'
)
order by start_time desc
limit 30;
```

Do not remove the GitHub `schedule:` block until at least three real Supabase-scheduled dispatches have appeared as `workflow_dispatch`, started within five minutes of their intended IST time, and completed successfully. Include at least one `scan` and one non-scan mode in that verification set.

Do not use GitHub's **Disable workflow** command during cutover; that would also disable `workflow_dispatch`. Cutover means removing only the `schedule:` event entries from the workflow YAML after verification.
