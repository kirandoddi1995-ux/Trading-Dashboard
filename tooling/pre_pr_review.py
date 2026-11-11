"""Pre-PR review gate: catch what the PR review bots flag, before pushing.

The PR bots on this repository check things the test suite does not:
  * CodeRabbit "Docstring Coverage": functions touched by the diff with cyclomatic
    complexity >= 2 need a docstring/JSDoc (threshold 80 %; this gate wants 100 %).
  * MergeHarbor "test gap": a changed function that no test executes.
  * Graphify "health": complexity / fan-out of changed functions growing.
  * Secret scanning and pyflakes.
Run this on the branch before every push. It reads git only; it never pushes or
calls the network. It reviews what the push would carry: the working tree and every
commit since the merge base with --base (default origin/main), so main's own newer
changes are never blamed on the branch and a secret committed then removed still fails.

    python -m pip install -r tooling/requirements-review.txt   # once
    python tooling/pre_pr_review.py                             # diff vs origin/main
    python tooling/pre_pr_review.py --coverage tests/test_x.py tests/test_y.py

Exit status 1 when a FAIL is found: a missing docstring/JSDoc on a named function,
a pyflakes message, secret-like added text, an unparsable changed file, or (with
--coverage) a changed Python function whose body no test function executes, or a
failing coverage test run. WARN lines (complexity, fan-out, undocumented anonymous
callbacks) do not fail the gate; they are for the review. A missing review tool
(pyflakes, tree-sitter, coverage.py) stops the gate with an install hint; it never
passes silently.

Scope: Python (.py) and TypeScript/JavaScript (.ts .tsx .mts .cts .js .jsx .mjs .cjs).
Python embedded in workflow YAML is not parsed: keep logic in modules (as
archive_on_time_check.py does) so this gate and coverage see it.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_HINT = "python -m pip install -r tooling/requirements-review.txt"
COMPLEXITY_WARN = 10
FAN_OUT_WARN = 12
SECRET_PATTERNS = {
    "GitHub token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),
    "AWS key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "Anthropic key": re.compile(r"\bsk-ant-[A-Za-z0-9]+-[A-Za-z0-9_-]{20,}"),
    "OpenAI-style key": re.compile(r"\bsk-(?!ant-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{32,}"),
    "database URL with password": re.compile(r"\bpostgres(?:ql)?(?:\+\w+)?://[^\s:/@'\"]+:[^\s@/'\"]+@"),
    "Google OAuth client secret": re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}"),
    "Google access token": re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}"),
    "Google refresh token": re.compile(r"(?<![A-Za-z0-9/])1//[0-9A-Za-z_-]{20,}"),
    "Supabase secret key": re.compile(r"\bsb_secret_[A-Za-z0-9_-]{20,}"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "Telegram bot token": re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}(?![\w-])"),
    "Supabase access token": re.compile(r"\bsbp_[0-9a-f]{40}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}(?![\w-])"),
    "Stripe live key": re.compile(r"\b[rs]k_live_[0-9A-Za-z]{24,}\b"),
}


@dataclass
class Unit:
    """One function (Python def or TypeScript function) touched by the diff."""

    path: str
    name: str
    start: int
    end: int
    complexity: int
    documented: bool
    fan_out: int = 0
    base_complexity: int | None = None
    base_fan_out: int | None = None
    covered: bool | None = None
    body_start: int | None = None  # first statement after the docstring (coverage)
    anonymous: bool = False  # TS callbacks / returned functions: JSDoc gaps only WARN
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ git ---

# Paths come from `-z` listings and are passed back verbatim: never quoted, never
# read as glob/pathspec magic. Hunk headers (@@) are the only diff text parsed, so
# diff.noprefix and similar user settings cannot change the result.
GIT_OPTIONS = ("-c", "core.quotePath=false", "--literal-pathspecs")
DIFF = ("diff", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames", "-U0")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def git(*args: str) -> str:
    """Run a read-only git command in the repository and return stdout (UTF-8)."""
    return subprocess.run(["git", *GIT_OPTIONS, *args], cwd=ROOT, capture_output=True,
                          encoding="utf-8", errors="replace", check=True).stdout


def merge_base(base: str) -> str:
    """The commit the branch forked from `base` (what a PR diff is computed against)."""
    try:
        return git("merge-base", base, "HEAD").strip()
    except subprocess.CalledProcessError:
        raise SystemExit(f"No merge base with {base}: run `git fetch origin main` "
                         "(in a shallow clone: `git fetch --unshallow`), or pass --base.") from None


def changed_paths(base: str) -> tuple[list[str], list[str]]:
    """(tracked paths changed versus `base`, untracked paths), exactly as git stores them."""
    tracked = git("diff", "--name-only", "-z", "--no-renames", base, "--").split("\0")
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return [path for path in tracked if path], [path for path in untracked if path]


def _hunk_lines(diff: str) -> set[int]:
    """New-file lines each hunk touches; a pure deletion touches the lines on both sides."""
    touched: set[int] = set()
    for line in diff.splitlines():
        match = HUNK.match(line)
        if match:
            start, count = int(match.group(1)), int(match.group(2) or 1)
            touched.update(range(start, start + count) if count else {max(start, 1), start + 1})
    return touched


def _untracked_text(path: str) -> str | None:
    """An untracked file's text, or None for a binary file."""
    data = (ROOT / path).read_bytes()
    return None if b"\0" in data else data.decode("utf-8", errors="replace")


