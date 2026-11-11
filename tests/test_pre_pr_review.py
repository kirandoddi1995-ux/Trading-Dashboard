"""tooling/pre_pr_review.py: the local gate that mirrors the PR review bots.

Secret-shaped fixtures are assembled at run time so this file never holds one.

Each check runs on a throwaway git repository built in the test, so the results do
not depend on this repository's history. No network.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
import textwrap

import pytest

from tooling import pre_pr_review as gate

needs_tree_sitter = pytest.mark.skipif(
    not all(importlib.util.find_spec(name) for name in ("tree_sitter", "tree_sitter_typescript")),
    reason="tree-sitter review tooling not installed (tooling/requirements-review.txt)")


def _repo(tmp_path, monkeypatch, base_files, new_files):
    """A git repo with `base_files` committed as origin/main and `new_files` on top."""
    def run(*args):
        """Run git quietly inside the temp repo."""
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.test")
    run("config", "user.name", "t")
    for name, text in base_files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(textwrap.dedent(text))
    run("add", "-A")
    run("commit", "-q", "-m", "base")
    run("update-ref", "refs/remotes/origin/main", "HEAD")
    for name, text in new_files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(textwrap.dedent(text))
    monkeypatch.setattr(gate, "ROOT", tmp_path)


def test_complexity_counts_branches_but_not_nested_functions():
    """McCabe count: if/for/while/except/bool-op/comprehension; nested defs excluded."""
    node = ast.parse(textwrap.dedent("""
        def f(a, b):
            if a and b:
                return [x for x in a if x]
            for _ in b:
                try:
                    pass
                except ValueError:
                    pass
            def inner():
                if a:
                    pass
            return 1 if a else 2
    """)).body[0]
    assert gate.python_complexity(node) == 1 + 1 + 1 + 2 + 1 + 1 + 1


def test_touched_undocumented_branching_function_fails_and_untouched_is_ignored(tmp_path, monkeypatch):
    """Only functions the diff touches count; complexity 1 needs no docstring."""
    base = {"m.py": """
        def old(x):
            if x:
                return 1
            return 2
        def stays(x):
            if x:
                return 1
            return 2
    """}
    new = {"m.py": """
        def old(x):
            if x:
                return 10
            return 2
        def stays(x):
            if x:
                return 1
            return 2
        def simple():
            return 3
        def documented(x):
            \"\"\"Has a docstring.\"\"\"
            return 1 if x else 2
    """}
    _repo(tmp_path, monkeypatch, base, new)
    fails, warns, units = gate.review("origin/main")
    assert sorted(u.name for u in units) == ["documented", "old", "simple"]
    assert fails == ["DOCSTRING missing (complexity 2): m.py:2 old"]


@needs_tree_sitter
def test_typescript_functions_need_jsdoc_and_are_bounded_by_braces(tmp_path, monkeypatch):
    """A JSDoc right above counts; a later edit does not touch an earlier function."""
    base = {"a.ts": """
        function untouched(x: number): number {
          if (x) return 1;
          return 2;
        }
    """}
    new = {"a.ts": """
        function untouched(x: number): number {
          if (x) return 1;
          return 2;
        }

        type Extra = { a?: string };

        /** Documented. */
        export function good(x: number): number {
          return x > 1 ? 1 : 2;
        }

        export async function bad(x: number) {
          if (x && x > 2) return 1;
          return 0;
        }
    """}
    _repo(tmp_path, monkeypatch, base, new)
    fails, _, units = gate.review("origin/main")
    assert sorted(u.name for u in units) == ["bad", "good"]
    assert fails == ["DOCSTRING missing (complexity 3): a.ts:14 bad"]


def test_secret_like_text_and_pyflakes_fail(tmp_path, monkeypatch):
    """A token-shaped string or an unused import fails the gate."""
    token = "ghp_" + "A" * 30
    _repo(tmp_path, monkeypatch, {"m.py": "x = 1\n"},
          {"m.py": f"import os\nx = '{token}'\n", "notes.txt": "-----BEGIN " + "RSA PRIVATE KEY-----\n"})
    fails, _, _ = gate.review("origin/main")
    assert any(f.startswith("PYFLAKES") and "'os' imported but unused" in f for f in fails)
    assert "SECRET-LIKE (GitHub token) added in m.py" in fails
    assert "SECRET-LIKE (private key) added in notes.txt" in fails


def test_growth_in_complexity_warns_but_does_not_fail(tmp_path, monkeypatch):
    """A documented function crossing the complexity bar is a WARN, not a FAIL."""
    body = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(12))
    _repo(tmp_path, monkeypatch, {"m.py": "def f(x):\n    \"\"\"Doc.\"\"\"\n    return 0\n"},
          {"m.py": f"def f(x):\n    \"\"\"Doc.\"\"\"\n{body}\n    return 0\n"})
    fails, warns, _ = gate.review("origin/main")
    assert fails == [] and warns == ["COMPLEXITY 1 -> 13: m.py:1 f"]
    assert gate.main(["--base", "origin/main"]) == 0


@pytest.mark.parametrize("text, label", [
    ("token = 'github_pat_" + "a1" * 15 + "'", "GitHub token"),
    ("Authorization: " + "eyJ" + "hbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig", "JWT"),
    ("AKIA" + "ABCDEFGHIJKLMNOP", "AWS key"),
])
def test_secret_patterns(text, label):
    """Each credential shape is recognised."""
    assert gate.LEAK_PATTERNS[label].search(text)


def test_test_gap_uses_body_lines_not_the_def_line(tmp_path, monkeypatch):
    """A function whose only executed line is its `def` (import time) is a test gap."""
    _repo(tmp_path, monkeypatch, {"m.py": "x = 1\n"}, {"m.py": textwrap.dedent('''
        def called(x):
            """Doc."""
            return x + 1


        def never(x):
            """Doc."""
            return x - 1
    ''')})
    units, _ = gate.collect_units("origin/main")
    by_name = {u.name: u for u in units}
    executed = {by_name["called"].start, by_name["never"].start, by_name["called"].body_start}
    monkeypatch.setattr(gate, "coverage_map", lambda tests, paths: {"m.py": executed})
    assert gate.coverage_findings(units, ["tests/t.py"]) == [
        f"TEST GAP no test runs m.py:{by_name['never'].start} never"]
    assert by_name["called"].covered is True and by_name["never"].covered is False


@needs_tree_sitter
def test_every_typescript_function_form_is_found_named_and_spanned(tmp_path, monkeypatch):
    """Arrows (bare, let, multi-line, generic), generators, methods, default export, next-line brace."""
    source = """
        const bare = x => { if (x) return 1; return 2; };
        let viaLet = (x: number) => { if (x) return 1; return 2; };
        const multi = (
          a: number,
          b: number,
        ) => { if (a) return b; return a; };
        const generic = <T,>(x: T) => { if (x) return x; return x; };
        function* gen(x: number) { if (x) yield 1; }
        const obj = { method(x: number) { if (x) return 1; return 2; }, prop: (x: number) => x ? 1 : 2 };
        class Box { size(x: number) { if (x) return 1; return 2; } }
        export default function (x: number) { if (x) return 1; return 2; }
        function sig(a: number,
          b: number)
        {
          const text = "} not a brace {";
          if (a) return b;
          return a;
        }
    """
    _repo(tmp_path, monkeypatch, {"a.ts": "export {};\n"}, {"a.ts": source})
    units, fails = gate.collect_units("origin/main")
    assert fails == []
    spans = {u.name: (u.start, u.end, u.complexity, u.documented) for u in units}
    assert set(spans) == {"bare", "viaLet", "multi", "generic", "gen", "method", "prop", "Box.size",
                          "default", "sig"}
    assert spans["multi"][:2] == (4, 7)
    assert spans["sig"][:2] == (13, 19)
    assert all(complexity == 2 and not documented for _, _, complexity, documented in spans.values())
    review_fails, _ = gate.unit_findings(units)
    assert len(review_fails) == 10


@needs_tree_sitter
def test_typescript_complexity_counts_each_branch_kind_and_skips_nested_functions(tmp_path, monkeypatch):
    """if, for, for-of, while, do, catch, case (not default), ternary, &&, ||, ??; inner arrow excluded."""
    source = """
        /** Doc. */
        export function busy(a: any, b: any) {
          if (a) {}
          for (;;) { break; }
          for (const x of b) {}
          while (a) { break; }
          do {} while (false);
          try {} catch { }
          switch (a) { case 1: break; case 2: break; default: break; }
          const c = a ? 1 : 2;
          const d = a && b || c;
          const e = a ?? b;
          const inner = () => { if (a) {} if (b) {} };
          return [c, d, e, inner];
        }
    """
    _repo(tmp_path, monkeypatch, {"a.ts": "export {};\n"}, {"a.ts": source})
    units, _ = gate.collect_units("origin/main")
    by_name = {u.name: u for u in units}
    assert by_name["busy"].complexity == 1 + 1 + 1 + 1 + 1 + 1 + 1 + 2 + 1 + 2 + 1
    assert by_name["busy.inner"].complexity == 3 and by_name["busy"].documented


@needs_tree_sitter
def test_jsdoc_is_found_above_exports_variables_methods_and_returned_functions(tmp_path, monkeypatch):
    """The JSDoc sits above the statement, not the function node itself; // and /* */ are not JSDoc."""
    source = """
        /** A. */
        export const a = (x: number) => x ? 1 : 2;
        // Not JSDoc.
        export const b = (x: number) => x ? 1 : 2;
        /* Not JSDoc either. */
        export const c = (x: number) => x ? 1 : 2;
        class K {
          /** M. */
          m(x: number) { return x ? 1 : 2; }
        }
        /** Outer. */
        export function outer(): (x: number) => number {
          /** Returned. */
          return (x: number) => x ? 1 : 2;
        }
    """
    _repo(tmp_path, monkeypatch, {"a.ts": "export {};\n"}, {"a.ts": source})
    units, _ = gate.collect_units("origin/main")
    documented = {u.name: u.documented for u in units}
    assert documented == {"a": True, "b": False, "c": False, "K.m": True, "outer": True,
                          "outer.<returned function>": True}


