# Group I — explicit read-only historical repository bridge

Upload AFTER A through H. Eight repository destinations, with three staging sources:

- ROOT `production_repository.py`: use the COMPLETE file in `staged_historical_repository/production_repository.py`. Do NOT use the held dirty root draft.
- ROOT `equity_runtime_health.py`: use the COMPLETE file in `staged_historical_repository/equity_runtime_health.py`. Do NOT use the held dirty root draft.
- ROOT `package_release.py`: use the COMPLETE file in `staged_historical_repository/package_release.py`. Public-main source plus explicit seeds for fingerprinted optional libraries; not the dirty root draft.
- ROOT `ledger_historical_views.py`: bounded original-only readiness and research projections from one verified history cut.
- ROOT `ledger_historical_repository.py`: explicit restricted, read-only factory binding the source reader to the SAME repository connection; no credential discovery or connection at construction.
- `tests/test_ledger_historical_views.py`: synthetic originals, missing labels/proofs, bounds, original signatures, chronology and single-cut tests.
- `tests/test_historical_repository_bridge.py`: actual public repository routing, default-mode compatibility, read-only failure paths, factory and fingerprint closure tests.
- ROOT `HISTORICAL_REPOSITORY_PACKAGE.md`: these instructions.

Never upload the staging folder. Copy the three staged source files into the ROOT
of the clean review clone. Preserve the unrelated held working-folder drafts.
Group F's final source also extracts `audit_history(history)` with unchanged audit
output, so dataset rows and their audit use one cut rather than two live reads.

## Scope and limitations

Four actual public repository read APIs gain an OPTIONAL explicit cold-aware mode:
events, continuity, decision readiness and matured datasets. Default app/collector
factories remain hot-only and unchanged. Nobody may turn on cold pruning merely
because this code is uploaded. The factory needs commissioned protected roots,
terminal heads, exact read roles, licensed immutable-object GET transport, original
historical keys and an explicitly protected spool directory. It installs nothing.

Explicit mode requires validate-only schema handling and exact restricted-role
configuration. Connections are read-only; evidence append is rejected BEFORE
schema work, even with a borrowed connection. Native PostgreSQL role/read-only and
pool-reuse proof still needs an isolated local PostgreSQL rehearsal. Docker was
not available to this session; the WASM harness is not a substitute for that proof.
Existing connection TLS behaviour is unchanged; commission verified transport
and restricted credentials before actual source use. No hosted writes are included.

Projection retains original features and hashes. Unknown target/stop outcomes are
nullable, NOT losses. Unmatured decisions stay visible. Missing or conflicting
identity, chronology, horizon/source references, feature quality and quotes stay
explicit. Compatibility lists are bounded at 20,000 rows/32 MiB; larger analysis
must stream, not truncate. Failure of any final fence fails the whole read.

A signature authenticates a payload, not the correctness of referenced facts.
Therefore training eligibility, PIT verification, costs-applied, executable-quote
verification, external reference verification and production evidence remain
FALSE. Separate original-claim completeness flags do not grant those proofs.
There is no model fit, new hypothesis, rule retuning or reading of sealed periods.

Important pre-existing follow-up: the unchanged DEFAULT hot-only matured dataset
still maps non-TARGET outcomes to zero, uses actual_forward_return as excess_return,
and derives several proof flags from payload claims. This package deliberately
does not silently change that legacy path. Do NOT commission production training
from it. Review/fix those semantics with dedicated compatibility/failure tests
before any ML round; the new explicit historical mode does not make the old path
safe or verify its external evidence. This is remaining engineering, not an owner
setting that can be made green.

## Clean-clone verification

After copying ALL preceding groups and the eight correct destinations:

```powershell
python -m pytest -q tests/test_ledger_historical_views.py tests/test_historical_repository_bridge.py tests/test_ledger_history_consumers.py -p no:cacheprovider --basetemp "$env:TEMP/historical-review-$([guid]::NewGuid().ToString('N'))" --tb=short
python -m pyflakes ledger_historical_views.py ledger_historical_repository.py ledger_history_consumers.py production_repository.py equity_runtime_health.py package_release.py tests/test_ledger_historical_views.py tests/test_historical_repository_bridge.py
python -m mypy --strict --follow-imports=silent ledger_historical_views.py ledger_historical_repository.py ledger_history_consumers.py tests/test_ledger_historical_views.py tests/test_historical_repository_bridge.py
python -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP/historical-full-$([guid]::NewGuid().ToString('N'))"
python -c "from equity_runtime_health import release_fingerprint; print(release_fingerprint('.'))"
```

Use the existing pinned SQL harness/dependencies as CI does, including
`EQUITY_TEST_PGLITE_MODULE`. No new package or lock-file changes are required.
The legacy repository/health sources use the existing legacy type-check regime;
the NEW library/test code above is strict checked. In this dirty local folder only,
factory checking needs `--shadow-file production_repository.py staged_historical_repository/production_repository.py`;
the clean clone needs no shadow override.

Final full-suite results and reviewed candidate fingerprint belong in the morning
handoff after tests terminate. Never calculate a release expectation from the dirty
working folder or copy the running app's hash as its own expected value.

Reviewed clean-public A..J candidate:
`03ad7baa68ebaad1f64b1cd3c356455e1c18cb8f23f027652de303b64b4f8478`.
Source projection preserves raw actual_forward_return separately; excess_return
remains NULL without a benchmark/net proof. Source origin/synthetic-fixture status
is unknown, not asserted false. Mismatched horizon/source/coverage/chronology proof
also leaves the binary label NULL. It never silently relabels these rows as losses.

## Owner handover — only after exact-SHA green CI

1. Keep DASHBOARD_RELEASE_ENABLED=false, installed capture and existing scan-only
   recurrence unchanged. Upload each group in order through its reviewed PR.
2. For I, verify exactly eight PR paths and the public-main-only repository diff.
   Main's collector still constructs the default hot repository. Its recorded code
   fingerprint hashes scheduled_collector/scanner_funnel/decision_evidence, none
   changed here. No collector configuration change is needed for this package.
3. Confirm post-merge quality, resilience and CodeQL on the EXACT final main SHA.
   Recompute the reviewed dashboard fingerprint in that clean clone and compare
   it with this handoff. Stop on ANY disagreement; never force the expectation.
4. Do NOT change Streamlit's expectation while its release still runs old source.
   Group I changes fingerprint members. Later release promotion and root TOML
   expectation update must be an explicit supervised owner handover: identify the
   reviewed target SHA, promote only that green SHA via the release runbook, then
   set EXPECTED_EQUITY_CODE_SHA256 to the separately reviewed candidate hash and
   restart. During a mismatch entries correctly remain blocked. Do not loosen it.
5. Verify all three release expectations VALID/matches_actual, boot/OIDC, clock,
   recovery and delivery. Do not enable cold factory/pruning or additional modes.

The release hold is intentionally unchanged; these instructions prepare a later
owner decision, not authorise an unattended release, hosted migration or deletion.
