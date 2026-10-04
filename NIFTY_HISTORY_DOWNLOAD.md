# NIFTY five-minute history: local commissioning runbook

No Supabase, GitHub, dashboard, workflow or order changes. Data stays outside the
project; Drive mirroring is a separate later step. No new dependencies are needed.
Source: https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/

## 1. Review and test before using credentials

From `C:\Users\banga\Desktop\kiran_share_market`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_download_nifty_history.py tests/test_intraday_directional_replay.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pyflakes download_nifty_history.py tests/test_download_nifty_history.py
```

Use an external data directory such as `C:\Users\banga\Documents\TradingResearch\nifty-v1`.
The tool rejects paths inside the project, including paths resolving through links.
Confirm private retention is permitted before using `--licence-confirmed`.
Do not copy credentials into data files, the repository, terminal commands or chat.

## 2. FIRST authenticated run: one completed session

Choose a known regular NSE trading session; the example is 30 September 2026.
Confirm that date against the exchange calendar before running. No bulk download
can proceed until this check passes AND you explicitly acknowledge review.

```powershell
.\.venv\Scripts\python.exe download_nifty_history.py check --date 2026-09-30 --root "C:\Users\banga\Documents\TradingResearch\nifty-v1" --licence-confirmed
```

If `UPSTOX_ANALYTICS_TOKEN` is not already set privately in the process environment,
the tool asks for it with hidden input. Paste the existing token into that prompt,
not into a command. Do not regenerate or display it. Runtime failures emit fixed
error codes, not response bodies, headers, signed URLs or raw exceptions.

Expected: CHUNK_VERIFIED followed by status PASS, count 75, no missing/unexpected
timestamps. First start should be 09:15 IST, last start 15:25 IST. The raw candle
fields are retained in a compressed immutable JSON artifact; its metadata includes
retrieval time and a candle-content SHA256. `session-check.json` is the receipt.

Inspect the saved candles locally. Matching starts and count support the documented
start-time convention, but are not independent proof of the prices or bar semantics.
If available, compare a few completed candles with the broker chart. Do not loosen
the test or shift timestamps to force PASS. A FAIL retains the observed data and
missing/unexpected times, returns a failing exit code, and blocks bulk download.

AUTH_REQUIRED: token access/expiry/entitlement needs operator attention. Redirects
are rejected; TLS verification is never disabled. Rate limits/server/transport
failures have at most three attempts; excessive Retry-After is a failure, not an
unbounded sleep. Normal requests reuse one HTTPS session.

To inspect a different date or preserve revised data, use a new data directory.
Existing artifacts and receipts are never overwritten; corrupt files fail explicitly.

## 3. Bulk download after reviewing the first response

```powershell
.\.venv\Scripts\python.exe download_nifty_history.py download --start 2022-01-01 --end 2026-09-30 --root "C:\Users\banga\Documents\TradingResearch\nifty-v1" --licence-confirmed --reviewed-session-check
```

The tool verifies the receipt against its retained one-session artifact before
requesting a token. Dates are inclusive. Requests remain within calendar months,
never overlap, and exclude the current date. NIFTY key, unit minutes and interval
5 are fixed. Successful cached chunks are validated and reused after interruption;
reruns do not fetch or replace them. A response duplicate/revision is rejected.
Return order is normalized chronologically; original candle values are not filled,
smoothed or adjusted. Empty monthly responses are preserved for subsequent auditing.

Outputs in the chosen external directory:

- Immutable `minutes-5-START-END.json.gz` source-candle artifacts and provenance.
- `nifty-five-minute-2022-01-01-2026-09-30.csv` for the existing replay input format.
- Matching Zstd Parquet, verified through a read-back comparison.
- Manifest with row count, source-row/CSV/Parquet SHA256 and the frozen split.

The manifest hashes should be checked after copying to another disk or Drive.
Use a new directory for any later re-download/revision study, then compare it with
the originals rather than silently replacing historical versions. The pipeline
does NOT upload to Drive automatically or delete source files.

## 4. Calendar and previous closes BEFORE replay

DOWNLOAD_VERIFIED has `replay_ready: false` deliberately. The downloader validates
returned candles but cannot infer whether an entirely absent trading day was a
holiday, outage or missing history. Obtain the official session calendar for
2022-2026, including special sessions. Audit every expected regular date against
75 five-minute starts; retain missing, extra and unsupported special-session dates.
Never build a calendar only from dates that happened to return bars.

The replay needs the preceding completed daily NIFTY close, INCLUDING special
sessions. December 2021 supplies the first prior close. These are Upstox daily
closes, NOT independently verified exchange prices. Daily timestamps are never
labelled as availability five minutes after midnight.

```powershell
.venv\Scripts\python.exe download_nifty_history.py download-daily --root "$env:USERPROFILE\Documents\TradingResearch\nifty-v1" --start 2021-12-01 --end 2026-09-30 --licence-confirmed --reviewed-session-check
```

Review `nifty_session_calendar.py`: annual circulars, amended closures and special
sessions have source links. The 2022 Muhurat and 2025 Budget sessions have
UNVERIFIED timing and remain excluded rather than guessed. Review the first prior
session anchor, 2021-12-31, too. Then use a NEW derived-output directory:

```powershell
.venv\Scripts\python.exe prepare_nifty_replay.py --root "$env:USERPROFILE\Documents\TradingResearch\nifty-v1" --output "$env:USERPROFILE\Documents\TradingResearch\nifty-ready-v2" --calendar-reviewed
```

Without `--calendar-reviewed`, the tool writes an audit but exits 1 and issues no
eligible replay sessions. Missing daily closes exclude affected dates; it NEVER
falls back to an older row or the last five-minute close. `quality.json` includes
every calendar date, missing/unexpected starts, counts and eligibility.
`sessions.json` retains excluded trading dates. Specials are not scored, even
when they contain 75 bars. Warm-up resets after excluded trading dates.
For regular sessions, only starts in [09:15,15:30) IST enter indicators/replay.
Complete sessions with additional outside starts are retained and labelled
REGULAR_COMPLETE_WITH_OUT_OF_SESSION_BARS. Each outside timestamp remains in
both reports and source files; replay rechecks that the declared outside list
exactly matches the source and contains no inside timestamps. Missing regular
bars, inside off-grid bars and duplicates are never repaired by this rule.
`regular_grid_counts` reports before/restored/after counts independently of the
separate calendar-review, previous-close and availability eligibility checks.

`replay_ready: true` means reviewed inputs and at least one eligible session,
NOT complete coverage of all dates. Review exclusions before a study. Unexpected
closed-date bars block readiness. Original downloads remain unchanged.

Local regression command:

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP\nifty-readiness-review" tests/test_download_nifty_history.py tests/test_nifty_readiness.py tests/test_intraday_directional_replay.py
```

After those inputs are verified, prepare ordered session JSON as described in
INTRADAY_OPTION_REPLAY_SPEC.md. Preserve unsupported/missing dates in the quality
report. Current replay excludes incomplete sessions; report their frequency and
whether exclusions concentrate on event/high-volatility days.

`available_at = bar start + 5 minutes` in the analysis exports is an ASSUMPTION,
labelled `historical_final_assumed_bar_end`, NOT the actual retrieval time or proof
that the final candle existed then. Actual retrieval time stays in source metadata.
Historical revisions cannot be reconstructed from a first download today.

## 5. Frozen study split

- 2022-2024: development, chronological comparisons.
- 2025: validation for choosing between frozen candidates.
- 2026 through September: final holdout. Do not inspect strategy outcomes while tuning.

Warm indicators using earlier bars but start each scored evaluation flat. The
current basic runner does not automatically enforce period scoring/warm-up masks:
add and test that orchestration BEFORE reporting split results. A full-history run
is diagnostic, not the agreed holdout test. Missing days and different regimes
must be disclosed; a longer calendar alone does not guarantee independent evidence.

This download cannot provide historical option bid/ask or genuine fills. It does
not lift option-entry holds, satisfy execution evidence, or establish net option P&L.