@needs_tree_sitter
def test_anonymous_callbacks_warn_named_functions_fail(tmp_path, monkeypatch):
    """An undocumented branching test() callback is a WARN; a named function is a FAIL."""
    source = """
        test("loops", () => { for (const x of [1]) { void x; } });
        export function named(x: number) { return x ? 1 : 2; }
    """
    _repo(tmp_path, monkeypatch, {"a.test.ts": "export {};\n"}, {"a.test.ts": source})
    fails, warns, units = gate.review("origin/main")
    assert {u.name: u.anonymous for u in units} == {'<callback of test("loops")>': True, "named": False}
    assert fails == ["DOCSTRING missing (complexity 2): a.test.ts:3 named"]
    assert warns == ['DOCSTRING missing (complexity 2): a.test.ts:2 <callback of test("loops")>']


@needs_tree_sitter
def test_unparsable_typescript_fails_instead_of_passing(tmp_path, monkeypatch):
    """A parse error is reported (tree-sitter recovers silently otherwise)."""
    _repo(tmp_path, monkeypatch, {"a.ts": "export {};\n"}, {"a.ts": "function broken( {\n  return 1;\n"})
    fails, _, _ = gate.review("origin/main")
    assert any(f.startswith("a.ts: TypeScript parse error near line") for f in fails)


