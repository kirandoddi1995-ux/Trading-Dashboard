import ast
import csv
from pathlib import Path

import operations_evidence_matrix as matrix


def test_every_concept_has_exact_existing_selector_or_explicit_no_proof() -> None:
    with Path('PROJECT_STATUS_LEDGER_2026-10-16.csv').open(encoding='utf8', newline='') as stream:
        concepts = {r['concept_or_task'] for r in csv.DictReader(stream)}
    assert concepts == set(matrix.TESTS)
    assert set(matrix.SCOPE) == concepts
    for selector in matrix.selectors():
        if selector:
            path, function = selector.split('::')
            names = {n.name for n in ast.parse(Path(path).read_text(encoding='utf8')).body
                     if isinstance(n, ast.FunctionDef)}
            assert function in names, selector


def test_junit_pass_skip_fail_and_absence_are_distinct(tmp_path: Path) -> None:
    file = tmp_path / 'synthetic.xml'
    file.write_text('''<testsuites><testsuite>
      <testcase classname="tests.test_forward_session_ops" name="test_report_append_and_alert_once"/>
      <testcase classname="tests.test_forward_ops_plan" name="test_disabled_date_pinned_and_versioned_audit"><skipped/></testcase>
      <testcase classname="tests.test_storage_alert_delivery" name="test_acceptance_is_not_owner_receipt_or_commissioning"><failure/></testcase>
    </testsuite></testsuites>''',encoding='utf8')
    result = matrix.results(file)
    assert result['Local alert notification']['passed'] == 1
    assert result['Dated audit task']['status'] == 'SKIPPED_ONLY'
    assert result['Independent alert delivery']['status'] == 'FAILED'
    assert result['Universe shadow deduplication']['status'] == 'NOT_RUN'
    assert result['Full Supabase database restore drill']['status'] == 'OWNER_OR_NATIVE_EVIDENCE_REQUIRED'
    assert all(not row['commissioning_verified'] for row in result.values())
    assert all(row['what_this_tests'] and row['does_not_prove'] for row in result.values())
