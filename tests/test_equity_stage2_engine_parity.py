"""Drift guard: equity_stage2_engine.py must stay an exact copy of app.py's
Stage-2 scoring math, except for an explicit, enumerated set of signature
changes (see ALLOWED_DIFFS).

Why a copy at all: app.py's bytes are pinned by equity_real_report.APP_SHA256
(study evidence chain), so the engine cannot be wired in by editing app.py.
This test is what makes the copy safe: change one side without the other and
it fails, naming the definition and showing both versions.

app.py is never imported (it is a Streamlit script); it is parsed as source.
"""
from __future__ import annotations

import ast
import builtins
import copy
import symtable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
ENGINE = ROOT / "equity_stage2_engine.py"

# Every top-level definition the engine carries. Each must exist exactly once
# in app.py and match it (after ALLOWED_DIFFS). Adding a definition to the
# engine without listing it here fails test_engine_defines_exactly_shared_set.
SHARED = (
    "LOGGER", "IST", "_MARKET_OPEN_MIN", "_MARKET_CLOSE_MIN", "_SESSION_MINUTES",
    "NSE_SECTOR_MAP", "get_ticker_sector", "get_sector_bucket", "_clamp", "_scale",
    "_percentile_rank", "_session_elapsed_fraction", "classify_ema_trend",
    "classify_macd", "compute_bollinger_percent_b", "get_weekly_trend",
    "relative_strength_vs_nifty", "compute_trend_quality_score",
    "compute_volume_quality_score", "compute_breakout_quality_score",
    "derive_long_trade_levels", "_execution_cost_breakdown",
)


# --- the only permitted differences, as explicit transforms on app.py's AST ---

def _insert_param(name: str, position: int):
    def apply(fn: ast.FunctionDef) -> int:
        n_args = len(fn.args.args)
        if position > n_args - len(fn.args.defaults):
            raise AssertionError(f"{fn.name}: cannot insert required param after defaulted ones")
        fn.args.args.insert(position, ast.arg(arg=name))
        return 1
    apply.label = f"insert required param {name!r} at position {position}"
    return apply


def _append_param(name: str, default):
    def apply(fn: ast.FunctionDef) -> int:
        fn.args.args.append(ast.arg(arg=name))
        fn.args.defaults.append(ast.Constant(value=default))
        return 1
    apply.label = f"append param {name}={default!r}"
    return apply


def _rename_global(old: str, new: str, expected: int):
    def apply(fn: ast.FunctionDef) -> int:
        hits = 0
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and node.id == old:
                node.id = new
                hits += 1
        assert hits == expected, f"{fn.name}: expected {expected} uses of {old}, found {hits} — app.py changed; re-review the engine copy"
        return hits
    apply.label = f"rename {old} -> {new} ({expected}x)"
    return apply


def _add_call_keyword(callee: str, keyword: str, expected: int):
    def apply(fn: ast.FunctionDef) -> int:
        hits = 0
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == callee:
                node.keywords.append(ast.keyword(arg=keyword, value=ast.Name(id=keyword, ctx=ast.Load())))
                hits += 1
        assert hits == expected, f"{fn.name}: expected {expected} calls to {callee}, found {hits} — app.py changed; re-review the engine copy"
        return hits
    apply.label = f"pass {keyword}={keyword} to {callee}() ({expected}x)"
    return apply


ALLOWED_DIFFS = {
    # app.py read the page-scoped global `nifty_hist_df`; engine takes it explicitly.
    "relative_strength_vs_nifty": (_insert_param("nifty_hist_df", 1),),
    # app.py read the page-scoped global `MARKET_OPEN`; engine takes it explicitly.
    "compute_volume_quality_score": (
        _append_param("market_open", False),
        _rename_global("MARKET_OPEN", "market_open", expected=2),
    ),
    "compute_breakout_quality_score": (
        _append_param("market_open", False),
        _add_call_keyword("compute_volume_quality_score", "market_open", expected=1),
    ),
}


# --- helpers ---

def _defs(path: Path) -> dict[str, list[ast.stmt]]:
    found: dict[str, list[ast.stmt]] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.setdefault(node.name, []).append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        found.setdefault(name.id, []).append(node)
    return found


def _import_bindings(path: Path) -> dict[str, str]:
    bindings = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            for alias in node.names:
                bindings[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return bindings


def _without_docstring(node: ast.stmt) -> ast.stmt:
    node = copy.deepcopy(node)
    body = getattr(node, "body", None)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        node.body = body[1:] or [ast.Pass()]
    return node


APP_DEFS = _defs(APP)
ENGINE_DEFS = _defs(ENGINE)


# --- tests ---

def test_engine_defines_exactly_shared_set():
    assert set(ENGINE_DEFS) == set(SHARED), (
        f"engine-only: {sorted(set(ENGINE_DEFS) - set(SHARED))}, "
        f"missing: {sorted(set(SHARED) - set(ENGINE_DEFS))}")


def test_allowed_diffs_only_name_shared_functions():
    assert set(ALLOWED_DIFFS) <= set(SHARED)


@pytest.mark.parametrize("name", SHARED)
def test_definition_matches_app_original(name):
    assert len(APP_DEFS.get(name, [])) == 1, f"app.py must define {name} exactly once at top level"
    assert len(ENGINE_DEFS.get(name, [])) == 1, f"engine must define {name} exactly once"
    expected = copy.deepcopy(APP_DEFS[name][0])
    for transform in ALLOWED_DIFFS.get(name, ()):
        transform(expected)
    expected = _without_docstring(expected)
    actual = _without_docstring(ENGINE_DEFS[name][0])
    if ast.dump(expected) != ast.dump(actual):
        allowed = [t.label for t in ALLOWED_DIFFS.get(name, ())] or ["none"]
        pytest.fail(
            f"{name} drifted from app.py. Allowed differences: {allowed}.\n"
            f"--- app.py (after allowed diffs) ---\n{ast.unparse(expected)}\n"
            f"--- equity_stage2_engine.py ---\n{ast.unparse(actual)}")


def test_app_binds_each_shared_name_exactly_once_anywhere():
    # A second binding anywhere in app.py (nested block, `global` write, local
    # shadow) would make "which version is live" ambiguous; the top-level
    # comparison above would silently compare against the wrong one.
    counts = {name: 0 for name in SHARED}
    for node in ast.walk(ast.parse(APP.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in counts:
            counts[node.name] += 1
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in counts:
            counts[node.id] += 1
        elif isinstance(node, ast.arg) and node.arg in counts:
            counts[node.arg] += 1
    assert all(c == 1 for c in counts.values()), {n: c for n, c in counts.items() if c != 1}


def test_engine_free_names_resolve_at_module_level():
    source = ENGINE.read_text(encoding="utf-8")
    module_names = set(ENGINE_DEFS) | set(_import_bindings(ENGINE)) | set(dir(builtins))
    unresolved = []

    def walk(table):
        for child in table.get_children():
            for symbol in child.get_symbols():
                if symbol.is_referenced() and symbol.is_global() and symbol.get_name() not in module_names:
                    unresolved.append(f"{child.get_name()}: {symbol.get_name()}")
            walk(child)

    walk(symtable.symtable(source, str(ENGINE), "exec"))
    assert not unresolved, f"names that would raise NameError at runtime: {unresolved}"


def test_engine_imports_bind_same_modules_as_app():
    app_imports, engine_imports = _import_bindings(APP), _import_bindings(ENGINE)
    mismatched = {name: (app_imports.get(name), module) for name, module in engine_imports.items()
                  if app_imports.get(name) != module}
    assert not mismatched, f"engine name -> (app.py module, engine module): {mismatched}"