def test_missing_tree_sitter_stops_the_gate(monkeypatch):
    """No TypeScript parser: stop with the install hint, never a silent PASS."""
    monkeypatch.setitem(sys.modules, "tree_sitter", None)
    with pytest.raises(SystemExit, match="requirements-review.txt"):
        gate._ts_parser("a.ts")


def test_a_deletion_only_change_touches_the_function(tmp_path, monkeypatch):
    """A hunk that only removes lines (+c,0) still marks the function as touched."""
    _repo(tmp_path, monkeypatch,
          {"m.py": "def f(x):\n    if x:\n        return 1\n    y = 2\n    return y\n"},
          {"m.py": "def f(x):\n    if x:\n        return 1\n    return y\n"})
    units, _ = gate.collect_units("origin/main")
    assert [u.name for u in units] == ["f"]
    assert gate._hunk_lines("@@ -4 +3,0 @@\n") == {3, 4}
    assert gate._hunk_lines("@@ -1,2 +0,0 @@\n") == {1}


def test_odd_paths_and_user_diff_config_are_still_reviewed(tmp_path, monkeypatch):
    """Spaces, non-ASCII names and diff.noprefix / color / quotePath settings never drop a file."""
    names = ["my mod.py", "m\u00f6d\u00fcl.py"]
    _repo(tmp_path, monkeypatch, {name: "x = 1\n" for name in names}, {})
    for config in (("diff.noprefix", "true"), ("color.diff", "always"), ("core.quotePath", "true")):
        subprocess.run(["git", "config", *config], cwd=tmp_path, check=True)
    for name in names:
        (tmp_path / name).write_text("import os\ndef f(x):\n    return 1 if x else 2\n")
    fails, _, units = gate.review("origin/main")
    assert sorted(u.path for u in units) == sorted(names)
    for name in names:
        assert f"DOCSTRING missing (complexity 2): {name}:2 f" in fails
        assert any(f.startswith(f"PYFLAKES {name}:1") for f in fails)


def test_untracked_files_count_whole_and_binaries_are_skipped(tmp_path, monkeypatch):
    """New files are reviewed in full; a binary untracked file is ignored, not decoded."""
    _repo(tmp_path, monkeypatch, {"keep.txt": "x\n"}, {"new.py": "def f(x):\n    return 1 if x else 2\n"})
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01ghp_" + b"A" * 30)
    assert gate.changed_lines("origin/main") == {"new.py": {1, 2, 3}}
    assert not any(path == "blob.bin" for path, _ in gate.added_text("origin/main"))