def changed_lines(base: str) -> dict[str, set[int]]:
    """{path: touched line numbers in the working tree} versus `base`, untracked files whole."""
    tracked, untracked = changed_paths(base)
    out = {path: _hunk_lines(git(*DIFF, base, "--", path))
           for path in tracked if (ROOT / path).is_file()}
    for path in untracked:
        text = _untracked_text(path)
        if text is not None:
            out[path] = set(range(1, text.count("\n") + 2))
    return out


def _added_lines(diff: str) -> list[str]:
    """Lines a -U0 diff adds (everything after the first hunk header that starts with +)."""
    out, in_hunk = [], False
    for line in diff.splitlines():
        in_hunk = in_hunk or line.startswith("@@")
        if in_hunk and line.startswith("+"):
            out.append(line[1:])
    return out


def _committed_added_text(base: str) -> list[tuple[str, str]]:
    """(path, line) each commit in base..HEAD adds versus its first parent, merges included
    (text typed while resolving a merge), so a secret removed later still counts."""
    out = []
    for commit in git("rev-list", f"{base}..HEAD").split():
        parent = f"{commit}^1"
        paths = git("diff", "--name-only", "-z", "--no-renames", parent, commit, "--").split("\0")
        for path in filter(None, paths):
            out.extend((path, line) for line in _added_lines(git(*DIFF, parent, commit, "--", path)))
    return out


def added_text(base: str) -> list[tuple[str, str]]:
    """(path, line) for every added line: working tree vs base, untracked files, and each commit since base."""
    tracked, untracked = changed_paths(base)
    out = []
    for path in tracked:
        out.extend((path, line) for line in _added_lines(git(*DIFF, base, "--", path)))
    for path in untracked:
        text = _untracked_text(path)
        out.extend((path, line) for line in (text or "").splitlines())
    return out + _committed_added_text(base)


def _base_text(base: str, path: str) -> str | None:
    """`path` as it is in `base`, or None when it is new."""
    try:
        return git("show", f"{base}:{path}")
    except subprocess.CalledProcessError:
        return None


# --------------------------------------------------------------- Python ---

def python_complexity(node: ast.AST) -> int:
    """McCabe-style cyclomatic complexity of one function body (nested defs excluded)."""
    score = 1
    stack = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp,
                              ast.ExceptHandler, ast.Assert, ast.match_case)):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            score += 1 + len(child.ifs)
        stack.extend(ast.iter_child_nodes(child))
    return score


def python_fan_out(node: ast.AST) -> int:
    """Distinct called names (`f(...)`, `obj.method(...)`) in one function body."""
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return len(names)


