# Group D1 — bounded, fully verified original history

Upload after groups A, B and C. Four complete paths, relative to the project root:

- ledger_cold_store.py — updated original-history iterator: oldest-first, one decoded segment at a time; verifies both event and retry locators. Existing list APIs remain.
- ledger_history_stream.py — new private, bounded SQLite staging and original decision/outcome joins. Exhausts signatures, identities, terminal heads and the final source fence BEFORE exposing records.
- tests/test_ledger_history_stream.py — new deterministic synthetic tests, including damaged late segments, unsigned-history distinction, join semantics, time/size limits and cleanup.
- COLD_HISTORY_STREAM_PACKAGE.md — these instructions.

Final source/test also add detached retry lookup through the EXISTING unique
retry index. Invalid identities and closed stages fail, never look absent. Four
extra cases check index use, detached values, context lifetime and identity bounds.

This is a library package, not live activation. No hosted reader, migration,
archive deletion, new credential, capture update or fingerprint change is included.
Unsigned historical events remain unsigned; hash continuity is not promoted to
HMAC authenticity. Original payloads, timestamps, hashes and signatures survive.

## Owner review

Use a fresh branch from current main AFTER C merges. Upload only these four files,
placing the test inside tests/. Require exact-SHA quality, resilience and CodeQL
checks, then verify main's post-merge checks. Keep releases and other existing holds
unchanged. Do not upload the dirty production_repository.py or runtime-health file.

In the intended Python environment, from the clean clone:

```powershell
python -m pytest -q tests/test_ledger_cold_store.py tests/test_ledger_history_stream.py -p no:cacheprovider --basetemp "$env:TEMP/cold-stream-review-$([guid]::NewGuid().ToString('N'))" --tb=short
python -m pyflakes ledger_cold_store.py ledger_history_stream.py tests/test_ledger_history_stream.py
python -m mypy --strict --follow-imports=silent ledger_history_stream.py tests/test_ledger_history_stream.py
```

No actual history is read by those tests. A future consumer must supply an existing
owner-approved protected spool directory, original verification keys and independently
pinned terminal heads. It must impose transport timeouts as well as this library's
between-read deadline. Missing objects and source changes fail closed; partial
iteration is not evidence of complete verification. Spools are temporary, not backups.
Directory names alone do not prove encryption, ACL protection or independent custody.

The pair API preserves the current SQL aggregate join (all outcomes, or explicitly
the first by sequence); it does not decide whether those labels are valid for a
particular intraday study. Research rules and sealed periods are untouched.

## Acceptance boundary

This removes the full decoded-segment accumulation and unbounded in-memory pair
join from the NEW staged interface. Existing callers/factories still need explicit
integration. No hot row may be retired merely because this package passes tests.