def test_nested_python_functions_are_collected_with_qualified_names(tmp_path, monkeypatch):
    """Inner functions and methods are their own units."""
    source = (
        "class C:\n"
        "    \"\"\"Doc.\"\"\"\n"
        "\n"
        "    def method(self, x):\n"
        "        \"\"\"Doc.\"\"\"\n"
        "        def inner(y):\n"
        "            return 1 if y else 2\n"
        "        return inner(x)\n"
    )
    _repo(tmp_path, monkeypatch, {"m.py": "x = 1\n"}, {"m.py": source})
    units, _ = gate.collect_units("origin/main")
    assert [u.name for u in units] == ["C.method", "C.method.inner"]
    assert gate.unit_findings(units)[0] == ["DOCSTRING missing (complexity 2): m.py:6 C.method.inner"]


def test_fan_out_growth_warns(tmp_path, monkeypatch):
    """More than 12 distinct callees, and more than before: a WARN."""
    calls = "\n".join(f"    f{i}()" for i in range(13))
    _repo(tmp_path, monkeypatch, {"m.py": "def g():\n    \"\"\"Doc.\"\"\"\n    f0()\n"},
          {"m.py": f"def g():\n    \"\"\"Doc.\"\"\"\n{calls}\n"})
    _, warns = gate.unit_findings(gate.collect_units("origin/main")[0])
    assert warns == ["FAN-OUT 1 -> 13 callees: m.py:1 g"]


class _Done:
    """subprocess.run result stand-in."""

    def __init__(self, stdout="", stderr="", returncode=0):
        """Keep the outputs and exit status."""
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_missing_pyflakes_stops_the_gate_and_stderr_counts(monkeypatch):
    """No pyflakes: stop with the hint. Syntax errors on stderr are findings, not ignored."""
    def answer(**result):
        """A fake subprocess.run returning `result`."""
        return lambda *args, **kwargs: _Done(**result)

    monkeypatch.setattr(gate.subprocess, "run", answer(stderr="No module named pyflakes", returncode=1))
    with pytest.raises(SystemExit, match="pyflakes is not installed"):
        gate.pyflakes_findings(["m.py"])
    monkeypatch.setattr(gate.subprocess, "run", answer(stderr="m.py:1:5: invalid syntax", returncode=1))
    assert gate.pyflakes_findings(["m.py"]) == ["PYFLAKES m.py:1:5: invalid syntax"]
    monkeypatch.setattr(gate.subprocess, "run", answer(returncode=2))
    assert gate.pyflakes_findings(["m.py"]) == ["PYFLAKES exited 2 without output"]


def test_coverage_needs_passing_tests_and_counts_only_test_contexts(monkeypatch):
    """Scoped run with per-test contexts; import-time-only lines do not count; failing tests stop the gate;
    the scratch directory is removed afterwards."""
    calls, rc_texts = [], []

    def run(cmd, **kwargs):
        """Answer the coverage run, then the JSON report with contexts (reading the rcfile while it exists)."""
        calls.append(cmd)
        rcfile = next(arg for arg in cmd if arg.startswith("--rcfile=")).split("=", 1)[1]
        rc_texts.append(open(rcfile, encoding="utf-8").read())
        if "json" in cmd:
            return _Done('{"files": {"m.py": {"contexts": {"1": [""], "3": ["tests.t.test_x"], "4": ["", "t.y"]}}}}')
        return _Done()

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.coverage_map(["tests/t.py"], ["m.py", "n.py"]) == {"m.py": {3, 4}}
    assert calls[0][1:4] == ["-m", "coverage", "run"] and "--include=m.py,n.py" in calls[0]
    assert calls[0][-1] == "tests/t.py" and "--show-contexts" in calls[1]
    rcfile = next(arg for arg in calls[0] if arg.startswith("--rcfile=")).split("=", 1)[1]
    assert "dynamic_context = test_function" in rc_texts[0]
    assert not os.path.exists(os.path.dirname(rcfile))  # no temp files left behind
    monkeypatch.setattr(gate.subprocess, "run", lambda cmd, **kwargs: _Done("1 failed", returncode=1))
    with pytest.raises(SystemExit, match="coverage test run failed"):
        gate.coverage_map(["tests/t.py"], ["m.py"])
    monkeypatch.setattr(gate.subprocess, "run",
                        lambda cmd, **kwargs: _Done(stderr="No module named coverage", returncode=1))
    with pytest.raises(SystemExit, match="coverage is not installed"):
        gate.coverage_map(["tests/t.py"], ["m.py"])


def test_coverage_flag_needs_at_least_one_test():
    """`--coverage` alone is a usage error, never a silent PASS."""
    with pytest.raises(SystemExit) as caught:
        gate.main(["--coverage"])
    assert caught.value.code == 2