def python_functions(source: str) -> list[tuple[str, ast.AST]]:
    """(qualified name, def node) for every function and method, duplicates included
    (a @property getter and its setter share a name)."""
    out: list[tuple[str, ast.AST]] = []

    def visit(node, prefix):
        """Collect defs under `node`, qualifying nested names with `prefix`."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                out.append((name, child))
                visit(child, f"{name}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            else:
                visit(child, prefix)
    visit(ast.parse(source), "")
    return out


def _python_base_defs(path: str, base: str) -> dict[str, ast.AST]:
    """{(qualified name, occurrence): def node} in `base` ({} for a new or unparsable file).

    The occurrence number keeps a property getter compared with the old getter, not the setter.
    """
    source = _base_text(base, path)
    try:
        return _numbered(python_functions(source)) if source is not None else {}
    except SyntaxError:
        return {}


def _numbered(functions: list[tuple[str, ast.AST]]) -> dict[tuple[str, int], ast.AST]:
    """{(name, how many earlier defs share the name): node}, in source order."""
    seen: dict[str, int] = {}
    out = {}
    for name, node in functions:
        out[(name, seen.get(name, 0))] = node
        seen[name] = seen.get(name, 0) + 1
    return out


def _python_span(node: ast.AST) -> set[int]:
    """Lines of a def, its decorators included (a decorator-only edit touches the function)."""
    first = min([decorator.lineno for decorator in node.decorator_list] + [node.lineno])
    return set(range(first, node.end_lineno + 1))


def python_units(path: str, lines: set[int], base: str) -> list[Unit]:
    """Touched Python functions with complexity, docstring and base-version metrics."""
    base_defs = _python_base_defs(path, base)
    current = _numbered(python_functions((ROOT / path).read_text(encoding="utf-8")))
    return [_python_unit(path, name, node, base_defs.get((name, occurrence)))
            for (name, occurrence), node in current.items() if _python_span(node) & lines]


def _is_stub_statement(statement: ast.stmt) -> bool:
    """`pass`, `...` or a bare string: nothing coverage can record as run."""
    return isinstance(statement, ast.Pass) or (
        isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
        and (statement.value.value is Ellipsis or isinstance(statement.value.value, str)))


def _python_unit(path: str, name: str, node: ast.AST, prior: ast.AST | None) -> Unit:
    """One Python function's metrics, with the base version's for comparison."""
    documented = ast.get_docstring(node) is not None
    body = node.body[1:] if documented else node.body
    # A stub (docstring, pass or ... only) has no line coverage can record: no TEST GAP.
    body_start = None if all(_is_stub_statement(statement) for statement in body) else body[0].lineno
    return Unit(
        path, name, node.lineno, node.end_lineno, python_complexity(node), documented,
        python_fan_out(node), python_complexity(prior) if prior else None,
        python_fan_out(prior) if prior else None, body_start=body_start,
    )


# ----------------------------------------------------------- TypeScript ---

TS_SUFFIXES = (".ts", ".mts", ".cts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
TS_FUNCTION_TYPES = {"function_declaration", "generator_function_declaration", "function_expression",
                     "generator_function", "arrow_function", "method_definition"}
TS_BRANCH_TYPES = {"if_statement", "for_statement", "for_in_statement", "while_statement",
                   "do_statement", "catch_clause", "ternary_expression", "switch_case"}
TS_BRANCH_OPERATORS = {"&&", "||", "??"}
TS_TRANSPARENT = {"parenthesized_expression", "as_expression", "satisfies_expression", "non_null_expression"}
# Nodes between a function and the statement its JSDoc sits above.
TS_DOC_WRAPPERS = TS_TRANSPARENT | {"variable_declarator", "lexical_declaration", "variable_declaration",
                                    "export_statement", "return_statement", "assignment_expression",
                                    "expression_statement", "public_field_definition", "pair"}
TS_NAME_FIELDS = {"variable_declarator": "name", "pair": "key", "assignment_expression": "left",
                  "public_field_definition": "name"}


def _ts_parser(path: str):
    """A tree-sitter parser for `path` (TSX grammar for .tsx and JavaScript files)."""
    try:
        import tree_sitter
        import tree_sitter_typescript
    except ImportError:
        raise SystemExit(f"TypeScript checks need tree-sitter: {INSTALL_HINT}") from None
    typescript = path.endswith((".ts", ".mts", ".cts"))
    grammar = tree_sitter_typescript.language_typescript() if typescript else tree_sitter_typescript.language_tsx()
    return tree_sitter.Parser(tree_sitter.Language(grammar))


def _ts_is_function(node) -> bool:
    """True for a named function-like node (the bare `function` keyword token is not one)."""
    return node.is_named and node.type in TS_FUNCTION_TYPES


def _ts_context(node):
    """The nearest ancestor that is not a transparent wrapper (parentheses, `as`, `satisfies`, `!`)."""
    parent = node.parent
    while parent is not None and parent.type in TS_TRANSPARENT:
        parent = parent.parent
    return parent


def _ts_declared_name(node) -> str | None:
    """The name a function is declared, assigned or exported under; None when anonymous."""
    own = node.child_by_field_name("name")
    if own is not None:
        return own.text.decode()
    parent = _ts_context(node)
    if parent is not None and parent.type == "export_statement":
        return "default"
    field_name = TS_NAME_FIELDS.get(parent.type) if parent is not None else None
    named = parent.child_by_field_name(field_name) if field_name else None
    return named.text.decode() if named is not None else None


def _ts_anonymous_label(node) -> str:
    """A readable label for an anonymous function: the call it is passed to, or how it is used."""
    parent = _ts_context(node)
    if parent is not None and parent.type == "arguments" and parent.parent is not None:
        callee = parent.parent.child_by_field_name("function")
        first = parent.named_children[0] if parent.named_children else None
        label = first.text.decode()[:40] if first is not None and first.type == "string" else ""
        return f"<callback of {callee.text.decode() if callee is not None else '?'}({label})>"
    return "<returned function>" if parent is not None and parent.type == "return_statement" else "<anonymous>"


def _ts_name(node) -> tuple[str, bool]:
    """(name, anonymous) of a function node."""
    declared = _ts_declared_name(node)
    return (declared, False) if declared is not None else (_ts_anonymous_label(node), True)


def _ts_qualified(node, name: str) -> str:
    """`name` prefixed with the enclosing classes and named functions (Outer.inner)."""
    parts, parent = [name], node.parent
    while parent is not None:
        if _ts_is_function(parent) or parent.type in {"class_declaration", "class", "abstract_class_declaration"}:
            label = _ts_name(parent)[0] if _ts_is_function(parent) else (
                parent.child_by_field_name("name").text.decode() if parent.child_by_field_name("name") else "<class>")
            parts.append(label)
        parent = parent.parent
    return ".".join(reversed(parts))


def _ts_documented(node) -> bool:
    """True when a /** JSDoc */ comment directly precedes the function's statement."""
    anchor = node
    while anchor.parent is not None and anchor.parent.type in TS_DOC_WRAPPERS:
        anchor = anchor.parent
    previous = anchor.prev_named_sibling
    return previous is not None and previous.type == "comment" and previous.text.startswith(b"/**")


