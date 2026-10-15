"""Deterministic synthetic public trees and Git responses; no real Git or network."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path
import subprocess
from typing import TypedDict, cast

import pytest

import daily_owner_upload_check as check


ANCHOR = '1251530731cce5b75fad8601567b9320d07b710d'
BASE = 'b' * 40
CONTROL = 'DAILY_OWNER_UPLOAD_2026-10-15.json'
DAILY = (
    'forward_daily_contract.py', 'forward_daily_owner.ps1',
    'tests/test_forward_daily_contract.py', 'tests/test_forward_daily_owner.py',
    'project_conductor.py', 'tests/test_project_conductor.py',
    'PROJECT_WORKING_AGREEMENT.md', 'TECHNOLOGY_RADAR_2026-10-15.md',
    'FRIDAY_CAPTURE_2026-10-16.md', 'daily_owner_upload_check.py',
    'tests/test_daily_owner_upload_check.py', 'DAILY_OWNER_UPLOAD_2026-10-15.md', CONTROL,
)
PRIOR = (
    'forward_morning_route.py', 'tests/test_forward_morning_route.py',
    'forward_evidence_preserve.py', 'tests/test_forward_evidence_preserve.py',
    'storage_consistent_cut_export.py', 'tests/test_storage_consistent_cut_export.py',
    'storage_cut_native_check.py', 'tests/test_storage_cut_native_check.py',
    'research_forward_cohort.py', 'tests/test_research_forward_cohort.py',
    'programme_agent_team.py', 'tests/test_programme_agent_team.py',
    'MORNING_2026-10-15.md', 'OWNER_CAPTURE_2026-10-15.md',
    'OVERNIGHT_CONTINUITY_2026-10-15.md', 'AGENT_TEAM_2026-10-15.md',
    'continuity_upload_check.py', 'tests/test_continuity_upload_check.py',
    'CONTINUITY_UPLOAD_2026-10-15.md', 'CONTINUITY_UPLOAD_2026-10-15.json',
)


class Pin(TypedDict):
    path: str
    sha256_lf: str | None


class Plan(TypedDict):
    version: str
    anchor: str
    files: list[Pin]
    prerequisites: list[Pin]


def sha(raw: bytes) -> str:
    """Independent expected LF hash, without using the function under test."""
    return hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()


def prerequisite_commitment(pins: list[Pin]) -> str:
    canonical = '\n'.join(f'{pin["path"]}:{pin["sha256_lf"]}'
                          for pin in sorted(pins, key=lambda pin: pin['path']))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def test_public_frozen_prerequisite_commitment_constant() -> None:
    # Deliberately has no synthetic-tree fixture: assert the real public constant.
    assert check.PREREQUISITE_SET_SHA256 == (
        '3294e8b01b649fc6b6caf48bd4816196ff2e2e4616600e123e56a6b056fe676c')


def test_commitment_matches_unchanged_public_continuity_manifest_and_bytes() -> None:
    root = Path(__file__).resolve().parents[1]
    original = json.loads((root / 'CONTINUITY_UPLOAD_2026-10-15.json').read_text())
    pins: list[Pin] = []
    assert original['base'] == ANCHOR
    assert {row['destination'] for row in original['files']} == set(PRIOR)
    for row in original['files']:
        name = row['destination']
        actual = sha((root / name).read_bytes())
        if name != 'CONTINUITY_UPLOAD_2026-10-15.json':
            assert actual == row['sha256_lf'], name
        else:
            assert row['sha256_lf'] is None
        pins.append({'path': name, 'sha256_lf': actual})
    assert prerequisite_commitment(pins) == check.PREREQUISITE_SET_SHA256


@dataclass
class Tree:
    root: Path
    plan: Plan
    blobs: dict[str, bytes]
    oids: dict[str, str]
    baseline: list[str] = field(default_factory=lambda: [f'A\t{n}' for n in PRIOR])
    staged: list[str] = field(default_factory=lambda: [f'A\t{n}' for n in DAILY])
    head: str = BASE
    base: str = BASE
    top: Path | None = None
    unstaged: str = ''
    untracked: str = ''
    modes: dict[str, str] = field(default_factory=dict)
    stages: dict[str, str] = field(default_factory=dict)
    sizes: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)
    blob_calls: list[str] = field(default_factory=list)

    def write_plan(self, plan: object | None = None) -> None:
        raw = json.dumps(self.plan if plan is None else plan).encode('utf-8')
        (self.root / CONTROL).write_bytes(raw)
        self.blobs[CONTROL] = raw

    def git(self, root: Path, *args: str) -> str:
        assert root == self.root
        self.calls.append(args)
        if args == ('rev-parse', 'HEAD'):
            return self.head
        if args == ('rev-parse', '--show-toplevel'):
            return str(self.top if self.top is not None else self.root)
        if args == ('merge-base', '--is-ancestor', ANCHOR, self.base):
            return ''
        if args == ('diff', '--name-status', '--no-renames', ANCHOR, self.base, '--'):
            return '\n'.join(self.baseline)
        if args == ('diff', '--name-only', '--'):
            return self.unstaged
        if args == ('ls-files', '--others', '--exclude-standard'):
            return self.untracked
        if args == ('diff', '--cached', '--name-status', '--no-renames', self.base, '--'):
            return '\n'.join(self.staged)
        if len(args) == 4 and args[:3] == ('ls-files', '--stage', '--'):
            name = args[3]
            assert name in self.oids
            return f'{self.modes.get(name, "100644")} {self.oids[name]} {self.stages.get(name, "0")}\t{name}'
        if len(args) == 3 and args[:2] == ('cat-file', '-s'):
            names = [name for name, oid in self.oids.items() if oid == args[2]]
            assert len(names) == 1
            name = names[0]
            return self.sizes.get(name, str(len(self.blobs[name])))
        raise AssertionError(f'Unexpected Git arguments: {args!r}')

    def run(self, args: list[str], *, check: bool, stdout: int, stderr: int,
            timeout: int) -> subprocess.CompletedProcess[bytes]:
        assert check is True
        assert (stdout, stderr, timeout) == (subprocess.PIPE, subprocess.DEVNULL, 30)
        assert args[:5] == ['git', '-C', str(self.root), 'cat-file', 'blob']
        assert len(args) == 6
        names = [name for name, oid in self.oids.items() if oid == args[5]]
        assert len(names) == 1
        assert self.calls[-1] == ('cat-file', '-s', args[5])
        self.blob_calls.append(names[0])
        return subprocess.CompletedProcess(args, 0, stdout=self.blobs[names[0]])


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tree:
    root = tmp_path.resolve()
    blobs = {name: f'# synthetic public file: {name}\r\n'.encode('ascii')
             for name in (*PRIOR, *DAILY) if name != CONTROL}
    for name, raw in blobs.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    policy = b'{"synthetic_policy":true}\n'
    (root / 'resilience_policy.json').write_bytes(policy)
    (root / 'resilience_policy.sha256').write_bytes(hashlib.sha256(policy).hexdigest().encode('ascii') + b'\n')
    plan: Plan = {
        'version': 'daily-owner-v1', 'anchor': ANCHOR,
        'files': [{'path': name, 'sha256_lf': None if name == CONTROL else sha(blobs[name])}
                  for name in DAILY],
        'prerequisites': [{'path': name, 'sha256_lf': sha(blobs[name])} for name in PRIOR],
    }
    result = Tree(root, plan, blobs,
                  {name: f'{i:040x}' for i, name in enumerate((*PRIOR, *DAILY), 1)})
    # Bind once to the original synthetic twenty. write_plan never refreshes it.
    monkeypatch.setattr(check, 'PREREQUISITE_SET_SHA256',
                        prerequisite_commitment(plan['prerequisites']))
    result.write_plan()
    monkeypatch.setattr(check, 'git', result.git)
    monkeypatch.setattr(subprocess, 'run', result.run)
    return result


@pytest.fixture
def combined_tree(tree: Tree) -> Tree:
    tree.base = ANCHOR
    tree.head = ANCHOR
    tree.baseline.clear()
    tree.staged = [f'A\t{name}' for name in (*PRIOR, *DAILY)]
    return tree


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('name', PRIOR)
def test_new_manifest_cannot_rebind_any_frozen_prerequisite(tree: Tree, name: str,
                                                          combined: bool) -> None:
    if combined:
        tree.base = tree.head = ANCHOR
        tree.baseline.clear()
        tree.staged = [f'A\t{path}' for path in (*PRIOR, *DAILY)]
    frozen = check.PREREQUISITE_SET_SHA256
    for pin in tree.plan['prerequisites']:
        if pin['path'] == name:
            pin['sha256_lf'] = '0' * 64
    tree.write_plan()
    assert prerequisite_commitment(tree.plan['prerequisites']) != frozen
    assert check.PREREQUISITE_SET_SHA256 == frozen
    with pytest.raises(ValueError, match='^FROZEN_PREREQUISITE_HASH_REBINDING_REJECTED$'):
        check.verify(tree.root, tree.base, combined=combined)
    assert not tree.blob_calls
    assert not any(args[0] == 'diff' for args in tree.calls)


@pytest.mark.parametrize('combined', [False, True])
def test_rebinding_cannot_be_hidden_by_matching_worktree_and_index(tree: Tree,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], combined: bool) -> None:
    if combined:
        tree.base = tree.head = ANCHOR
        tree.baseline.clear()
        tree.staged = [f'A\t{path}' for path in (*PRIOR, *DAILY)]
    frozen = check.PREREQUISITE_SET_SHA256
    changed = b'# synthetic-secret-do-not-print: replaced frozen prerequisite\n'
    (tree.root / PRIOR[0]).write_bytes(changed)
    tree.blobs[PRIOR[0]] = changed
    tree.plan['prerequisites'][0]['sha256_lf'] = sha(changed)
    tree.write_plan()
    manifest = (tree.root / CONTROL).read_bytes()
    with pytest.raises(ValueError, match='^FROZEN_PREREQUISITE_HASH_REBINDING_REJECTED$'):
        check.verify(tree.root, tree.base, combined=combined)
    monkeypatch.chdir(tree.root)
    assert check.main(['--base', tree.base, *(['--combined'] if combined else [])]) == 2
    output = capsys.readouterr()
    assert output.err == ''
    assert 'synthetic-secret-do-not-print' not in output.out and str(tree.root) not in output.out
    assert json.loads(output.out) == {
        'status': 'BLOCKED', 'rule': 'FROZEN_PREREQUISITE_HASH_REBINDING_REJECTED',
        'hosted_changes': 0, 'raw_error_printed': False}
    assert (tree.root / CONTROL).read_bytes() == manifest
    assert check.PREREQUISITE_SET_SHA256 == frozen
    assert not tree.blob_calls


@pytest.mark.parametrize('combined', [False, True])
def test_frozen_commitment_uses_sorted_lines_without_final_lf(tree: Tree, combined: bool) -> None:
    if combined:
        tree.base = tree.head = ANCHOR
        tree.baseline.clear()
        tree.staged = [f'A\t{path}' for path in (*PRIOR, *DAILY)]
    frozen = check.PREREQUISITE_SET_SHA256
    tree.plan['prerequisites'].reverse()
    tree.write_plan()
    assert prerequisite_commitment(tree.plan['prerequisites']) == frozen
    assert check.verify(tree.root, tree.base, combined=combined) == []


def test_combined_exact_thirty_three_on_unchanged_anchor(combined_tree: Tree) -> None:
    tree = combined_tree
    manifest_before = (tree.root / CONTROL).read_bytes()
    assert check.verify(tree.root, ANCHOR, combined=True) == []
    assert len(tree.staged) == 33
    assert tree.calls[:4] == [
        ('rev-parse', 'HEAD'), ('rev-parse', '--show-toplevel'),
        ('merge-base', '--is-ancestor', ANCHOR, ANCHOR),
        ('diff', '--name-status', '--no-renames', ANCHOR, ANCHOR, '--'),
    ]
    assert ('diff', '--cached', '--name-status', '--no-renames', ANCHOR, '--') in tree.calls
    assert tree.blob_calls == [*PRIOR, *DAILY]
    assert (tree.root / CONTROL).read_bytes() == manifest_before
    assert set(tree.plan) == {'version', 'anchor', 'files', 'prerequisites'}


@pytest.mark.parametrize('base,head', [(BASE, BASE), (BASE, ANCHOR), (ANCHOR, BASE),
    ('HEAD', ANCHOR), ('', ANCHOR), (ANCHOR.upper(), ANCHOR)])
def test_combined_requires_both_base_and_head_equal_anchor(combined_tree: Tree,
                                                         base: str, head: str) -> None:
    combined_tree.head = head
    with pytest.raises(ValueError, match='^BASE_NOT_CURRENT_HEAD$'):
        check.verify(combined_tree.root, base, combined=True)
    assert not combined_tree.blob_calls


@pytest.mark.parametrize('value', [None, 0, 1, '', 'false', 'true', [], {}])
def test_combined_flag_rejects_nonbool_types(tree: Tree, value: object) -> None:
    # cast permits an intentional invalid runtime input without silencing type checking.
    with pytest.raises(ValueError, match='^BASE_NOT_CURRENT_HEAD$'):
        check.verify(tree.root, BASE, combined=cast(bool, value))
    assert tree.calls == []


@pytest.mark.parametrize('delta', [f'A\t{PRIOR[0]}', 'M\ttracked.py', 'D\ttracked.py',
                                  'R100\told.py\tnew.py', 'all-prior'])
def test_combined_requires_completely_empty_anchor_delta(combined_tree: Tree, delta: str) -> None:
    tree = combined_tree
    tree.baseline = [f'A\t{name}' for name in PRIOR] if delta == 'all-prior' else [delta]
    with pytest.raises(ValueError, match='^BASE_TREE_NOT_ANCHOR_PLUS_FROZEN_CONTINUITY$'):
        check.verify(tree.root, ANCHOR, combined=True)
    assert not tree.blob_calls


@pytest.mark.parametrize('mutation', ['missing-twenty', 'missing-prior', 'missing-daily',
                                    'extra', 'modified', 'deleted', 'renamed'])
def test_combined_requires_exact_thirty_three_staged_additions(combined_tree: Tree,
                                                             mutation: str) -> None:
    tree = combined_tree
    if mutation == 'missing-twenty':
        tree.staged = [f'A\t{name}' for name in DAILY]
    elif mutation == 'missing-prior':
        tree.staged.remove(f'A\t{PRIOR[0]}')
    elif mutation == 'missing-daily':
        tree.staged.remove(f'A\t{DAILY[0]}')
    elif mutation == 'extra':
        tree.staged.append('A\tunrelated.py')
    elif mutation == 'modified':
        tree.staged[0] = f'M\t{PRIOR[0]}'
    elif mutation == 'deleted':
        tree.staged[0] = f'D\t{PRIOR[0]}'
    else:
        tree.staged[0] = f'R100\told.py\t{PRIOR[0]}'
    with pytest.raises(ValueError, match='^EXACT_STAGED_ADDITIONS_REQUIRED$'):
        check.verify(tree.root, ANCHOR, combined=True)
    assert not tree.blob_calls


def test_default_mode_does_not_implicitly_accept_combined_tree(combined_tree: Tree) -> None:
    with pytest.raises(ValueError, match='^BASE_TREE_NOT_ANCHOR_PLUS_FROZEN_CONTINUITY$'):
        check.verify(combined_tree.root, ANCHOR)


@pytest.mark.parametrize('name', [PRIOR[0], DAILY[0]])
def test_combined_keeps_both_packages_hash_pins(combined_tree: Tree, name: str) -> None:
    tree = combined_tree
    expected = sha(tree.blobs[name])
    manifest_before = (tree.root / CONTROL).read_bytes()
    changed = b'# synthetic combined changed file\n'
    (tree.root / name).write_bytes(changed)
    tree.blobs[name] = changed
    assert check.verify(tree.root, ANCHOR, combined=True) == [
        {'path': name, 'expected': expected, 'actual': sha(changed)}]
    assert (tree.root / CONTROL).read_bytes() == manifest_before


@pytest.mark.parametrize('name', [PRIOR[0], DAILY[0], CONTROL])
def test_combined_keeps_index_blob_binding(combined_tree: Tree, name: str) -> None:
    tree = combined_tree
    working = tree.blobs[name]
    tree.blobs[name] = b'# synthetic combined staged tamper\n'
    assert check.verify(tree.root, ANCHOR, combined=True) == [
        {'path': name, 'expected': sha(tree.blobs[name]), 'actual': sha(working)}]


@pytest.mark.parametrize('problem,rule', [
    ('mode', 'REGULAR_STAGE_ZERO_BLOB_REQUIRED'), ('stage', 'REGULAR_STAGE_ZERO_BLOB_REQUIRED'),
    ('oversize', 'STAGED_BLOB_TOO_LARGE'), ('malformed', 'STAGED_BLOB_TOO_LARGE'),
    ('mismatch', 'STAGED_BLOB_SIZE_MISMATCH'), ('policy', 'APPROVED_POLICY_BYTES_INVALID'),
    ('dirty', 'STAGE_EXACT_PACKAGE_THEN_CHECK'), ('untracked', 'STAGE_EXACT_PACKAGE_THEN_CHECK'),
    ('extra-control-field', 'CONTROL_INVALID'), ('wrong-prior', 'EXACT_PREREQUISITES_REQUIRED'),
])
def test_combined_preserves_shared_guards_and_safe_cli(combined_tree: Tree,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], problem: str, rule: str) -> None:
    tree = combined_tree
    secret = 'synthetic-secret-do-not-print'
    if problem == 'mode':
        tree.modes[PRIOR[0]] = '120000'
    elif problem == 'stage':
        tree.stages[PRIOR[0]] = '2'
    elif problem == 'oversize':
        tree.sizes[PRIOR[0]] = str(check.LIMIT + 1)
    elif problem == 'malformed':
        tree.sizes[PRIOR[0]] = secret
    elif problem == 'mismatch':
        tree.sizes[PRIOR[0]] = str(len(tree.blobs[PRIOR[0]]) + 1)
    elif problem == 'policy':
        (tree.root / 'resilience_policy.json').write_bytes(b'{}\n')
    elif problem == 'dirty':
        tree.unstaged = secret
    elif problem == 'untracked':
        tree.untracked = secret
    elif problem == 'extra-control-field':
        plan: dict[str, object] = dict(tree.plan)
        plan['combined'] = True
        tree.write_plan(plan)
    else:
        tree.plan['prerequisites'][0]['path'] = 'replacement.py'
        tree.write_plan()
    with pytest.raises(ValueError, match=f'^{rule}$'):
        check.verify(tree.root, ANCHOR, combined=True)
    monkeypatch.chdir(tree.root)
    assert check.main(['--base', ANCHOR, '--combined']) == 2
    output = capsys.readouterr()
    assert output.err == ''
    assert secret not in output.out and str(tree.root) not in output.out
    assert json.loads(output.out) == {
        'status': 'BLOCKED', 'rule': rule, 'hosted_changes': 0, 'raw_error_printed': False}


def test_main_combined_success(combined_tree: Tree, monkeypatch: pytest.MonkeyPatch,
                               capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(combined_tree.root)
    assert check.main(['--base', ANCHOR, '--combined']) == 0
    output = capsys.readouterr()
    assert output.err == ''
    assert json.loads(output.out) == {
        'status': 'DAILY_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI',
        'failures': [], 'hosted_changes': 0}


@pytest.mark.parametrize('combined', [False, True])
def test_cli_forwards_explicit_combined_keyword(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], combined: bool) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[tuple[Path, str, bool]] = []

    def verify(root: Path, base: str, *, combined: bool = False) -> list[dict[str, str]]:
        calls.append((root, base, combined))
        return []

    monkeypatch.setattr(check, 'verify', verify)
    base = ANCHOR if combined else BASE
    assert check.main(['--base', base, *(['--combined'] if combined else [])]) == 0
    assert calls == [(tmp_path, base, combined)]
    assert json.loads(capsys.readouterr().out)['failures'] == []


def test_exact_frozen_contract_and_complete_success(tree: Tree) -> None:
    assert check.ANCHOR == ANCHOR
    assert check.CONTROL == CONTROL
    assert check.FILES == DAILY
    assert len(DAILY) == 13 and len(PRIOR) == 20
    assert check.verify(tree.root, BASE) == []
    assert tree.calls[:4] == [
        ('rev-parse', 'HEAD'), ('rev-parse', '--show-toplevel'),
        ('merge-base', '--is-ancestor', ANCHOR, BASE),
        ('diff', '--name-status', '--no-renames', ANCHOR, BASE, '--'),
    ]
    assert tree.blob_calls == [*PRIOR, *DAILY]


@pytest.mark.parametrize('value', [None, {}, (), 'pins', [None], [[]], [{}],
    [{'path': 'a.py'}], [{'path': 'a.py', 'sha256_lf': 'a' * 64, 'extra': 1}],
    [{'path': 1, 'sha256_lf': 'a' * 64}], [{'path': 'a.py', 'sha256_lf': None}],
    [{'path': 'a.py', 'sha256_lf': True}], [{'path': 'a.py', 'sha256_lf': 42}],
    [{'path': 'a.py', 'sha256_lf': 'A' * 64}], [{'path': 'a.py', 'sha256_lf': 'a' * 63}],
    [{'path': 'a.py', 'sha256_lf': 'a' * 65}], [{'path': 'a.py', 'sha256_lf': 'g' * 64}],
    [{'path': 'a.py', 'sha256_lf': 'a' * 64 + '\n'}],
    [{'path': 'a.py', 'sha256_lf': 'a' * 64}, {'path': 'a.py', 'sha256_lf': 'b' * 64}],
    [{'path': CONTROL, 'sha256_lf': None}, {'path': CONTROL, 'sha256_lf': None}],
])
def test_entries_reject_malformed_and_duplicate_pins(value: object) -> None:
    with pytest.raises(ValueError, match='^CONTROL_PINS_INVALID$'):
        check.entries(value)


def test_entries_accept_only_control_as_null_and_valid_hashes() -> None:
    assert check.entries([{'path': CONTROL, 'sha256_lf': None},
                          {'path': 'public.py', 'sha256_lf': 'a' * 64}]) == {
                              CONTROL: None, 'public.py': 'a' * 64}


@pytest.mark.parametrize('name', ['', '.', '..', '../private', 'a/../private', '/absolute',
    'C:/private', 'C:private', 'a\\private', '//host/share', './public', 'a//b',
    'a/', '.env', 'a/.private', 'a/./b'])
def test_source_rejects_nonpublic_paths(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match='^PUBLIC_PATH_INVALID$'):
        check.source(tmp_path, name)


@pytest.mark.parametrize('kind', ['is_symlink', 'is_junction'])
@pytest.mark.parametrize('location', ['ancestor', 'root', 'directory', 'file'])
def test_source_rejects_links_before_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                           kind: str, location: str) -> None:
    root = tmp_path.resolve()
    target = root / 'public' / 'file.py'
    target.parent.mkdir()
    target.write_bytes(b'public\n')
    linked = {'ancestor': root.parent, 'root': root,
              'directory': target.parent, 'file': target}[location]

    def is_link(path: Path) -> bool:
        return path == linked

    def forbidden_open(path: Path, *args: object, **kwargs: object) -> io.BytesIO:
        raise AssertionError('A linked source must never be opened')

    monkeypatch.setattr(Path, kind, is_link)
    monkeypatch.setattr(Path, 'open', forbidden_open)
    with pytest.raises(ValueError, match='^PUBLIC_SOURCE_LINK_REJECTED$'):
        check.source(root, 'public/file.py')


def test_source_missing_directory_and_size_bound(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='^PUBLIC_SOURCE_MISSING_OR_TOO_LARGE$'):
        check.source(tmp_path, 'missing.py')
    (tmp_path / 'directory').mkdir()
    with pytest.raises(ValueError, match='^PUBLIC_SOURCE_MISSING_OR_TOO_LARGE$'):
        check.source(tmp_path, 'directory')
    target = tmp_path / 'bounded.py'
    target.write_bytes(b'x' * check.LIMIT)
    assert check.source(tmp_path, target.name) == b'x' * check.LIMIT
    target.write_bytes(b'x' * (check.LIMIT + 1))
    with pytest.raises(ValueError, match='^PUBLIC_SOURCE_MISSING_OR_TOO_LARGE$'):
        check.source(tmp_path, target.name)


def test_source_read_remains_bounded_if_file_grows(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / 'growing.py'
    target.write_bytes(b'x')
    reads: list[int | None] = []

    class GrowingStream(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            reads.append(size)
            return super().read(size)

    def growing_open(path: Path, mode: str) -> GrowingStream:
        assert path == target and mode == 'rb'
        return GrowingStream(b'x' * (check.LIMIT + 2))

    monkeypatch.setattr(Path, 'open', growing_open)
    with pytest.raises(ValueError, match='^PUBLIC_SOURCE_MISSING_OR_TOO_LARGE$'):
        check.source(tmp_path, target.name)
    assert reads == [check.LIMIT + 1]


@pytest.mark.parametrize('base', ['', 'HEAD', 'b' * 39, 'b' * 41, 'B' * 40, BASE + '\n', 'c' * 40])
def test_base_must_be_full_current_head(tree: Tree, base: str) -> None:
    with pytest.raises(ValueError, match='^BASE_NOT_CURRENT_HEAD$'):
        check.verify(tree.root, base)
    assert not tree.blob_calls


def test_clone_root_required(tree: Tree) -> None:
    tree.top = tree.root.parent
    with pytest.raises(ValueError, match='^CLONE_ROOT_REQUIRED$'):
        check.verify(tree.root, BASE)


def test_anchor_ancestry_failure_propagates(tree: Tree, monkeypatch: pytest.MonkeyPatch) -> None:
    def git(root: Path, *args: str) -> str:
        if args == ('merge-base', '--is-ancestor', ANCHOR, BASE):
            raise subprocess.CalledProcessError(1, ['git', *args])
        return tree.git(root, *args)

    monkeypatch.setattr(check, 'git', git)
    with pytest.raises(subprocess.CalledProcessError):
        check.verify(tree.root, BASE)


@pytest.mark.parametrize('mutation', ['empty', 'missing', 'extra', 'modified', 'deleted',
                                    'renamed', 'wrong-addition', 'daily-already-present'])
def test_base_requires_complete_twenty_additions_only(tree: Tree, mutation: str) -> None:
    if mutation == 'empty':
        tree.baseline.clear()
    elif mutation == 'missing':
        tree.baseline.pop()
    elif mutation == 'extra':
        tree.baseline.append('A\tunrelated.py')
    elif mutation in {'modified', 'deleted'}:
        tree.baseline[0] = ('M' if mutation == 'modified' else 'D') + '\t' + PRIOR[0]
    elif mutation == 'renamed':
        tree.baseline[0] = f'R100\told.py\t{PRIOR[0]}'
    elif mutation == 'wrong-addition':
        tree.baseline[0] = 'A\treplacement.py'
    else:
        tree.baseline.append(f'A\t{DAILY[0]}')
    with pytest.raises(ValueError, match='^BASE_TREE_NOT_ANCHOR_PLUS_FROZEN_CONTINUITY$'):
        check.verify(tree.root, BASE)
    assert not tree.blob_calls


@pytest.mark.parametrize('mutation', ['empty', 'missing', 'extra', 'modified', 'deleted',
                                    'renamed', 'prerequisite', 'wrong-addition'])
def test_stage_requires_exact_thirteen_additions(tree: Tree, mutation: str) -> None:
    if mutation == 'empty':
        tree.staged.clear()
    elif mutation == 'missing':
        tree.staged.pop()
    elif mutation == 'extra':
        tree.staged.append('A\tunrelated.py')
    elif mutation in {'modified', 'deleted'}:
        tree.staged[0] = ('M' if mutation == 'modified' else 'D') + '\t' + DAILY[0]
    elif mutation == 'renamed':
        tree.staged[0] = f'R100\told.py\t{DAILY[0]}'
    elif mutation == 'prerequisite':
        tree.staged.append(f'M\t{PRIOR[0]}')
    else:
        tree.staged[0] = 'A\treplacement.py'
    with pytest.raises(ValueError, match='^EXACT_STAGED_ADDITIONS_REQUIRED$'):
        check.verify(tree.root, BASE)
    assert not tree.blob_calls


@pytest.mark.parametrize('attribute', ['unstaged', 'untracked'])
def test_dirty_tree_blocks(tree: Tree, attribute: str) -> None:
    setattr(tree, attribute, 'synthetic-extra.py')
    with pytest.raises(ValueError, match='^STAGE_EXACT_PACKAGE_THEN_CHECK$'):
        check.verify(tree.root, BASE)


@pytest.mark.parametrize('mutation,rule', [
    ('extra', 'CONTROL_INVALID'), ('missing', 'CONTROL_INVALID'),
    ('version', 'CONTROL_INVALID'), ('anchor', 'CONTROL_INVALID'),
    ('not-object', 'CONTROL_INVALID'), ('missing-file', 'EXACT_PACKAGE_REQUIRED'),
    ('extra-file', 'EXACT_PACKAGE_REQUIRED'), ('self-hash', 'EXACT_PACKAGE_REQUIRED'),
    ('missing-prior', 'EXACT_PACKAGE_REQUIRED'), ('extra-prior', 'EXACT_PACKAGE_REQUIRED'),
    ('overlap', 'EXACT_PACKAGE_REQUIRED'), ('wrong-prior', 'EXACT_PREREQUISITES_REQUIRED'),
    ('traversal', 'EXACT_PACKAGE_REQUIRED'), ('null-prior', 'CONTROL_PINS_INVALID'),
    ('duplicate-pin', 'CONTROL_PINS_INVALID'),
])
def test_control_cannot_loosen_package_or_prerequisites(tree: Tree, mutation: str, rule: str) -> None:
    plan: dict[str, object] = dict(tree.plan)
    if mutation == 'extra':
        plan['unknown'] = True
    elif mutation == 'missing':
        del plan['anchor']
    elif mutation in {'version', 'anchor'}:
        plan[mutation] = 'unapproved'
    elif mutation == 'not-object':
        tree.write_plan([])
    elif mutation == 'missing-file':
        tree.plan['files'].pop(0)
    elif mutation == 'extra-file':
        tree.plan['files'].append({'path': 'extra.py', 'sha256_lf': 'a' * 64})
    elif mutation == 'self-hash':
        tree.plan['files'][-1]['sha256_lf'] = 'a' * 64
    elif mutation == 'missing-prior':
        tree.plan['prerequisites'].pop()
    elif mutation == 'extra-prior':
        tree.plan['prerequisites'].append({'path': 'extra.py', 'sha256_lf': 'a' * 64})
    elif mutation == 'overlap':
        tree.plan['prerequisites'][0] = tree.plan['files'][0]
    elif mutation == 'wrong-prior':
        tree.plan['prerequisites'][0]['path'] = 'replacement.py'
    elif mutation == 'traversal':
        tree.plan['files'][0]['path'] = '../private.py'
    elif mutation == 'null-prior':
        tree.plan['prerequisites'][0]['sha256_lf'] = None
    else:
        tree.plan['files'][0] = tree.plan['files'][1]
    if mutation != 'not-object':
        tree.write_plan(plan)
    with pytest.raises(ValueError, match=f'^{rule}$'):
        check.verify(tree.root, BASE)


@pytest.mark.parametrize('raw,rule', [
    (b'{"anchor":1,"anchor":2}', 'DUPLICATE_CONTROL_FIELD'),
    (b'{"files":[{"path":"a","path":"b"}]}', 'DUPLICATE_CONTROL_FIELD'),
    (b'{"extra":NaN}', 'CONTROL_CONSTANT_INVALID'),
    (b'{"extra":Infinity}', 'CONTROL_CONSTANT_INVALID'),
    (b'{"extra":-Infinity}', 'CONTROL_CONSTANT_INVALID'),
])
def test_json_duplicate_fields_and_nonfinite_constants_block(tree: Tree, raw: bytes, rule: str) -> None:
    (tree.root / CONTROL).write_bytes(raw)
    with pytest.raises(ValueError, match=f'^{rule}$'):
        check.verify(tree.root, BASE)


@pytest.mark.parametrize('name', [PRIOR[0], DAILY[0]])
def test_changed_pin_reports_exact_path_expected_actual(tree: Tree, name: str) -> None:
    old = tree.blobs[name]
    changed = b'# synthetic changed public content\n'
    (tree.root / name).write_bytes(changed)
    tree.blobs[name] = changed
    assert check.verify(tree.root, BASE) == [
        {'path': name, 'expected': sha(old), 'actual': sha(changed)}]


@pytest.mark.parametrize('name', [PRIOR[0], DAILY[0], CONTROL])
def test_staged_blob_tamper_including_self_null_control(tree: Tree, name: str) -> None:
    working = tree.blobs[name]
    tree.blobs[name] = b'# different synthetic staged bytes\n'
    assert check.verify(tree.root, BASE) == [
        {'path': name, 'expected': sha(tree.blobs[name]), 'actual': sha(working)}]


@pytest.mark.parametrize('name', [PRIOR[0], DAILY[0], CONTROL])
@pytest.mark.parametrize('size', ['', 'garbage', '-1', '+1', '1.0', '1e2', ' 1', '1 ',
    '1\n', '1\x00', '\u0661', '\uff11', '00000000000', '9' * 100, str(check.LIMIT + 1), '9999999999'])
def test_invalid_or_oversize_blob_size_blocks_before_read(tree: Tree, name: str, size: str) -> None:
    tree.sizes[name] = size
    with pytest.raises(ValueError, match='^STAGED_BLOB_TOO_LARGE$'):
        check.verify(tree.root, BASE)
    order = [*PRIOR, *DAILY]
    assert tree.blob_calls == order[:order.index(name)]
    assert tree.calls[-1] == ('cat-file', '-s', tree.oids[name])


@pytest.mark.parametrize('name', [PRIOR[0], DAILY[0], CONTROL])
@pytest.mark.parametrize('delta', [-1, 1])
def test_blob_read_length_must_match_announced_size(tree: Tree, name: str, delta: int) -> None:
    tree.sizes[name] = str(len(tree.blobs[name]) + delta)
    with pytest.raises(ValueError, match='^STAGED_BLOB_SIZE_MISMATCH$'):
        check.verify(tree.root, BASE)
    order = [*PRIOR, *DAILY]
    assert tree.blob_calls == order[:order.index(name) + 1]


def test_blob_size_counts_raw_bytes_before_lf_normalization(tree: Tree) -> None:
    name = PRIOR[0]
    assert b'\r\n' in tree.blobs[name]
    tree.sizes[name] = str(len(tree.blobs[name].replace(b'\r\n', b'\n')))
    with pytest.raises(ValueError, match='^STAGED_BLOB_SIZE_MISMATCH$'):
        check.verify(tree.root, BASE)
    assert tree.blob_calls == [name]


def test_blob_read_exceeding_limit_despite_small_declared_size_blocks(tree: Tree) -> None:
    name = PRIOR[0]
    tree.sizes[name] = '1'
    tree.blobs[name] = b'x' * (check.LIMIT + 1)
    with pytest.raises(ValueError, match='^STAGED_BLOB_SIZE_MISMATCH$'):
        check.verify(tree.root, BASE)
    assert tree.blob_calls == [name]


@pytest.mark.parametrize('length', [0, check.LIMIT])
def test_blob_size_accepts_inclusive_bounds(tree: Tree, length: int) -> None:
    name = DAILY[0]
    raw = b'x' * length
    (tree.root / name).write_bytes(raw)
    tree.blobs[name] = raw
    tree.plan['files'][0]['sha256_lf'] = sha(raw)
    tree.write_plan()
    assert check.verify(tree.root, BASE) == []
    assert ('cat-file', '-s', tree.oids[name]) in tree.calls


@pytest.mark.parametrize('name', [PRIOR[0], DAILY[0], CONTROL])
@pytest.mark.parametrize('mode,stage', [('100755', '0'), ('120000', '0'), ('160000', '0'),
                                     ('100644', '1'), ('100644', '2'), ('100644', '3')])
def test_index_requires_regular_nonexecutable_stage_zero(tree: Tree, name: str,
                                                      mode: str, stage: str) -> None:
    tree.modes[name] = mode
    tree.stages[name] = stage
    with pytest.raises(ValueError, match='^REGULAR_STAGE_ZERO_BLOB_REQUIRED$'):
        check.verify(tree.root, BASE)


@pytest.mark.parametrize('index', ['', '100644 bad 0\t{path}',
    '100644 ' + 'a' * 40 + ' 0\twrong.py',
    '100644 ' + 'a' * 40 + ' 0\t{path}\n100644 ' + 'b' * 40 + ' 0\t{path}'])
def test_malformed_index_response_blocks(tree: Tree, monkeypatch: pytest.MonkeyPatch,
                                       index: str) -> None:
    def git(root: Path, *args: str) -> str:
        if args == ('ls-files', '--stage', '--', PRIOR[0]):
            return index.replace('{path}', PRIOR[0])
        return tree.git(root, *args)

    monkeypatch.setattr(check, 'git', git)
    with pytest.raises(ValueError, match='^REGULAR_STAGE_ZERO_BLOB_REQUIRED$'):
        check.verify(tree.root, BASE)


def test_public_lf_pins_and_staged_blobs_allow_crlf(tree: Tree) -> None:
    name = PRIOR[0]
    (tree.root / name).write_bytes(tree.blobs[name].replace(b'\r\n', b'\n'))
    assert check.verify(tree.root, BASE) == []


@pytest.mark.parametrize('mutation', ['crlf', 'changed', 'sidecar'])
def test_policy_requires_raw_sha256_not_lf_normalized(tree: Tree, mutation: str) -> None:
    target = tree.root / 'resilience_policy.json'
    if mutation == 'crlf':
        target.write_bytes(target.read_bytes().replace(b'\n', b'\r\n'))
    elif mutation == 'changed':
        target.write_bytes(b'{"synthetic_policy":false}\n')
    else:
        (tree.root / 'resilience_policy.sha256').write_bytes(b'0' * 64 + b'\n')
    with pytest.raises(ValueError, match='^APPROVED_POLICY_BYTES_INVALID$'):
        check.verify(tree.root, BASE)


def test_git_wrapper_exact_subprocess_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def run(args: list[str], *, check: bool, stdout: int, stderr: int,
            timeout: int) -> subprocess.CompletedProcess[bytes]:
        assert args == ['git', '-C', str(tmp_path), 'rev-parse', 'HEAD']
        assert check is True
        assert (stdout, stderr, timeout) == (subprocess.PIPE, subprocess.DEVNULL, 30)
        return subprocess.CompletedProcess(args, 0, stdout=b'  synthetic-head\r\n')

    monkeypatch.setattr(subprocess, 'run', run)
    assert check.git(tmp_path, 'rev-parse', 'HEAD') == 'synthetic-head'


@pytest.mark.parametrize('tamper', [False, True])
def test_main_success_and_hash_failure(tree: Tree, monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture[str], tamper: bool) -> None:
    monkeypatch.chdir(tree.root)
    old = tree.blobs[PRIOR[0]]
    changed = b'# changed synthetic prerequisite\n'
    if tamper:
        (tree.root / PRIOR[0]).write_bytes(changed)
        tree.blobs[PRIOR[0]] = changed
    assert check.main(['--base', BASE]) == (2 if tamper else 0)
    output = capsys.readouterr()
    assert output.err == ''
    assert json.loads(output.out) == {
        'status': 'BLOCKED' if tamper else 'DAILY_PACKAGE_VERIFIED_REQUIRES_TESTS_AND_EXACT_COMMIT_CI',
        'failures': [{'path': PRIOR[0], 'expected': sha(old), 'actual': sha(changed)}] if tamper else [],
        'hosted_changes': 0,
    }


@pytest.mark.parametrize('problem,rule', [
    ('base', 'BASE_NOT_CURRENT_HEAD'), ('root', 'CLONE_ROOT_REQUIRED'),
    ('baseline', 'BASE_TREE_NOT_ANCHOR_PLUS_FROZEN_CONTINUITY'),
    ('staged', 'EXACT_STAGED_ADDITIONS_REQUIRED'), ('dirty', 'STAGE_EXACT_PACKAGE_THEN_CHECK'),
    ('duplicate', 'DUPLICATE_CONTROL_FIELD'), ('extra', 'CONTROL_INVALID'),
    ('json', 'PUBLIC_PACKAGE_REVIEW_REQUIRED'), ('utf8', 'PUBLIC_PACKAGE_REVIEW_REQUIRED'),
    ('subprocess', 'PUBLIC_PACKAGE_REVIEW_REQUIRED'), ('value-error', 'PUBLIC_PACKAGE_REVIEW_REQUIRED'),
    ('missing', 'PUBLIC_SOURCE_MISSING_OR_TOO_LARGE'),
    ('size-malformed', 'STAGED_BLOB_TOO_LARGE'),
    ('size-oversize', 'STAGED_BLOB_TOO_LARGE'),
    ('size-mismatch', 'STAGED_BLOB_SIZE_MISMATCH'),
])
def test_main_redacts_errors(tree: Tree, monkeypatch: pytest.MonkeyPatch,
                            capsys: pytest.CaptureFixture[str], problem: str, rule: str) -> None:
    monkeypatch.chdir(tree.root)
    secret = 'synthetic-secret-do-not-print'
    if problem == 'base':
        tree.head = 'c' * 40
    elif problem == 'root':
        tree.top = tree.root.parent
    elif problem == 'baseline':
        tree.baseline.append('M\tunrelated.py')
    elif problem == 'staged':
        tree.staged.pop()
    elif problem == 'dirty':
        tree.untracked = secret
    elif problem == 'duplicate':
        (tree.root / CONTROL).write_bytes(b'{"x":1,"x":2}')
    elif problem == 'extra':
        plan: dict[str, object] = dict(tree.plan)
        plan['unknown'] = secret
        tree.write_plan(plan)
    elif problem == 'json':
        (tree.root / CONTROL).write_bytes(secret.encode('ascii'))
    elif problem == 'utf8':
        (tree.root / CONTROL).write_bytes(b'\xff' + secret.encode('ascii'))
    elif problem == 'size-malformed':
        tree.sizes[PRIOR[0]] = secret
    elif problem == 'size-oversize':
        tree.sizes[PRIOR[0]] = str(check.LIMIT + 1)
    elif problem == 'size-mismatch':
        tree.sizes[PRIOR[0]] = str(len(tree.blobs[PRIOR[0]]) + 1)
    elif problem in {'subprocess', 'value-error'}:
        def git(root: Path, *args: str) -> str:
            if problem == 'value-error':
                raise ValueError(secret + str(root))
            raise subprocess.CalledProcessError(1, ['git', secret], output=secret, stderr=secret)

        monkeypatch.setattr(check, 'git', git)
    else:
        (tree.root / CONTROL).unlink()
    assert check.main(['--base', BASE]) == 2
    output = capsys.readouterr()
    assert output.err == ''
    assert secret not in output.out and str(tree.root) not in output.out
    assert json.loads(output.out) == {
        'status': 'BLOCKED', 'rule': rule, 'hosted_changes': 0, 'raw_error_printed': False}