@pytest.mark.skipif(importlib.util.find_spec("coverage") is None, reason="coverage.py not installed")
def test_real_coverage_run_flags_a_function_only_called_at_import(tmp_path, monkeypatch):
    """End to end: called only at import (even via a test-named function) is a TEST GAP; called in a test is covered."""
    module = (
        "def at_import(x):\n"
        "    \"\"\"Doc.\"\"\"\n"
        "    return x + 1\n"
        "\n"
        "\n"
        "def in_test(x):\n"
        "    \"\"\"Doc.\"\"\"\n"
        "    return x - 1\n"
        "\n"
        "\n"
        "def testable_default():\n"
        "    \"\"\"Named like a test, called only at import: coverage opens a context for it.\"\"\"\n"
        "    return at_import(0)\n"
        "\n"
        "\n"
        "VALUE = testable_default()\n"
    )
    test = "import m\n\n\ndef test_it():\n    assert m.in_test(2) == 1\n"
    _repo(tmp_path, monkeypatch, {"other.txt": "x\n"}, {"m.py": module, "tests/test_m.py": test})
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(tmp_path), os.environ.get("PYTHONPATH", "")]))
    units, _ = gate.collect_units("origin/main")
    assert gate.coverage_findings(units, ["tests/test_m.py"]) == [
        "TEST GAP no test runs m.py:1 at_import", "TEST GAP no test runs m.py:11 testable_default"]


def _join(*parts):
    """Assemble a secret-shaped fixture at run time (no literal token in this file)."""
    return "".join(parts)


@pytest.mark.parametrize("text, label", [
    (_join("ANTHROPIC=sk-", "ant-api03-", "A" * 40), "Anthropic key"),
    (_join("OPENAI=sk-", "proj-", "B" * 40), "OpenAI-style key"),
    (_join("sk-", "C" * 40), "OpenAI-style key"),
    (_join("postgresql://postgres.ref:", "hunter2pass", "@aws-0.pooler.supabase.com:6543/postgres"),
     "database URL with password"),
    (_join('"client_secret": "GOCSPX-', "D" * 28, '"'), "Google OAuth client secret"),
    (_join('"token": "ya29.', "E" * 40, '"'), "Google access token"),
    (_join('"refresh_token": "1//', "0" + "F" * 40, '"'), "Google refresh token"),
    (_join("SUPABASE_KEY=sb_", "secret_", "G" * 30), "Supabase secret key"),
    (_join("xox", "b-123456789012-", "H" * 20), "Slack token"),
    (_join("123456789:AA", "I" * 33), "Telegram bot token"),
])
def test_project_credential_shapes_are_recognised(text, label):
    """Shapes this project actually holds: DB URL, Drive OAuth JSON, Supabase, bots, model keys."""
    assert gate.LEAK_PATTERNS[label].search(text)
    if label == "Anthropic key":
        assert not gate.LEAK_PATTERNS["OpenAI-style key"].search(text)


@pytest.mark.parametrize("text", [
    "postgresql://synthetic", "postgresql://localhost:5432/db", "url := 'https://x.test/1//2'",
    "sb_publishable_abc", "https://example.test/path//1", "skip-this-word", "time 12:30",
])
def test_ordinary_text_is_not_secret_like(text):
    """Placeholders and ordinary strings do not trip any pattern."""
    assert not [label for label, pattern in gate.LEAK_PATTERNS.items() if pattern.search(text)]


def test_glob_like_file_names_are_diffed_literally(tmp_path, monkeypatch):
    """A file named `[ab].py` gets its own hunks, not a.py's (pathspec magic is off)."""
    _repo(tmp_path, monkeypatch, {"[ab].py": "x = 1\n", "a.py": "y = 1\n" * 5},
          {"[ab].py": "x = 2\n", "a.py": "y = 1\n" * 4 + "y = 2\n"})
    assert gate.changed_lines("origin/main") == {"[ab].py": {1}, "a.py": {5}}


def _git(repo, *args):
    """Run git quietly in a test repository."""
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_cli_exit_status_and_result_line_follow_the_findings(tmp_path, monkeypatch, capsys):
    """One FAIL: exit 1 and RESULT FAIL. Clean tree: exit 0 and RESULT PASS."""
    _repo(tmp_path, monkeypatch, {"m.py": "x = 1\n"}, {"m.py": "def f(x):\n    return 1 if x else 2\n"})
    assert gate.main(["--base", "origin/main"]) == 1
    out = capsys.readouterr().out
    assert "FAIL DOCSTRING missing (complexity 2): m.py:1 f" in out and out.rstrip().endswith("RESULT FAIL")
    (tmp_path / "m.py").write_text("x = 1\n")
    assert gate.main(["--base", "origin/main"]) == 0
    assert capsys.readouterr().out.rstrip().endswith("RESULT PASS")