def _ts_complexity(node) -> int:
    """Cyclomatic complexity of one function: branches, loops, catch, ternary, && || ?? (nested functions excluded)."""
    score, stack = 1, list(node.children)
    while stack:
        child = stack.pop()
        if _ts_is_function(child):
            continue
        if child.type in TS_BRANCH_TYPES:
            score += 1
        elif child.type == "binary_expression":
            operator = child.child_by_field_name("operator")
            score += operator is not None and operator.type in TS_BRANCH_OPERATORS
        stack.extend(child.children)
    return score


def _ts_functions(path: str, source: str) -> tuple[list[tuple], int | None]:
    """([(qualified name, anonymous, node)], first parse-error line or None) for one file."""
    tree = _ts_parser(path).parse(source.encode("utf-8"))
    found, error_line, stack = [], None, [tree.root_node]
    while stack:
        node = stack.pop()
        if (node.type == "ERROR" or node.is_missing) and error_line is None:
            error_line = node.start_point[0] + 1
        if _ts_is_function(node):
            name, anonymous = _ts_name(node)
            found.append((_ts_qualified(node, name), anonymous, node))
        stack.extend(reversed(node.children))
    return found, error_line


def _ts_base_complexity(path: str, base: str) -> dict[str, int]:
    """{qualified name: complexity} in `base`; anonymous functions only when their label is unique."""
    source = _base_text(base, path)
    functions = _ts_functions(path, source)[0] if source is not None else []
    counts: dict[str, int] = {}
    for name, _, _ in functions:
        counts[name] = counts.get(name, 0) + 1
    return {name: _ts_complexity(node) for name, anonymous, node in functions
            if not anonymous or counts[name] == 1}


