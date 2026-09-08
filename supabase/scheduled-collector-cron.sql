-- Prerequisites (create these through Supabase's secret UIs; never put values here):
--   Vault: collector_dispatch_project_url, collector_dispatch_shared_secret
--   Edge Function secrets: GITHUB_ACTIONS_TOKEN, DISPATCH_SHARED_SECRET
-- DISPATCH_SHARED_SECRET and collector_dispatch_shared_secret must contain the same value.

create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net with schema extensions;

-- Safe to re-run: replace only this dispatcher's six jobs.
select cron.unschedule(jobid)
from cron.job
where jobname in (
  'collector-open-0925-ist',
  'collector-scan-1007-ist',
  'collector-scan-1437-ist',
  'collector-close-1545-ist',
  'collector-global-0315-ist',
  'collector-weekly-1800-ist'
);

select cron.schedule(
  'collector-open-0925-ist',
  '55 3 * * 1-5',
  $job$
    select net.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_project_url') || '/functions/v1/dispatch-scheduled-collector',
      headers := jsonb_build_object(
        'content-type', 'application/json',
        'x-dispatch-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_shared_secret')
      ),
      body := '{"mode":"open","schedule":"09:25 IST Monday-Friday"}'::jsonb,
      timeout_milliseconds := 10000
    );
  $job$
);

select cron.schedule(
  'collector-scan-1007-ist',
  '37 4 * * 1-5',
  $job$
    select net.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_project_url') || '/functions/v1/dispatch-scheduled-collector',
      headers := jsonb_build_object(
        'content-type', 'application/json',
        'x-dispatch-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_shared_secret')
      ),
      body := '{"mode":"scan","schedule":"10:07 IST Monday-Friday"}'::jsonb,
      timeout_milliseconds := 10000
    );
  $job$
);

select cron.schedule(
  'collector-scan-1437-ist',
  '7 9 * * 1-5',
  $job$
    select net.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_project_url') || '/functions/v1/dispatch-scheduled-collector',
      headers := jsonb_build_object(
        'content-type', 'application/json',
        'x-dispatch-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_shared_secret')
      ),
      body := '{"mode":"scan","schedule":"14:37 IST Monday-Friday"}'::jsonb,
      timeout_milliseconds := 10000
    );
  $job$
);

select cron.schedule(
  'collector-close-1545-ist',
  '15 10 * * 1-5',
  $job$
    select net.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_project_url') || '/functions/v1/dispatch-scheduled-collector',
      headers := jsonb_build_object(
        'content-type', 'application/json',
        'x-dispatch-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_shared_secret')
      ),
      body := '{"mode":"close","schedule":"15:45 IST Monday-Friday"}'::jsonb,
      timeout_milliseconds := 10000
    );
  $job$
);

select cron.schedule(
  'collector-global-0315-ist',
  '45 21 * * 1-5',
  $job$
    select net.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_project_url') || '/functions/v1/dispatch-scheduled-collector',
      headers := jsonb_build_object(
        'content-type', 'application/json',
        'x-dispatch-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_shared_secret')
      ),
      body := '{"mode":"global","schedule":"03:15 IST Tuesday-Saturday"}'::jsonb,
      timeout_milliseconds := 10000
    );
  $job$
);

select cron.schedule(
  'collector-weekly-1800-ist',
  '30 12 * * 6',
  $job$
    select net.http_post(
      url := (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_project_url') || '/functions/v1/dispatch-scheduled-collector',
      headers := jsonb_build_object(
        'content-type', 'application/json',
        'x-dispatch-secret', (select decrypted_secret from vault.decrypted_secrets where name = 'collector_dispatch_shared_secret')
      ),
      body := '{"mode":"weekly","schedule":"18:00 IST Saturday"}'::jsonb,
      timeout_milliseconds := 10000
    );
  $job$
);

-- Installation check: six active rows with the UTC schedules above.
select jobname, schedule, active
from cron.job
where jobname like 'collector-%-ist'
order by jobname;