def test_main_moving_on_is_not_blamed_on_a_branch_behind_it(tmp_path, monkeypatch):
    """Review against the merge base: main fixing its own file does not make the branch 'change' it."""
    _repo(tmp_path, monkeypatch, {"m.py": "import os\nx = 1\n"}, {})
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    _git(tmp_path, "checkout", "-q", "main")
    (tmp_path / "m.py").write_text("x = 1\n")
    _git(tmp_path, "commit", "-q", "-am", "main fixes its own unused import")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(tmp_path, "checkout", "-q", "feature")
    fails, _, units = gate.review("origin/main")
    assert fails == [] and units == []


@pytest.mark.parametrize("revert", ["commit", "working-tree"])
def test_a_secret_in_any_branch_commit_fails_even_if_removed_later(tmp_path, monkeypatch, revert):
    """The push carries every commit: a token committed then removed (or only reverted locally) fails."""
    _repo(tmp_path, monkeypatch, {"notes.txt": "x\n"}, {})
    (tmp_path / "notes.txt").write_text("x\n" + _join("ghp_", "Z" * 30) + "\n")
    _git(tmp_path, "commit", "-q", "-am", "oops")
    (tmp_path / "notes.txt").write_text("x\n")
    if revert == "commit":
        _git(tmp_path, "commit", "-q", "-am", "remove it")
    fails, _, _ = gate.review("origin/main")
    assert "SECRET-LIKE (GitHub token) added in notes.txt" in fails


def test_only_contexts_from_the_given_test_modules_count(tmp_path, monkeypatch):
    """coverage.py opens a context for any function named test*; only the test files' own count."""
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "sub").mkdir()
    for name in ("test_a.py", "test_b.py", "sub/test_c.py", "sub/helpers_test.py", "sub/helpers.py"):
        (tmp_path / "tests" / name).write_text("")
    assert gate._test_module_names(["tests/test_a.py::test_x"]) == {"test_a"}
    assert gate._test_module_names(["tests"]) == {"test_a", "test_b", "test_c", "helpers_test"}
    modules = {"test_a"}
    assert gate._from_a_test("tests.test_a.test_x", modules) and gate._from_a_test("test_a.Case.test_y", modules)
    assert not gate._from_a_test("m.testable_default", modules)
    assert not gate._from_a_test("", modules) and not gate._from_a_test("test_b.test_x", modules)


def test_property_getter_and_setter_are_both_checked_and_decorator_edits_touch(tmp_path, monkeypatch):
    """Same qualified name twice: both units exist; editing only a decorator touches the function."""
    base = (
        "class C:\n"
        "    \"\"\"Doc.\"\"\"\n"
        "\n"
        "    @property\n"
        "    def v(self):\n"
        "        return 1 if self else 2\n"
        "\n"
        "    @v.setter\n"
        "    def v(self, value):\n"
        "        \"\"\"Doc.\"\"\"\n"
        "        self._v = value\n"
    )
    _repo(tmp_path, monkeypatch, {"m.py": base}, {"m.py": base.replace("    @property\n", "    @property  # edited\n")})
    units, _ = gate.collect_units("origin/main")
    assert [(u.name, u.start) for u in units] == [("C.v", 5)]
    (tmp_path / "m.py").write_text(base + "\n")
    _git(tmp_path, "add", "-A")
    units = gate.python_units("m.py", set(range(1, 12)), "origin/main")
    assert [(u.name, u.start, u.documented) for u in units] == [("C.v", 5, False), ("C.v", 9, True)]


def test_stub_functions_are_not_test_gaps(tmp_path, monkeypatch):
    """Docstring-only, pass or ... bodies have no line coverage can record."""
    source = (
        "def stub():\n"
        "    \"\"\"Doc only.\"\"\"\n"
        "\n"
        "\n"
        "def placeholder():\n"
        "    \"\"\"Doc.\"\"\"\n"
        "    ...\n"
        "\n"
        "\n"
        "def real():\n"
        "    \"\"\"Doc.\"\"\"\n"
        "    return 1\n"
        "\n"
        "\n"
        "def passes():\n"
        "    \"\"\"Doc.\"\"\"\n"
        "    pass\n"
        "\n"
        "\n"
        "def noted():\n"
        "    \"\"\"Doc.\"\"\"\n"
        "    \"a second bare string\"\n"
    )
    _repo(tmp_path, monkeypatch, {"other.txt": "x\n"}, {"m.py": source})
    units, _ = gate.collect_units("origin/main")
    assert {u.name: u.body_start for u in units} == {
        "stub": None, "placeholder": None, "real": 12, "passes": None, "noted": None}
    monkeypatch.setattr(gate, "coverage_map", lambda tests, paths: {"m.py": set()})
    assert gate.coverage_findings(units, ["tests/t.py"]) == ["TEST GAP no test runs m.py:10 real"]