def ts_units(path: str, lines: set[int], base: str = "origin/main") -> tuple[list[Unit], list[str]]:
    """Touched TypeScript/JavaScript functions (complexity, base value, JSDoc) and parse failures."""
    functions, error_line = _ts_functions(path, (ROOT / path).read_text(encoding="utf-8"))
    base_by_name = _ts_base_complexity(path, base)
    units = []
    for name, anonymous, node in functions:
        start, end = node.start_point[0] + 1, node.end_point[0] + 1
        if not set(range(start, end + 1)) & lines:
            continue
        units.append(Unit(path, name, start, end, _ts_complexity(node), _ts_documented(node),
                          base_complexity=base_by_name.get(name), anonymous=anonymous))
    fails = [f"{path}: TypeScript parse error near line {error_line}"] if error_line else []
    return units, fails


# --------------------------------------------------------------- checks ---

def _test_module_names(tests: list[str]) -> set[str]:
    """Module names of the given test files (directories expand to their test_*.py files)."""
    names = set()
    for test in tests:
        path = ROOT / test.split("::", 1)[0]
        files = [*path.rglob("test_*.py"), *path.rglob("*_test.py")] if path.is_dir() else [path]
        names.update(file.stem for file in files)
    return names


def _from_a_test(context: str, modules: set[str]) -> bool:
    """True for a coverage context opened by a function in one of the test modules.

    coverage.py opens a context for ANY function whose name starts with "test", so a
    production `testable()` run at import would otherwise count as tested.
    """
    return bool(context) and bool(set(context.split(".")) & modules)


