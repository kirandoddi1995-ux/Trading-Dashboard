"""Plain status provenance and unchanged timing gates; no private evidence reads."""
import csv
from datetime import date, datetime
from pathlib import Path

import pytest

from forward_daily_contract import gate

ROOT = Path(__file__).resolve().parents[1]
HEADER = ('concept_or_task', 'built_in_source', 'tested_owner_linux_hosted_ci',
          'installed_and_enabled_owner_machine', 'proven_real_dated_evidence', 'not_verified')
CONCEPTS = [
    "NSE transport and daily preparation automation",
    "Standing role-based agent team",
    "Full Supabase database restore drill",
    "Upstox Analytics authorization and licence",
    "Runtime database credential rotation",
    "Setup and tools checkout",
    "Dated poll task",
    "Dated audit task",
    "Fresh official owner-close file",
    "Prepare and policy freeze",
    "Supervised Start admission",
    "Automatic recurrence",
    "Version-aware capture and revisions",
    "Local journal and capture receipts",
    "Drive publish and remote readback",
    "Independent encrypted custody and restore",
    "Daily local audit",
    "Remote custody audit",
    "Local alert notification",
    "Independent alert delivery",
    "Windows Time service",
    "Producer fresh clock gate",
    "14 October historical read-only audit",
    "Legacy audit result2 and shared-root writes",
    "OPTION_CAPTURE_ENABLED skipped schedules",
    "Consistent-cut exports",
    "Writer guards and cold readers",
    "Universe shadow deduplication",
    "Bounded retention and deletion",
    "Capacity guard across live writers",
    "Capacity alerts",
    "ML backtesting and Evidence Assistant",
    "Licensed frozen paper-first study",
    "Pinned Python and PowerShell toolchain",
    "Encrypted-disk 7-Zip tool"
]


def rows() -> list[dict[str, str]]:
    with (ROOT / 'PROJECT_STATUS_LEDGER_2026-10-16.csv').open(encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == HEADER
        return list(reader)


def test_exact_concepts_and_explicit_provenance() -> None:
    ledger = rows()
    assert len(ledger) == len(CONCEPTS) == 35
    assert {row['concept_or_task'] for row in ledger} == set(CONCEPTS)
    for row in ledger:
        assert set(row) == set(HEADER)
        for column, value in row.items():
            assert value and not value.startswith(('=', '+', '-', '@'))
            if column != 'concept_or_task':
                assert value.startswith(('S:', 'B:', 'O:', 'NV:')), (row['concept_or_task'], column)
        assert row['not_verified'].startswith('NV:')


def test_setup_evidence_does_not_turn_on_capture_or_claim_custody() -> None:
    ledger = {r['concept_or_task']: r for r in rows()}
    assert '03:52' in ledger['Setup and tools checkout']['proven_real_dated_evidence']
    assert 'completed' in ledger['Supervised Start admission']['installed_and_enabled_owner_machine']
    assert 'Ready' in ledger['Dated audit task']['installed_and_enabled_owner_machine']
    assert 'false' in ledger['Remote custody audit']['proven_real_dated_evidence']
    assert 'no learned trading edge' in ledger['ML backtesting and Evidence Assistant']['proven_real_dated_evidence']
    assert 'not independently' not in ledger['Setup and tools checkout']['proven_real_dated_evidence']


def test_final_day_owner_witness_never_commissions_training_or_custody() -> None:
    import json
    witness=json.loads((ROOT/'FRIDAY_COMPLETION_WITNESS_2026-10-16.json').read_text(encoding='utf8'))
    audit=witness['manual_read_only_audit']
    assert audit['recorded_decisions']==75 and audit['missing_decisions']==0
    assert audit['generation_sha256']=='17f7fbd62eafd8770ef2370becc5936a8fef16e4d6d71bee03f66d0ac08aabe9'
    assert witness['provenance'].startswith('OWNER_REPORTED')
    assert audit['training_eligible'] is audit['remote_custody_verified'] is audit['full_session_cohort_eligible'] is False
    assert witness['scheduled_audit_report_content_independently_inspected'] is False
    assert witness['production_blocked_poll_alert_seen'] is False
    assert witness['dated_poll']['next_run'] is witness['dated_audit']['next_run'] is None


@pytest.mark.parametrize('at,download,accepted', [
    ('2026-10-16T00:00:00+05:30', '2026-10-16T00:00:00+05:30', True),
    ('2026-10-16T07:30:00+05:30', '2026-10-16T07:29:30+05:30', True),
    ('2026-10-16T09:14:59.999999+05:30', '2026-10-16T09:14:00+05:30', True),
    ('2026-10-16T09:15:00+05:30', '2026-10-16T09:14:00+05:30', False),
    ('2026-10-16T07:30:00+05:30', '2026-10-15T23:59:59+05:30', False),
    ('2026-10-16T07:30:00+05:30', '2026-10-16T07:30:01+05:30', False),
])
def test_prepare_gate_exact_boundaries(at: str, download: str, accepted: bool) -> None:
    def evaluate() -> None:
        gate(date(2026, 10, 16), datetime.fromisoformat(at), 'Prepare',
             calendar_kind='REGULAR', elevated=False, downloaded=datetime.fromisoformat(download))
    if accepted:
        evaluate()
    else:
        with pytest.raises(ValueError):
            evaluate()


def test_start_gate_is_not_the_wait_gate_or_a_safe_launch_deadline() -> None:
    # This proves only the pure gate. It never runs the actual coordinator.
    gate(date(2026, 10, 16), datetime.fromisoformat('2026-10-16T03:55:00+05:30'),
         'Start', calendar_kind='REGULAR', elevated=False)
    with pytest.raises(ValueError, match='FIRST_START_DEADLINE'):
        gate(date(2026, 10, 16), datetime.fromisoformat('2026-10-16T09:20:30+05:30'),
             'Start', calendar_kind='REGULAR', elevated=False)
    target = datetime.fromisoformat('2026-10-16T09:20:30+05:30')
    first_wait = datetime.fromisoformat('2026-10-16T07:50:30+05:30')
    assert (target - first_wait).total_seconds() == 5400
    document = (ROOT / 'FRIDAY_OWNER_STATUS_2026-10-16.md').read_text(encoding='utf-8')
    assert 'before rejecting' in document and 'Never reset/retry' in document