@pytest.mark.parametrize("text, label", [
    (_join("SUPABASE_ACCESS_TOKEN=sbp_", "0123456789abcdef" * 2, "01234567"), "Supabase access token"),
    (_join("key=AIza", "S" * 35), "Google API key"),
    (_join("STRIPE=sk_", "live_", "T" * 24), "Stripe live key"),
    (_join("STRIPE_RESTRICTED=rk_", "live_", "U" * 24), "Stripe live key"),
    (_join("key=AIza", "V" * 34, "-"), "Google API key"),          # ends in '-' (no word boundary)
    (_join("987654321:AA", "W" * 32, "-"), "Telegram bot token"),
])
def test_more_credential_shapes_are_recognised(text, label):
    """Supabase personal access tokens, Google API keys, Stripe live keys."""
    assert gate.LEAK_PATTERNS[label].search(text)


@needs_tree_sitter
def test_tsx_and_javascript_use_the_jsx_grammar(tmp_path, monkeypatch):
    """JSX in .tsx/.jsx parses (the plain TypeScript grammar would report a parse error)."""
    source = "/** View. */\nexport function View(p: { on: boolean }) {\n  return p.on ? <b>on</b> : <i>off</i>;\n}\n"
    _repo(tmp_path, monkeypatch, {"keep.txt": "x\n"}, {"v.tsx": source, "w.jsx": source.replace(": { on: boolean }", "")})
    fails, _, units = gate.review("origin/main")
    assert fails == [] and sorted((u.path, u.name, u.documented) for u in units) == [
        ("v.tsx", "View", True), ("w.jsx", "View", True)]


def test_test_files_are_never_coverage_targets(monkeypatch):
    """Changed test helpers are not 'untested production code': no coverage run for them."""
    monkeypatch.setattr(gate, "coverage_map", lambda tests, paths: pytest.fail("no coverage run expected"))
    unit = gate.Unit("tests/test_x.py", "helper", 1, 3, 2, True, body_start=3)
    assert gate.coverage_findings([unit], ["tests/test_x.py"]) == []


def test_complexity_that_did_not_grow_is_not_a_warning(tmp_path, monkeypatch):
    """Touching an already-complex function without adding branches: no COMPLEXITY warning."""
    body = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(12))
    before = f"def f(x):\n    \"\"\"Doc.\"\"\"\n{body}\n    return 0\n"
    _repo(tmp_path, monkeypatch, {"m.py": before}, {"m.py": before.replace("return 0", "return -1")})
    fails, warns, units = gate.review("origin/main")
    assert [u.name for u in units] == ["f"] and units[0].complexity == 13
    assert fails == [] and warns == []


def test_a_secret_in_the_second_file_of_a_commit_is_found(tmp_path, monkeypatch):
    """Every file of every branch commit is scanned, not just the first."""
    _repo(tmp_path, monkeypatch, {"a.txt": "x\n", "b.txt": "y\n"}, {})
    (tmp_path / "a.txt").write_text("x\nplain\n")
    (tmp_path / "b.txt").write_text("y\n" + _join("ghp_", "Y" * 30) + "\n")
    _git(tmp_path, "commit", "-q", "-am", "two files")
    (tmp_path / "b.txt").write_text("y\n")
    _git(tmp_path, "commit", "-q", "-am", "clean")
    assert "SECRET-LIKE (GitHub token) added in b.txt" in gate.review("origin/main")[0]


