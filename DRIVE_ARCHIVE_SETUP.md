# Verified Drive archival — review and deployment guide

## What is implemented (and what is not)

Local files only. Nothing has been pushed, migrated on Supabase, authorized with
Google, uploaded to Drive, or deleted from a hosted database.

This pipeline archives only `quant_app.mf_nav` and `quant_app.market_quotes`.
It does NOT prune ledger events, scanner observations, universe versions,
research observations/outcomes, positions, or execution/model records. Those
tables can continue growing; this is not a guarantee that all future data fits
within 500 MB indefinitely. Do not use one generic age-based purge for all tables.

Normal policy: raw quotes retain at least 14 days of BOTH capture time and trading
date. NAV rows older than 14 days are eligible only if a newer NAV exists for the
same scheme. The latest NAV per scheme survives regardless of age. Daily volume
aggregates are retained regardless of age: the scanner needs 20 prior available
trading dates, which do not fit into 14 calendar days. No trading days/volumes
are invented. Recorded maxima are NOT claimed to be final exchange volume.

The maintenance workflow runs at 20:15 UTC (01:45 IST next day), independently of
the dashboard. Scheduled work is disabled until `ARCHIVE_ENABLED=true`. Actual
deletion requires `ARCHIVE_DELETE_ENABLED=true` AND delete mode. Missing/expired
tokens, quota limits, verification failures and missing rollups stop deletion.
Scheduled runs always request delete mode; if the deletion switch is missing or
false, the run fails with DELETION_NOT_ENABLED rather than silently exporting.
Set BOTH repository Actions variables ARCHIVE_ENABLED and ARCHIVE_DELETE_ENABLED
to the exact lowercase value true. These are Variables, not Secrets. Manual
preview/export modes remain available. No migration is required for this policy
change. Defaults still cap a run at 20,000 rows per table; inspect eligible_remaining
and run further reviewed batches if the backlog exceeds that limit.

## 1. Review and manually apply the SQL migration FIRST

File: `sql/drive_archive_draft.sql`.

It creates `quant_app.market_daily_volumes`, `quant_app.archive_manifests`, the
restricted `quant_archive_worker` role and a volume-capture trigger. It aggregates
only existing recorded volumes to initialize the compact table. It does not delete
source rows. The trigger and backfill are installed under a brief write lock to
avoid a collection gap. Run off-hours; failure/timeouts roll back the transaction.
The script is rerunnable. No startup auto-migration is added.

The Supabase CLI could not initialize under this session's filesystem restrictions;
this is an explicitly named review draft, not an automatically applied migration.

Permissions:

- Archive worker: CONNECT/TEMP on `postgres`; USAGE on `quant_app`;
  SELECT/DELETE on **only** `mf_nav` and `market_quotes`;
  SELECT on daily volumes; SELECT/INSERT/UPDATE on archive manifests.
- App runtime: SELECT/INSERT/UPDATE on the new daily table, EXECUTE on the
  SECURITY INVOKER insert-trigger function; no new source DELETE permission.
- Research collector: no grants on either new table. Public, anonymous,
  authenticated and service-role direct grants on the new tables are revoked.
- No SECURITY DEFINER function or broad table grant is introduced. The archive
  worker checks its exact role, no administrative flags/memberships, and rejects
  access to other relations in the three application schemas. Existing PUBLIC
  grants elsewhere must be reviewed if that check fails; don't bypass the check.

Set the archive role password privately. Build its Supabase **Session pooler**
connection string using username `quant_archive_worker.PROJECT_REF`, the actual
pooler hostname/port shown by Supabase, database `postgres`, and the role password.
Percent-encode password special characters. Store the URL as an Actions secret,
never in a file uploaded to GitHub. Do not use the `postgres` owner connection.

Optional read-only post-migration check (should return zero missing maxima):

