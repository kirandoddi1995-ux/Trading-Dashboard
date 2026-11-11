## Change Request: On-time nightly archive (Supabase Cron dispatch) + VACUUM after it
**Requester:** Kiran | **Date:** 10 Nov 2026 | **Priority:** Medium
**Status:** Code on branch `archive-pg-cron-dispatch`; Supabase steps pending (Kiran)

### Description
The nightly restore-proven retention run (`drive-archive.yml`, delete / growing / 100
batches) is started by GitHub's `schedule` at 20:15 UTC. GitHub delivers it 3.5-6.5 h
late (7 Nov 00:08, 7 Nov 23:39, 8 Nov 23:45, 10 Nov 02:45 UTC). On 10 Nov it started
after the 21:15 UTC VACUUM, so that night's deletes were not vacuumed until the next
night.

The collector already gets on-time starts from Supabase Cron through the
`dispatch-scheduled-collector` Edge Function. This change reuses that path:

- **Edge Function:** a fixed server-side target `archive-nightly` that dispatches
  `drive-archive.yml` with `mode=nightly` only. The caller can't choose a workflow or
  pass inputs. Collector requests are unchanged. Deploying it also brings the
  `null`-body check that is in the repo but not in the deployed v6.
- **Workflow:** new dispatch mode `nightly` that runs exactly the scheduled path, with
  the same owner gates (`ARCHIVE_ENABLED`, `ARCHIVE_NIGHTLY_DELETE`; delete itself
  still needs `ARCHIVE_DELETE_ENABLED`). The gates are at job level, like the
  schedule's: when they are off, only the no-secrets, no-checkout `scheduled-hold`
  job runs and `archive` is skipped. The run shows as "Nightly archive (on-time
  dispatch)".
- **Fallback:** the GitHub `schedule` stays. When it fires late, its own step runs
  `archive_on_time_check.py` (read-only `actions: read`; the only step that holds the
  token; `continue-on-error`). The archive step skips only when that step wrote
  `skip=true`: an on-time nightly run on main, created in the last 20 h, whose
  `archive` job concluded success. A held on-time run never counts, and a nightly
  dispatch that reaches the archive job with its gates off fails (exit 3,
  `NIGHTLY_GATE_MISMATCH`) instead of succeeding. The launcher compares the owner
  variables like GitHub does (case ignored), so the two gate layers always agree.
  Anything else (no run found, API error, malformed answer, crashed step) runs the
  archive as before, so it fails open. The check prints one line: `SKIPPED`,
  `NOT_FOUND` or `CHECK_FAILED`.
- **SQL** (`supabase/archive-nightly-cron.sql`): Cron job `archive-nightly-0145-ist` at
  20:15 UTC daily. The VACUUM job moves from 21:15 to 22:45 UTC (04:15 IST), after the
  archive (the 10 Nov run took 84 min).

### Business Justification
Freed space gets vacuumed the same night, the archive no longer drifts into market
hours, and the timing is predictable. Zero cost: public repo, existing secrets and
existing Edge Function.

### Impact Analysis
| Area | Impact | Details |
|------|--------|---------|
| Users | None | No app change |
| Systems | Low | Edge Function redeploy; 1 new Cron job; VACUUM time moved; workflow gains a mode |
| Processes | Low | Nightly retention starts at 01:45 IST on time; late GitHub run usually skips |
| Cost | None | Free tier; no extra DB reads (the skip happens before any connection) |