def test_a_secret_typed_while_resolving_a_merge_is_found(tmp_path, monkeypatch):
    """Merge commits are scanned against their first parent; one finding per kind and file."""
    _repo(tmp_path, monkeypatch, {"a.txt": "x\n"}, {})
    _git(tmp_path, "checkout", "-q", "-b", "side")
    (tmp_path / "s.txt").write_text("side\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "side")
    _git(tmp_path, "checkout", "-q", "main")
    _git(tmp_path, "merge", "-q", "--no-ff", "--no-commit", "side")
    (tmp_path / "a.txt").write_text("x\n" + _join("ghp_", "X" * 30) + "\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "merge side")
    (tmp_path / "a.txt").write_text("x\n")
    _git(tmp_path, "commit", "-q", "-am", "clean")
    fails = gate.review("origin/main")[0]
    assert fails.count("SECRET-LIKE (GitHub token) added in a.txt") == 1


def test_no_merge_base_stops_with_a_hint(tmp_path, monkeypatch):
    """Missing origin/main (or a too-shallow clone): a clear stop, not a traceback."""
    _repo(tmp_path, monkeypatch, {"a.txt": "x\n"}, {})
    _git(tmp_path, "update-ref", "-d", "refs/remotes/origin/main")
    with pytest.raises(SystemExit, match="git fetch origin main"):
        gate.review("origin/main")


def test_a_property_getter_is_compared_with_the_old_getter(tmp_path, monkeypatch):
    """Duplicate names are matched by occurrence, so the getter's growth is measured against itself."""
    body = "\n".join(f"        if self == {i}:\n            return {i}" for i in range(12))
    def module(getter_body):
        """A class with a documented branching getter and a plain setter."""
        return (
            "class C:\n"
            "    \"\"\"Doc.\"\"\"\n"
            "\n"
            "    @property\n"
            "    def v(self):\n"
            "        \"\"\"Doc.\"\"\"\n"
            f"{getter_body}\n"
            "        return 0\n"
            "\n"
            "    @v.setter\n"
            "    def v(self, value):\n"
            "        \"\"\"Doc.\"\"\"\n"
            "        self._v = value\n"
        )
    before = module(body)
    _repo(tmp_path, monkeypatch, {"m.py": before}, {"m.py": before.replace("return 0", "return -1")})
    fails, warns, units = gate.review("origin/main")
    assert [(u.name, u.base_complexity) for u in units] == [("C.v", 13)]
    assert fails == [] and warns == []


def test_a_secret_both_committed_and_still_present_is_reported_once(tmp_path, monkeypatch):
    """The working-tree diff and the commit scan see the same line: one finding."""
    _repo(tmp_path, monkeypatch, {"a.txt": "x\n"}, {})
    (tmp_path / "a.txt").write_text("x\n" + _join("ghp_", "Q" * 30) + "\n")
    _git(tmp_path, "commit", "-q", "-am", "still here")
    fails = gate.review("origin/main")[0]
    assert fails.count("SECRET-LIKE (GitHub token) added in a.txt") == 1


def test_fan_out_does_not_count_calls_inside_nested_functions(tmp_path, monkeypatch):
    """Callees added only to an inner function grow the inner unit, not the outer one."""
    inner_calls = "\n".join(f"        f{i}()" for i in range(13))
    source = f"def outer():\n    \"\"\"Doc.\"\"\"\n    def inner():\n        \"\"\"Doc.\"\"\"\n{inner_calls}\n    return inner\n"
    _repo(tmp_path, monkeypatch, {"m.py": "x = 1\n"}, {"m.py": source})
    by_name = {u.name: u.fan_out for u in gate.collect_units("origin/main")[0]}
    assert by_name == {"outer": 0, "outer.inner": 13}


@needs_tree_sitter
def test_an_edit_to_the_jsdoc_alone_touches_the_function(tmp_path, monkeypatch):
    """Turning /** into /* above an unchanged branching function must fail the gate."""
    base = "/** Doc. */\nexport function f(x: number) {\n  return x ? 1 : 2;\n}\n"
    _repo(tmp_path, monkeypatch, {"a.ts": base}, {"a.ts": base.replace("/** Doc. */", "/* Doc. */")})
    fails, _, units = gate.review("origin/main")
    assert [(u.name, u.start) for u in units] == [("f", 2)]
    assert fails == ["DOCSTRING missing (complexity 2): a.ts:2 f"]


@pytest.mark.parametrize("conflict", [False, True])
def test_merging_main_into_the_branch_does_not_blame_mains_own_lines(tmp_path, monkeypatch, conflict):
    """A merge contributes only its resolution: main's secret-shaped line is not the branch's,
    also when a conflict hunk keeps it next to the branch's own line."""
    fixture = _join("ghp_", "M" * 30) + "\n"
    _repo(tmp_path, monkeypatch, {"a.txt": "x\n"}, {})
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    (tmp_path / ("a.txt" if conflict else "f.txt")).write_text("feature\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "feature work")
    _git(tmp_path, "checkout", "-q", "main")
    (tmp_path / ("a.txt" if conflict else "m.txt")).write_text(fixture)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "main only")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(tmp_path, "checkout", "-q", "feature")
    subprocess.run(["git", "merge", "-q", "--no-edit", "main"], cwd=tmp_path, capture_output=True)
    if conflict:  # keep both sides' lines, add nothing new
        (tmp_path / "a.txt").write_text(fixture + "feature\n")
        _git(tmp_path, "commit", "-q", "-am", "merge main, keep both")
    # Only the branch's own commit adds a line; the merge adds nothing of its own.
    assert gate._committed_added_text(gate.merge_base("origin/main")) == [("a.txt" if conflict else "f.txt", "feature")]
    assert not [f for f in gate.review("origin/main")[0] if f.startswith("SECRET-LIKE")]


def test_python_functions_lists_every_def_in_source_order_with_qualified_names():
    """Nested defs, methods and duplicate names (property getter + setter) all appear, in order."""
    source = textwrap.dedent("""
        def top():
            def inner():
                pass
        class C:
            @property
            def v(self):
                pass
            @v.setter
            def v(self, value):
                pass
        async def later():
            pass
    """)
    assert [(name, node.lineno) for name, node in gate.python_functions(source)] == [
        ("top", 2), ("top.inner", 3), ("C.v", 7), ("C.v", 10), ("later", 12)]