```sql
SELECT COUNT(*) AS missing_or_lower_daily_maxima
FROM (
    SELECT instrument_key, trade_date, MAX(volume) AS captured_max
    FROM quant_app.market_quotes
    WHERE volume IS NOT NULL
    GROUP BY instrument_key, trade_date
) raw
LEFT JOIN quant_app.market_daily_volumes daily
  USING (instrument_key, trade_date)
WHERE daily.instrument_key IS NULL OR daily.max_captured_volume < raw.captured_max;
```

The daily table mirrors insert-only capture, including older collector releases.
Direct correction/deletion of source data outside this pipeline is not supported
as a way of recalculating historical maxima; that would need separate reconciliation.
No source snapshots are overwritten with constructed OHLC data.

## 2. One-time Google setup on Windows

1. Sign in to the dedicated Gmail account in Google Cloud Console. Create/select
   its Google Cloud project and enable **Google Drive API**.
2. Configure Google Auth Platform branding/audience for an External application.
   This integration requests only `https://www.googleapis.com/auth/drive.file`.
3. Move publishing status to **In production** before final authorization.
   Google's External/Testing refresh tokens with Drive scope expire in 7 days.
   Production is not a promise tokens never expire: revocation, account changes,
   or token limits can still require reauthorization. Follow any consent or
   verification steps Google shows; do not add broad Drive/Gmail scopes.
4. Create an OAuth client of type **Desktop app**, NOT Web application and NOT
   service account. Download its JSON privately as `client_secret.json` in this
   local project directory. Do not upload it to GitHub.
5. In PowerShell, in the project directory:

```powershell
python -m pip install -r requirements-archive.txt
python authorize_drive.py
```

Use the project's Python 3.13 environment for the supplied pinned versions (the
existing project's dependency set is tested on 3.13, not 3.11). If `python` points
elsewhere, use `.venv\Scripts\python.exe` for both commands.

The script opens the browser, asks you to choose the archive account and grant
consent, and listens only on a random **127.0.0.1** port. It uses PKCE and validates
OAuth state. It creates `Trading Dashboard Verified Archives` using this OAuth
client so `drive.file` can access that folder without full-Drive permission.

It saves `token.json`, which contains the refresh token, OAuth client credentials,
and `archive_folder_id`. It does not print these values. Windows file ACLs are
restricted to the current user before secret bytes are written; existing token
files are never overwritten. File ACLs do not replace disk encryption, secure
backups or protecting the Windows account itself.

Treat both JSON files as credentials. They are gitignored, but manual GitHub upload
can bypass gitignore: **never select them for upload**. Also exclude all downloaded
Parquet datasets from GitHub. Keep a private backup of these credential files.

For reauthorization, use the SAME OAuth client and Gmail account, move the old
token file privately, rerun authorization and replace the Actions token secret.
The script creates a NEW folder on each authorization; when rotating a token,
keep the original folder ID in Actions to retain access to existing batches.
Confirm that original folder remains accessible before enabling deletion again.

## 3. GitHub Actions configuration

Repository Settings → Secrets and variables → Actions → **Secrets**:

- `ARCHIVE_DATABASE_URL`: restricted archive-role Session pooler connection URL.
- `DRIVE_OAUTH_TOKEN_JSON`: **the entire contents of token.json**, including braces.
- `DRIVE_ARCHIVE_FOLDER_ID`: `archive_folder_id` from token.json.

Under **Variables**, initially leave both unset (or set `false`):

- `ARCHIVE_ENABLED`
- `ARCHIVE_DELETE_ENABLED`

No new Streamlit secrets are required for archival. No maintenance credential is
placed in the dashboard. The GitHub job installs `requirements-archive.txt` only;
the dashboard's requirements are unchanged. The collector also supports an explicit
`python scheduled_collector.py --archive ...` entry point when its normal full
environment is installed. Scans never invoke maintenance automatically.

The modified production repository is release-fingerprinted. After uploading it,
update this existing Streamlit secret (leave the policy hash unchanged):

```toml
EXPECTED_EQUITY_CODE_SHA256 = "ce607905bedbab25f59fc96389201cfaaa3a8f3e1efa3b3969781397cde2d9cd"
```

