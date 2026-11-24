-- Owner-run once in the Supabase SQL Editor (Kiran chose "retire job 7", 24 Nov 2026).
-- Removes pg_cron job 'purge_raw_quotes' (job 7) and nothing else.
--
-- Why: job 7 runs `UPDATE quant_app.market_quotes SET raw = NULL WHERE observed_at < now() - interval '3 days'`
-- every night at 20:00 UTC. Since the typed_only_v1 change the collector stores no provider payload: every
-- new quote row holds only the 35-byte marker {"retention": "typed_only_v1"} in raw (checked 24 Nov), and the
-- nightly archive deletes quote rows after 14 days. So the job saves at most ~2 MB, yet it rewrites every
-- row older than 3 days each night (23 Nov: 44,054 rows written, 5,520 newly purged) -> WAL, dead rows, a
-- nightly autovacuum. Retiring it keeps the marker on rows until the archive deletes them (~+2 MB).
-- db_maintenance_watch.py watches only the VACUUM job (8), so nothing alerts once job 7 is gone.
--
-- Rollback (puts job 7 back with the same schedule and command; it gets a new job id):
--   select cron.schedule('purge_raw_quotes', '0 20 * * *',
--     'UPDATE quant_app.market_quotes SET raw = NULL WHERE observed_at < now() - interval ''3 days''');
--   Before a rollback, let pending archive batches prune first: the re-created job would NULL the marker on
--   rows already exported with it, and the archive's exact-row delete check would then stop for review.

-- 0. Pre-check before any change: job 7 exists, is active and still runs the recorded command at the
--    recorded time. Stops here, changing nothing, if not (someone changed it: look before removing).
--    A second run after a successful one also stops here: expected, the job is already gone.
do $$
begin
  if not exists (
      select 1 from cron.job
      where jobname = 'purge_raw_quotes' and active and schedule = '0 20 * * *'
        and command = 'UPDATE quant_app.market_quotes SET raw = NULL WHERE observed_at < now() - interval ''3 days''') then
    raise exception 'purge_raw_quotes missing, inactive or not the recorded job: nothing changed';
  end if;
end $$;

-- 1. Remove job 7 (its past run history in cron.job_run_details stays).
select cron.unschedule('purge_raw_quotes');

-- 2. Check: 0 rows named purge_raw_quotes; the VACUUM job is still there and active.
select jobid, jobname, schedule, active from cron.job
where jobname in ('purge_raw_quotes', 'nightly-vacuum-growing-tables') order by jobid;
