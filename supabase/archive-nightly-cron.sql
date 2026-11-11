-- On-time nightly archive: Supabase Cron -> dispatch-scheduled-collector Edge Function
-- -> GitHub workflow_dispatch drive-archive.yml mode=nightly (ARCHIVE_ON_TIME_DISPATCH_2026-11-10.md).
--
-- Prerequisites: the same ones as supabase/scheduled-collector-cron.sql (Vault secrets
-- collector_dispatch_project_url and collector_dispatch_shared_secret, pg_cron, pg_net),
-- and the Edge Function redeployed with the "archive-nightly" target.
-- Contains secret NAMES only. Safe to re-run.

-- 0. Pre-check before any change: the VACUUM job moved in step 2 must exist and be
--    active (it was created by hand and is not in the repo; alter_job below changes only
--    its schedule). Stops here, changing nothing, so a disabled VACUUM is never left behind.
do $precheck$
begin
  if not exists (select 1 from cron.job where jobname = 'nightly-vacuum-growing-tables' and active) then
    raise exception 'nightly-vacuum-growing-tables missing or inactive in cron.job: nothing changed';
  end if;
end
$precheck$;

-- 1. Nightly archive at 20:15 UTC (01:45 IST), every day: exactly the GitHub schedule's
--    slot, but on time. The GitHub schedule stays as a fallback that skips itself when
--    this run succeeded.
select cron.unschedule(jobid)
from cron.job
where jobname = 'archive-nightly-0145-ist';

select cron.schedule(
  'archive-nightly-0145-ist',
  '15 20 * * *',
  $job$
    select net.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_project_url') || '/functions/v1/dispatch-scheduled-collector',
      headers := jsonb_build_object(
        'content-type', 'application/json',
        'x-dispatch-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_shared_secret')
      ),
      body := '{"target":"archive-nightly","schedule":"01:45 IST daily"}'::jsonb,
      timeout_milliseconds := 10000
    );
  $job$
);

-- 2. VACUUM after the archive has deleted, not during it: 21:15 -> 22:45 UTC (04:15 IST).
--    The 10 Nov run took 84 min from 02:45 UTC; an on-time 20:15 start ends well before 22:45.
--    Single statement (a VACUUM job must be exactly one statement).
select cron.alter_job(
  job_id := (select jobid from cron.job where jobname = 'nightly-vacuum-growing-tables'),
  schedule := '45 22 * * *'
);

-- Installation check: both rows active with these schedules.
select jobid, jobname, schedule, active
from cron.job
where jobname in ('archive-nightly-0145-ist', 'nightly-vacuum-growing-tables')
order by jobname;