Apply migration before deploying the reader. A missing table must fail visibly,
not silently fall back to an incomplete volume history.

## 4. First-run verification (before deleting anything)

The immediate COUNT preview can also be run independently in Supabase SQL Editor:

```sql
SELECT COUNT(*) AS eligible_rows
FROM quant_app.mf_nav old
WHERE old.nav_date < DATE '2026-09-13'
  AND EXISTS (
    SELECT 1 FROM quant_app.mf_nav newer
    WHERE newer.scheme_code=old.scheme_code AND newer.nav_date>old.nav_date
  );
```

Do not follow that with an unguarded date-based DELETE. `ArchiveRepository.acknowledge`
in `archive_maintenance.py` contains the actual DELETE: it joins a temporary table
populated from the verified downloaded archive on the original primary keys,
requires `to_jsonb(source)=archived_original`, and rechecks eligibility. The
manifest acknowledgment and source deletion commit in the same transaction.

In Actions → **Verified Drive archive (NAV and raw quotes only)** → Run workflow:

1. Choose `preview`, `mf_nav`, and one-time cutoff `2026-09-13`. This is read-only
   and does not call Drive. It reports the actual eligible count, not a hardcoded
   75,060. That was the earlier snapshot, not a permanent expected value.
2. Choose `export` with the same table/cutoff. It exports **one batch only**
   (default 1,000 rows), verifies it, records its manifest, deletes zero source
   rows, and reports how many remain eligible. This is deliberately a smoke test,
   not a claim that the whole table was archived.
3. Open the Drive folder. Check the `.parquet` and `.manifest.json` pair. Download
   both privately to your PC. The manifest has SHA-256, row count, source table,
   batch ID, source types and the Drive data-file ID.
4. Confirm the source rows are still present and the database manifest's
   `completed_at` is NULL. A green export job does not mean cleanup happened.
5. After reviewing that first archive, set `ARCHIVE_DELETE_ENABLED=true` and run
   `delete` with the same table/cutoff. The downloaded archive must match before
   exact source rows are deleted. Counts and the manifest are committed together.
6. Once that works, set `ARCHIVE_ENABLED=true` to enable daily scheduled maintenance
   using the normal 14-day cutoff for BOTH tables. One-time NAV cutoff is never
   applied to scheduled runs and cannot be used for quotes.

For a historical batch, the default run handles at most 20 × 1,000 rows. Repeat
the manual run if `eligible_remaining` is positive. No delete is inferred from a
green status alone: inspect `verified`, `deleted`, `retained`, and remaining counts.

Failure or changed rows: unchanged verified rows may already be safely removed,
but changed rows remain in the database and the job reports failure for review.
The next run exports the changed content under a new identity. Never remove a
Drive file just because a previous run failed. If the Drive quota is full, token
expires, a checksum fails, duplicate batch files exist, the role is too broad or
daily-volume coverage is missing: **no affected batch deletion proceeds**.

## 5. Integrity, retries, storage and restore

Parquet uses Zstandard compression, explicit UTC timestamps/dates, nullable values,
and NUMERIC values as **decimal strings**, not floats (source NUMERIC is unbounded).
Each source field has its own column for analysis. The original PostgreSQL row is
also retained as canonical `_row_json` for exact restore/delete checks. JSONB is
encoded as lossless JSON text. There is no CSV fallback silently changing types.

Uploading success or matching row count alone does not authorize deletion. The
job downloads both files, checks SHA-256 against the original bytes, verifies all
column values and primary keys against the frozen snapshot, and checks the
manifest. It then deletes only rows equal to that snapshot and still eligible.
Network calls happen outside source transactions. Each batch commits separately.
A transaction-scoped advisory lock serializes final acknowledgments; GitHub also
serializes workflow runs. An uncertain upload is found by batch ID on retry.
Conflicting files/manifests fail closed and are not overwritten.

