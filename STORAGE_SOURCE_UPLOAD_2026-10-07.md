# Consistent upload group — diagnostics and explicit manual source, not storage commissioning

Source folder: C:\Users\banga\Desktop\kiran_share_market. Paths below are relative
to that folder; ROOT files must not land under tests/ or staged_capture_repair/.

Use one reviewed branch/PR. Do not sweep the changing workspace into main or
upload only the tests. Preserve folder locations. The first resumed scan (#158)
has now passed and settled; main can unfreeze for this complete reviewed PR.
These files are not needed to restart the collector. Do not merge during an
active collector/archive run. No migration/workflow/settings/secret change is included.

## Repository root (13 complete files)

- nse_owner_close.py — new owner-attested retained-source contract.
- nse_close_transport_check.py — existing explicit one-request transport diagnostic;
  offline preview by default, no retry or capture preparation.
- nse_close_file_check.py — existing offline bounded CSV structure/date check;
  does not establish authenticity or prepare capture.
- nifty_previous_close.py — root alignment with the already-reviewed transport
  redaction repair (already on main); no URL/TLS/timeout/fallback change.
- forward_nifty_producer.py — strict v3 source validation; v1/v2 retained.
- forward_nifty_schedule.py — explicit manual preparation, v3 polling/audit,
  and root alignment with the already-reviewed missing-recipe repair.
- storage_commissioning.py — new inactive pure checklist, never deletion authority.
- storage_policy.py — UNCHANGED existing local dependency; include it if absent
  from main. It was part of the withdrawn storage group and must not be assumed
  present on main. Standard-library-only, no hosted execution on import.
- PERMANENT_STORAGE_ROLLOUT.md — selected design/order/risks/acceptance.
- NSE_OWNER_CLOSE_RUNBOOK.md — exact owner install and supervised next-day flow.
- PERMANENT_STORAGE_DESIGN.md — prior component design, cross-linked; still unready.
- AUTOMATION_PROGRESS.md — continuity and test results.
- STORAGE_SOURCE_UPLOAD_2026-10-07.md — this inventory.

## tests/ (5 complete files)

- tests/test_nse_owner_close.py — new source/scheduler/parity failure and edge tests.
- tests/test_nse_close_transport_check.py — offline transport/redaction failure tests.
- tests/test_nse_close_file_check.py — synthetic-file date/schema/preview tests.
- tests/test_storage_commissioning.py — new proof/capacity/calendar checklist tests.
- tests/test_storage_policy.py — UNCHANGED dependency tests; include if absent on
  main, alongside storage_policy.py. No SQL harness or review migration needed.

Total 18 files (the original 14 plus four existing diagnostic files). One PR,
not a second diagnostic PR. No .github/, sql/ or supabase/ upload in this group. Do not include
the rest of the unfinished ledger package. LOCAL ONLY companion changed:
staged_capture_repair/forward_nifty_schedule.py; do not upload it instead of the
root scheduler. Its optional parity test also works when staging is absent.

For the installed PC capture folder, ONLY the four capture root Python files are
needed. Existing reviewed dependencies remain installed. Tasks stay disabled
until the runbook's supervised preparation/poll acceptance. Old code/state remain
private and preserved; source environment hashes change for fresh recipes.

Checks/results are in AUTOMATION_PROGRESS.md. Full local suite includes unfinished
local storage tests; it must not be described as exact-main CI. Require quality,
resilience and CodeQL for the complete uploaded SHA. No equity fingerprint input
changed, so no EXPECTED_EQUITY_CODE_SHA256 update is needed for this package.

The two diagnostic tools are optional in the installed PC capture folder: they
are not dependencies of owner-file preparation/poll/audit. The required installed
capture set remains the four root modules above. No repeated transport probe is
requested as part of this upload.
