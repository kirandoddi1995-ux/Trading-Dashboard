# Group F — original-history consumer adapters

Upload AFTER D2; E can precede F. Three complete paths:

- ledger_history_consumers.py — explicit staged-source adapter for original events, retry lookup/absence, continuity audit and decision/outcome joins.
- tests/test_ledger_history_consumers.py — actual staged-reader synthetic integration and every-consumer late-fence failure tests.
- COLD_CONSUMER_ADAPTER_PACKAGE.md — this runbook.

```powershell
python -m pytest -q tests/test_ledger_history_consumers.py tests/test_ledger_staged_reader.py tests/test_ledger_history_stream.py -p no:cacheprovider --basetemp "$env:TEMP/cold-consumer-$([guid]::NewGuid().ToString('N'))" --tb=short
python -m pyflakes ledger_history_consumers.py tests/test_ledger_history_consumers.py
python -m mypy --strict --follow-imports=silent ledger_history_consumers.py tests/test_ledger_history_consumers.py
```

All reads use the complete verified cut. Failed final fences cannot become empty
retry results or partial training pairs. Compatibility aggregate lists are bounded;
large callers must stream rather than receive an unbounded list. Continuity and
original HMAC coverage are reported separately, including empty/unsigned history.
No label validity, calibrated model or trading authority follows from continuity.

This is an injected adapter, NOT an automatic production factory change. A later
reviewed integration must connect every actual repository/factory caller and supply
a protected private spool path explicitly. Current dirty production_repository.py
still contains the old in-memory pair adapter and must NOT be uploaded as part of
this package. The old raw reader APIs also remain compatibility interfaces; use
the new consumer adapter for exhaust-before-exposure semantics.

Related operations needing a single cut must share history(); separate API calls
can observe different valid cuts. No live keys, directories, Drive transport or
database configuration are discovered here. No fingerprint expectation change.
Fresh PR, exact-SHA full CI and post-merge main checks, with existing holds unchanged.

Final overnight source extracts audit_history(history) for same-cut dataset
audits, uses the unique-index retry lookup, and preserves original caller errors/
interruptions even if a source wrapper suppresses or replaces them. Ten added
cases ensure a result bound cannot become shorter success. No factory is activated.
Group I separately connects optional repository APIs and changes fingerprint members.
