# Group G — isolated Windows release-rehearsal repair

A clean-public Windows rehearsal exposed an existing timeout-cleanup race: killing
the virtual-environment launcher can leave its child interpreter holding the
temporary directory. Cleanup can then mask the intended hard timeout error.
No release is allowed through; this repair preserves the failed gate.

Three upload destinations, after F (or independently from its public baseline):

- release_verification.py — COMPLETE reviewed source from staged_release_timeout_fix/release_verification.py, not the unrelated dirty root draft.
- tests/test_release_timeout_recovery.py — NEW deterministic transient/permanent cleanup failure tests, no real deletion or hosted connection.
- RELEASE_TIMEOUT_REPAIR_PACKAGE.md — NEW instructions.

Copy the staged source file to ROOT release_verification.py in the clean clone;
do NOT upload the staging folder itself. The PR must show exactly these three
destination paths. This candidate is based on verified public main9ce3af9, adding
only bounded private-temporary cleanup retries and termination of THIS probe's
specific Windows process tree before cleanup. It preserves import/network/secret
isolation, manifests, dependency closure and timeout failure. It does not include
the held cold-reader release/fingerprint changes from the local root draft.

```powershell
python -m pytest -q tests/test_release_timeout_recovery.py tests/test_release_packaging.py tests/test_streamlit_boot.py -p no:cacheprovider --basetemp "$env:TEMP/release-timeout-review-$([guid]::NewGuid().ToString('N'))" --tb=short
python -m pyflakes release_verification.py tests/test_release_timeout_recovery.py
python -m mypy --strict --follow-imports=silent tests/test_release_timeout_recovery.py
python -m mypy --follow-imports=silent --check-untyped-defs release_verification.py
```

Require full exact-SHA PR and main checks. Existing public fingerprint inputs do
not include release_verification.py; no expectation update or release enablement.
No capture/task/hosted change. Temporary cleanup retries total at most about one
second; persistent locks remain errors, never silently ignored. Only this probe's
PID/tree may be stopped—never general Python/Streamlit/Task Scheduler processes.
The parent must still be running before invoking taskkill; its helper window is
hidden. One requested-list type annotation is non-behavioural, not a routing change.

The older ROOT release_verification.py draft is preserved locally and stays HELD.
Later cold-factory release work must rebase rather than overwrite this repair.
