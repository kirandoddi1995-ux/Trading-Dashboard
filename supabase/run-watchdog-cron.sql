-- On-time run watchdog: Supabase Cron -> dispatch-scheduled-collector Edge Function
-- -> GitHub workflow_dispatch run-watchdog.yml (RUN_FAILURE_ALERTS_2026-11-18.md).
-- GitHub delivered the watchdog's own schedule up to 5 h late (18 Nov 2026: 04:00 IST
-- slot started 09:17 IST); dispatches start at once. The GitHub schedule stays as a fallback.
--
-- Prerequisites: the same ones as supabase/archive-nightly-cron.sql, and the Edge
-- Function redeployed with the run-watchdog-1130 / -1600 / -0400 targets.
-- Contains secret NAMES only. Safe to re-run.

-- 0. Pre-check before any change: both Vault secrets the jobs read must exist.
do $precheck$
begin
  if (select count(*) from vault.decrypted_secrets
      where name in ('collector_dispatch_project_url', 'collector_dispatch_shared_secret')
        and coalesce(decrypted_secret, '') <> '') <> 2 then
    raise exception 'collector_dispatch_* Vault secrets missing: nothing changed';
  end if;
end
$precheck$;

select cron.unschedule(jobid)
from cron.job
where jobname in ('run-watchdog-1130-ist', 'run-watchdog-1600-ist', 'run-watchdog-0400-ist');

select cron.schedule(
  'run-watchdog-1130-ist',
  '0 6 * * 1-5',
  $job$
    select net.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_project_url') || '/functions/v1/dispatch-scheduled-collector',
      headers := jsonb_build_object(
        'content-type', 'application/json',
        'x-dispatch-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_shared_secret')
      ),
      body := '{"target":"run-watchdog-1130","schedule":"11:30 IST Monday-Friday"}'::jsonb,
      timeout_milliseconds := 10000
    );
  $job$
);

select cron.schedule(
  'run-watchdog-1600-ist',
  '30 10 * * 1-5',
  $job$
    select net.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_project_url') || '/functions/v1/dispatch-scheduled-collector',
      headers := jsonb_build_object(
        'content-type', 'application/json',
        'x-dispatch-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_shared_secret')
      ),
      body := '{"target":"run-watchdog-1600","schedule":"16:00 IST Monday-Friday"}'::jsonb,
      timeout_milliseconds := 10000
    );
  $job$
);

select cron.schedule(
  'run-watchdog-0400-ist',
  '30 22 * * *',
  $job$
    select net.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_project_url') || '/functions/v1/dispatch-scheduled-collector',
      headers := jsonb_build_object(
        'content-type', 'application/json',
        'x-dispatch-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_shared_secret')
      ),
      body := '{"target":"run-watchdog-0400","schedule":"04:00 IST daily"}'::jsonb,
      timeout_milliseconds := 10000
    );
  $job$
);

-- Installation check: three rows, active, with these schedules.
select jobid, jobname, schedule, active
from cron.job
where jobname like 'run-watchdog-%'
order by jobname;
