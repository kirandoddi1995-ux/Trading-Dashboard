"""Synthetic source metadata only; no hosted tree calls or private market data."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import storage_package_inventory as tool

SHA = 'a' * 40


def baseline(files=None):
    return tool.Baseline(SHA, files or {})


def write(root, name, raw):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def test_blob_identity_and_line_endings():
    raw = b'print(1)\n'
    assert tool.blob_sha(b'') == 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391'
    assert tool.status(raw, None) == 'LOCAL_ONLY'
    assert tool.status(raw, tool.blob_sha(raw)) == 'MATCHES_MAIN'
    assert tool.status(b'print(1)\r\n', tool.blob_sha(raw)) == 'MATCHES_MAIN_NEWLINES_ONLY'
    assert tool.status(raw, tool.blob_sha(b'print(1)\r\n')) == 'MATCHES_MAIN_NEWLINES_ONLY'
    assert tool.status(b'print(2)\n', tool.blob_sha(raw)) == 'MODIFIED_FROM_MAIN'


def test_baseline_valid_and_pinned():
    raw = json.dumps(dict(version='storage-source-baseline-v1', commit_sha=SHA,
                          files={'source.py': SHA})).encode()
    assert tool.load_baseline(raw) == baseline({'source.py': SHA})


@pytest.mark.parametrize('raw', [b'{}', b'[]', b'null', b'broken', b'\xff',
    b'{"version":1,"version":2}',
    json.dumps(dict(version='storage-source-baseline-v1', commit_sha='short', files={'x.py': SHA})).encode(),
    json.dumps(dict(version='storage-source-baseline-v1', commit_sha=SHA, files={'../x.py': SHA})).encode(),
    json.dumps(dict(version='storage-source-baseline-v1', commit_sha=SHA, files={'x.py': 1})).encode()])
def test_bad_baseline_rejected(raw):
    with pytest.raises(tool.InventoryError):
        tool.load_baseline(raw)


def test_baseline_bytes_are_bounded(monkeypatch):
    monkeypatch.setattr(tool, 'LIMIT', 2)
    with pytest.raises(tool.InventoryError, match='BASELINE_INVALID'):
        tool.load_baseline(b'longer')


@pytest.mark.parametrize('name', ['../private.py', '/private.py', 'C:/private.py',
    'tests\\test_x.py', './source.py', 'x//y.py', '.streamlit/secrets.toml',
    'token.json', 'bars.csv', 'Documents/TradingResearch/data.py', 'tests/helper.py'])
def test_private_or_ambiguous_paths_rejected(tmp_path, name):
    with pytest.raises(tool.InventoryError):
        tool.safe_path(tmp_path, name)


def test_fixed_inventory_ignores_private_subfolders_and_generated_files(tmp_path):
    write(tmp_path, 'source.py', b'print(1)\n')
    write(tmp_path, 'ledger_segments.py', b'VALUE=1\n')
    write(tmp_path, 'tests/test_ledger_segments.py', b'import ledger_segments\n')
    write(tmp_path, 'Documents/TradingResearch/bars.csv', b'never read')
    write(tmp_path, '.venv/private.py', b'never read')
    write(tmp_path, 'staged_capture_repair/private.py', b'never read')
    original = {p.relative_to(tmp_path).as_posix(): p.read_bytes()
                for p in tmp_path.rglob('*') if p.is_file()}
    items = tool.inventory(tmp_path, baseline({'source.py': tool.blob_sha(b'print(1)\n')}))
    assert [x['path'] for x in items] == ['ledger_segments.py', 'tests/test_ledger_segments.py']
    assert all(x['stage'] == 'P1_ORIGINALS_CATALOG' for x in items)
    assert original == {p.relative_to(tmp_path).as_posix(): p.read_bytes()
                        for p in tmp_path.rglob('*') if p.is_file()}


def test_missing_or_oversized_source_fails(tmp_path, monkeypatch):
    with pytest.raises(tool.InventoryError, match='MISSING'):
        tool.read_source(tmp_path, 'missing.py')
    write(tmp_path, 'source.py', b'large')
    monkeypatch.setattr(tool, 'LIMIT', 2)
    with pytest.raises(tool.InventoryError, match='SIZE_LIMIT'):
        tool.read_source(tmp_path, 'source.py')


def test_links_rejected_before_reads(tmp_path, monkeypatch):
    write(tmp_path, 'source.py', b'not read')
    original = Path.is_junction
    monkeypatch.setattr(Path, 'is_junction', lambda path: path.name == 'source.py' or original(path))
    with pytest.raises(tool.InventoryError, match='LINK_REJECTED'):
        tool.read_source(tmp_path, 'source.py')


def test_test_only_upload_requires_new_module(tmp_path):
    write(tmp_path, 'tests/test_feature.py', b'import feature\n')
    write(tmp_path, 'feature.py', b'VALUE=1\n')
    result = tool.check_package(tmp_path, baseline(), ['tests/test_feature.py'])
    assert result['status'] == 'BLOCKED'
    assert result['blockers'][0]['dependency'] == 'feature.py'
    result = tool.check_package(tmp_path, baseline(), ['tests/test_feature.py', 'feature.py'])
    assert result['status'] == 'PACKAGE_CHECK_PASSED_REQUIRES_REHEARSAL'
    assert result['approval_authority'] is False and result['hosted_changes'] == 0


def test_existing_main_dependency_only_accepted_when_local_source_matches(tmp_path):
    write(tmp_path, 'tests/test_feature.py', b'from feature import VALUE\n')
    write(tmp_path, 'feature.py', b'VALUE=1\r\n')
    pinned = baseline({'feature.py': tool.blob_sha(b'VALUE=1\n')})
    selected = ['tests/test_feature.py']
    assert not tool.check_package(tmp_path, pinned, selected)['blockers']
    write(tmp_path, 'feature.py', b'VALUE=2\n')
    assert tool.check_package(tmp_path, pinned, selected)['status'] == 'BLOCKED'


def test_dependency_checks_each_selected_module_not_only_test_seeds(tmp_path):
    write(tmp_path, 'one.py', b'import two\n')
    write(tmp_path, 'two.py', b'import three\n')
    write(tmp_path, 'three.py', b'VALUE=1\n')
    result = tool.check_package(tmp_path, baseline(), ['one.py', 'two.py'])
    assert result['blockers'] == [{'path': 'two.py', 'dependency': 'three.py',
                                  'code': 'DEPENDENCY_NOT_IN_PACKAGE'}]


def test_baseline_dependency_missing_locally_never_assumed_verified(tmp_path):
    write(tmp_path, 'one.py', b'import two\n')
    result = tool.check_package(tmp_path, baseline({'two.py': SHA}), ['one.py'])
    assert result['blockers'][0]['code'] == 'DEPENDENCY_UNAVAILABLE'


@pytest.mark.parametrize('present', [True, False])
def test_tool_baseline_is_a_required_resource_not_an_external_library(tmp_path, present):
    write(tmp_path, 'storage_package_inventory.py', b'VALUE=1\n')
    if present:
        write(tmp_path, tool.BASELINE, b'{}')
    result = tool.check_package(tmp_path, baseline(), ['storage_package_inventory.py'])
    assert result['status'] == 'BLOCKED'
    assert result['blockers'][0]['dependency'] == tool.BASELINE
    assert result['blockers'][0]['code'] == (
        'DEPENDENCY_NOT_IN_PACKAGE' if present else 'DEPENDENCY_UNAVAILABLE')


def test_sql_harness_companions_are_explicit_not_hidden_fixture_imports(tmp_path):
    write(tmp_path, 'tests/test_ledger_runtime_reader_sql.py', b'import json\n')
    for name in tool.MIGRATIONS:
        write(tmp_path, name, b'-- synthetic review-only fixture\n')
    selected = ['tests/test_ledger_runtime_reader_sql.py']
    result = tool.check_package(tmp_path, baseline(), selected)
    assert len(result['blockers']) == 3
    assert not tool.check_package(tmp_path, baseline(), selected + list(tool.MIGRATIONS))['blockers']


@pytest.mark.parametrize('members', [[], ['x.py', 'x.py']])
def test_empty_or_duplicate_package_rejected(tmp_path, members):
    with pytest.raises(tool.InventoryError, match='MEMBERS_INVALID'):
        tool.check_package(tmp_path, baseline(), members)


def test_import_discovery_does_not_execute_source():
    raw = b"raise RuntimeError('never executed')\ndef late():\n import future\nimport importlib\nimportlib.import_module('plugin')\n"
    assert tool.dependencies(raw) == {'future.py', 'importlib.py', 'plugin.py'}


@pytest.mark.parametrize('raw,code', [(b'from . import child', 'RELATIVE_IMPORT'),
    (b'__import__(variable)', 'DYNAMIC_IMPORT'), (b'invalid python!', 'PARSE_FAILED')])
def test_unsupported_discovery_fails_explicitly(raw, code):
    with pytest.raises(tool.InventoryError, match=code):
        tool.dependencies(raw)


def test_cli_inventory_and_package_are_read_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tool, '__file__', str(tmp_path / 'storage_package_inventory.py'))
    write(tmp_path, tool.BASELINE, json.dumps(dict(version='storage-source-baseline-v1',
        commit_sha=SHA, files={'source.py': SHA})).encode())
    write(tmp_path, 'source.py', b'VALUE=1\n')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert tool.main([]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'SOURCE_INVENTORY'
    assert tool.main(['--check-package', 'source.py']) == 0
    assert json.loads(capsys.readouterr().out)['approval_authority'] is False
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert tool.main(['--check-package', 'missing.py']) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'SOURCE_MISSING_OR_UNREADABLE'


def test_unknown_files_are_not_declared_obsolete():
    assert tool.stage('unknown.py') == 'UNCLASSIFIED_REVIEW'
    assert all(tool.stage(name) == 'P4_REVIEW_SQL_HOLD' for name in tool.MIGRATIONS)


def test_first_core_package_imports_without_unfinished_runtime_modules(tmp_path):
    root = Path(tool.__file__).resolve().parent
    pinned = tool.load_baseline(tool.read_source(root, tool.BASELINE))
    original = tool.read_source(root, 'evidence_ledger.py')
    assert tool.status(original, pinned.files['evidence_ledger.py']) in (
        'MATCHES_MAIN', 'MATCHES_MAIN_NEWLINES_ONLY')
    names = ['ledger_segments', 'cold_catalog', 'catalog_receipts', 'ledger_cold_store']
    for name in [*names, 'evidence_ledger']:
        shutil.copyfile(root / (name + '.py'), tmp_path / (name + '.py'))
    script = ("import importlib,pathlib,sys; root=pathlib.Path(sys.argv[1]); "
              "sys.path.insert(0,str(root)); names=sys.argv[2:]; "
              "modules=[importlib.import_module(n) for n in names]; "
              "assert all(pathlib.Path(m.__file__).parent==root for m in modules); "
              "assert 'production_repository' not in sys.modules; print('ISOLATED_CORE_IMPORT_PASS')")
    run = subprocess.run([sys.executable, '-I', '-c', script, str(tmp_path), *names],
                         capture_output=True, text=True, timeout=30, check=False)
    assert run.returncode == 0, 'ISOLATED_CORE_IMPORT_FAILED'
    assert run.stdout.strip() == 'ISOLATED_CORE_IMPORT_PASS'