After a crash before deletion, source rows remain. After a crash after commit,
removed rows no longer select; the committed manifest remains. If a duplicate
delivery arrives, the existing manifest must agree. External removal/corruption
of a Drive file after verification remains a real risk: keep a second PC backup
and don't treat Drive as immutable/WORM storage. Supabase and Google Drive are
not one distributed transaction. The worker cannot prevent an account owner
from later deleting archives. Protect the dedicated account with MFA.

Read-only local verification example for a downloaded pair:

```python
import json
from pathlib import Path
from drive_archive import verify_parquet
manifest = json.loads(Path('downloaded.manifest.json').read_text())
rows = verify_parquet(
    Path('downloaded.parquet').read_bytes(), manifest['source_table'],
    manifest['batch_id'], manifest['rows'], manifest['sha256'])
print('Verified rows:', len(rows))
```

For ML, read Parquet directly and explicitly parse numeric strings with Decimal
where exact arithmetic is needed. Archive selection and source field definitions
are metadata, not a claim that raw quotes constitute executable fills or valid
training labels. Research/production-evidence gates are untouched.

Restore procedure: verify the files first; load `_row_json` into a staging table
in an isolated test database; reconstruct typed rows using
`jsonb_populate_record(NULL::quant_app.mf_nav, original_json)` (or market_quotes);
compare all columns and counts. Only after review, use an authorized restore role
to insert absent source rows. Conflicting existing keys must stop restore rather
than be overwritten. The archival worker intentionally has NO source INSERT or
UPDATE grant. The tests perform this typed restoration for NAV, including exact
NUMERIC. No automatic production restore command is provided.

Storage estimates based on the earlier measured snapshot:

- Initial NAV candidates contained ~19.6 MiB of row data (75,060 rows), excluding
  indexes/physical effects. This is NOT a guaranteed disk-size reduction.
- Raw quotes had 148,019 rows versus 34,346 instrument/date combinations: ~76.8%
  fewer rows in the compact representation, also with much smaller fields.
- The daily table ADDS some storage initially. The 14-day policy now permits
  older eligible raw snapshots to be archived and deleted. Do not assume
  this alone guarantees staying under 500 MB. Monitor ALL growing tables daily.
- Normal VACUUM makes deleted space reusable; it does not generally shrink files.
  VACUUM FULL needs an exclusive lock and spare working space. It is NOT executed
  automatically by this job. Review physical reclamation separately before quota
  exhaustion, and consider temporary extra capacity if necessary.

## Official references

- Desktop OAuth/PKCE and loopback: https://developers.google.com/identity/protocols/oauth2/native-app
- Refresh-token expiry: https://developers.google.com/identity/protocols/oauth2#expiration
- Narrow Drive scope: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- Uploads: https://developers.google.com/workspace/drive/api/guides/manage-uploads
- Database size: https://supabase.com/docs/guides/platform/database-size

Hosted Google OAuth, Drive transport, Supabase role grants/locks and the first
archive/delete run still require deployment verification. Local mocks and local
PostgreSQL tests are not evidence that hosted credentials are configured correctly.

## Local validation delivered

- Full regression suite: **644 passed, 2 subtests passed** (Python 3.13).
- Focused archival tests: **20 passed**, including local PostgreSQL/PGlite tests.
- Changed Python files pass pyflakes; installed dependencies pass `pip check`.
- Local SQL tests cover migration reruns/backfill, runtime trigger rollback,
  unchanged 20-date volume averages before/after deleting raw quotes, zero/NULL
  volume behavior, newest-per-scheme retention, concurrent NAV correction,
  manifest conflicts, repeated acknowledgments, missing-rollup refusal, exact
  NUMERIC restoration and research-role denial.
- Local PGlite tests substitute the advisory lock (there are no shared processes
  in that test database); real hosted lock behavior is a deployment check.

Upload the explicitly listed changed files, not the legacy `package_release.py`
ZIP, whose existing allowlist does not include this new maintenance pipeline.
Do not upload `token.json`, OAuth client JSON, raw datasets, or local databases.