def _coverage_report(tests: list[str], paths: list[str]) -> dict:
    """Run `tests` under coverage.py with per-test contexts; return the JSON report's `files`.

    Stops the gate if coverage.py is missing or the test run fails.
    """
    workdir = Path(tempfile.mkdtemp())
    rcfile = workdir / "coveragerc"
    rcfile.write_text(f"[run]\ndata_file = {workdir / 'coverage.data'}\ndynamic_context = test_function\n")
    run = subprocess.run([sys.executable, "-m", "coverage", "run", f"--rcfile={rcfile}",
                          "--include=" + ",".join(paths), "-m", "pytest", "-q", "-p", "no:cacheprovider",
                          *tests], cwd=ROOT, capture_output=True, text=True)
    if "No module named coverage" in run.stderr:
        raise SystemExit(f"coverage is not installed: {INSTALL_HINT}")
    if run.returncode != 0:
        raise SystemExit(f"coverage test run failed (exit {run.returncode}); a failing test proves nothing:\n"
                         + (run.stdout + run.stderr)[-2000:])
    report = subprocess.run([sys.executable, "-m", "coverage", "json", f"--rcfile={rcfile}", "--show-contexts",
                             "-o", "-"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return json.loads(report)["files"]


def coverage_map(tests: list[str], paths: list[str]) -> dict[str, set[int]]:
    """{path: lines executed inside a test function} from running `tests` under coverage.py.

    Lines run only at import or collection time, or under a non-test function whose
    name starts with "test", do not count.
    """
    modules = _test_module_names(tests)
    return {path: {int(line) for line, contexts in info.get("contexts", {}).items()
                   if any(_from_a_test(context, modules) for context in contexts)}
            for path, info in _coverage_report(tests, paths).items()}


def collect_units(base: str, lines: dict[str, set[int]] | None = None) -> tuple[list[Unit], list[str]]:
    """Touched functions in changed Python/TypeScript files, plus parse failures."""
    units, fails = [], []
    for path, touched in sorted((changed_lines(base) if lines is None else lines).items()):
        if not (ROOT / path).is_file():
            continue
        if path.endswith(".py"):
            try:
                units += python_units(path, touched, base)
            except SyntaxError as exc:
                fails.append(f"{path}: syntax error {exc}")
        elif path.endswith(TS_SUFFIXES):
            found, parse_fails = ts_units(path, touched, base)
            units += found
            fails += parse_fails
    return units, fails


def unit_findings(units: list[Unit]) -> tuple[list[str], list[str]]:
    """Docstring failures (named functions) and warnings (anonymous gaps, growing complexity/fan-out)."""
    fails, warns = [], []
    for unit in units:
        where = f"{unit.path}:{unit.start} {unit.name}"
        if unit.complexity >= 2 and not unit.documented:
            (warns if unit.anonymous else fails).append(
                f"DOCSTRING missing (complexity {unit.complexity}): {where}")
        warns += _growth_warnings(unit, where)
    return fails, warns


def _growth_warnings(unit: Unit, where: str) -> list[str]:
    """Complexity / fan-out above the bar and larger than in the base version."""
    warns = []
    if unit.complexity > COMPLEXITY_WARN and (unit.base_complexity or 0) < unit.complexity:
        warns.append(f"COMPLEXITY {unit.base_complexity} -> {unit.complexity}: {where}")
    if unit.fan_out > FAN_OUT_WARN and (unit.base_fan_out or 0) < unit.fan_out:
        warns.append(f"FAN-OUT {unit.base_fan_out} -> {unit.fan_out} callees: {where}")
    return warns


def pyflakes_findings(python_files: list[str]) -> list[str]:
    """pyflakes messages (warnings and syntax errors) for the changed Python files."""
    if not python_files:
        return []
    flakes = subprocess.run([sys.executable, "-m", "pyflakes", *python_files], cwd=ROOT,
                            capture_output=True, text=True)
    if "No module named pyflakes" in flakes.stderr:
        raise SystemExit(f"pyflakes is not installed: {INSTALL_HINT}")
    messages = [f"PYFLAKES {line}" for line in (flakes.stdout + flakes.stderr).strip().splitlines()]
    if flakes.returncode != 0 and not messages:
        messages = [f"PYFLAKES exited {flakes.returncode} without output"]
    return messages


def secret_findings(base: str) -> list[str]:
    """Added lines that look like a credential (one finding per kind and file)."""
    return list(dict.fromkeys(f"SECRET-LIKE ({label}) added in {path}" for path, text in added_text(base)
                              for label, pattern in SECRET_PATTERNS.items() if pattern.search(text)))


def coverage_findings(units: list[Unit], tests: list[str]) -> list[str]:
    """Changed non-test Python functions whose body no test function executes."""
    targets = sorted({u.path for u in units if u.path.endswith(".py") and not u.path.startswith("tests/")})
    executed = coverage_map(tests, targets) if targets else {}
    fails = []
    for unit in units:
        if unit.path not in targets or unit.body_start is None:  # stubs have nothing to run
            continue
        # The `def` line runs at import; only a body line run by a test proves a call.
        body = set(range(unit.body_start, unit.end + 1))
        unit.covered = bool(executed.get(unit.path, set()) & body)
        if not unit.covered:
            fails.append(f"TEST GAP no test runs {unit.path}:{unit.start} {unit.name}")
    return fails


def review(base: str, coverage_tests: list[str] | None = None) -> tuple[list[str], list[str], list[Unit]]:
    """Return (fails, warns, units) for the working tree and commits since the merge base with `base`."""
    base = merge_base(base)
    lines = changed_lines(base)
    units, fails = collect_units(base, lines)
    unit_fails, warns = unit_findings(units)
    fails += unit_fails
    fails += pyflakes_findings(sorted(path for path in lines if path.endswith(".py")))
    fails += secret_findings(base)
    if coverage_tests:
        fails += coverage_findings(units, coverage_tests)
    return fails, warns, units


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; prints a short report and returns the exit status."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--coverage", nargs="+", metavar="TEST", help="tests to run under coverage.py")
    args = parser.parse_args(argv)
    fails, warns, units = review(args.base, args.coverage)
    scored = [u for u in units if u.complexity >= 2]
    documented = sum(u.documented for u in scored)
    print(f"Touched functions: {len(units)}; complexity >= 2: {len(scored)}; "
          f"documented: {documented} ({100 * documented / len(scored):.0f}%)" if scored
          else f"Touched functions: {len(units)}; none with complexity >= 2")
    for line in warns:
        print("WARN", line)
    for line in fails:
        print("FAIL", line)
    print("RESULT", "FAIL" if fails else "PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