### Risk Assessment
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Dispatch fails (token expired, Function down) | L | L | GitHub schedule fallback still runs (late) |
| Both runs on one night | L | L | Fallback skips on a successful on-time run; runs are idempotent |
| Wider deletes through the dispatcher | L | H | Target is fixed server-side (`mode=nightly`); TS tests reject other targets and inputs |
| VACUUM overlaps a long archive run | L | L | VACUUM is lock-light; 2.5 h gap |
| Archive overlaps `purge_raw_quotes` (20:00 UTC, same table) | L | L | Purge takes 4-9 s (30 Oct-9 Nov run history); archive starts 15 min later |
| VACUUM job missing or renamed | L | L | SQL step 0 checks it exists and stops before any change |
| Owner turns nightly delete on after a held on-time run | L | L | Held run has no successful `archive` job, so the late schedule runs that night |
| Owner variable spelled `True` / env wiring broken | L | M | Launcher ignores case like GitHub for `ARCHIVE_ENABLED` / `ARCHIVE_NIGHTLY_DELETE`; a gate mismatch inside the archive job fails red, never counts. `ARCHIVE_DELETE_ENABLED` must be exactly `true` (otherwise every nightly run fails red, deleting nothing) |
| `nav-live-backup.yml` dispatched while a late schedule waits | L | L | Same concurrency group: the pending schedule run is replaced. Only matters on a night the on-time run failed; the next night catches up |
| Fallback night: VACUUM (22:45 UTC) runs before the late deletes | M on failure nights | L | Only when the on-time run failed; the next night's VACUUM covers it |
| New mode breaks manual modes | L | M | Tests: manual preview/prune paths unchanged |

### Implementation Plan
| Step | Owner | Timeline | Dependencies |
|------|-------|----------|--------------|
| 1. Merge the PR (workflow learns `nightly`) | Kiran | First | CI green |
| 2. Redeploy Edge Function: Dashboard → Edge Functions → `dispatch-scheduled-collector` → Code → paste repo `supabase/functions/dispatch-scheduled-collector/index.ts` → Deploy (Verify JWT stays off) | Kiran | After 1 | — |
| 3. SQL Editor → run `supabase/archive-nightly-cron.sql` (step 0 stops it, changing nothing, if the VACUUM job is missing) | Kiran | After 2 | Vault secrets (already exist) |
| 4. Verify (read-only, Claude): Function version > 6, Cron rows, first 20:15 UTC run titled "Nightly archive (on-time dispatch)", late schedule skipped | Claude | Next night | 1-3 |

Order matters: if step 3 ran before step 1, GitHub would reject `mode=nightly` (unknown
choice) for that night. The fallback schedule would still run late.

### Communication Plan
| Audience | Message | Channel | Timing |
|----------|---------|---------|--------|
| Kiran | Steps 1-3, then morning check result | Chat | Tonight / next morning |

### Rollback Plan
- Trigger: on-time run fails 2 nights running, or any unexpected delete scope.
- Steps: `select cron.unschedule(jobid) from cron.job where jobname = 'archive-nightly-0145-ist';`
  and `select cron.alter_job(job_id := (select jobid from cron.job where jobname = 'nightly-vacuum-growing-tables'), schedule := '15 21 * * *');`.
  The GitHub schedule keeps running (it no longer finds on-time runs, so it runs every night).
  The workflow and Edge Function changes are inert without the Cron job; revert the PR if wanted.
- Verification: `select jobname, schedule, active from cron.job order by jobid;`

### Approvals Required
| Approver | Role | Status |
|----------|------|--------|
| Kiran | Owner | Pending |

Source pins: `SOURCE_SUPERSESSIONS.json` re-points `.github/workflows/drive-archive.yml`
and `tests/test_archive_commissioning_hold.py` to these bytes;
`security_profile_successors.SUPERSESSIONS_SHA256` re-pins the record. Tests:
`tests/test_archive_on_time_dispatch.py` (job-level gates over every event/mode/variable
combination, launcher wiring, SQL wiring; also runs the Edge Function's TypeScript tests,
which CI never ran before) and `tests/test_archive_on_time_check.py` (the fallback check,
fixed clock, no network).

Live check before this request (read-only, 10 Nov 18:09 UTC): `nightly-vacuum-growing-tables`
is jobid 8, `15 21 * * *`, a single `VACUUM (ANALYZE)` statement. Its only run so far
(9 Nov 21:15 UTC) failed with "VACUUM cannot run inside a transaction block" because it
was then four statements; it was rewritten to one statement on 10 Nov. Tonight's run is
the first test of that fix (11 Nov 08:00 IST storage check).
