"""Drift guard: equity_stage2_decision.evaluate_stage2 must stay a verbatim copy of
the decision core of app.py's scan-page `evaluate_stock`.

The core is app.py's `try:` body from its first statement through
`timing = trade_contracts.build_trade_timing(...)`, plus the `except` handler.
Allowed differences are explicit AST transforms (ALLOWED_TRANSFORMS). Anything
else - a changed threshold, a new or removed gate, a reordered statement - fails
here with both versions shown. Also guarded:
* app.py's evaluate_stock outside the copied core (setup before `try:`, `_reject`,
  `_archive_stage2`, live-only tail) is pinned by digest;
* the engine module/function have no code outside the copied slice;
* every module-level name the slice uses is bound exactly once at app.py module
  scope and imported by the engine from the same origin (or is a parity-guarded
  equity_stage2_engine copy), so a rebinding cannot change which object runs.
Mutation-tested: each of these guards was shown to fail on an injected drift.

app.py is never imported (it is a Streamlit script); it is parsed as source.
"""
from __future__ import annotations

import ast
import builtins
import copy
import symtable
from pathlib import Path

import pytest

from test_equity_stage2_engine_parity import SHARED as ENGINE_SHARED

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")
DECISION_SOURCE = (ROOT / "equity_stage2_decision.py").read_text(encoding="utf-8")
APP_TREE = ast.parse(APP_SOURCE)
DECISION_TREE = ast.parse(DECISION_SOURCE)


def _single_function(tree, name):
    """The one FunctionDef called `name` anywhere in `tree` (fails if not exactly one)."""
    found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(found) == 1, f"expected exactly one def {name}, found {len(found)}"
    return found[0]


def _single_try(function):
    """The one top-level `try:` statement in `function`'s body."""
    tries = [s for s in function.body if isinstance(s, ast.Try)]
    assert len(tries) == 1, f"{function.name}: expected one top-level try, found {len(tries)}"
    return tries[0]


def _assigns(stmt, name):
    """True if `stmt` is an assignment whose targets include the plain name `name`."""
    return isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets)


APP_FN = _single_function(APP_TREE, "evaluate_stock")
APP_TRY = _single_try(APP_FN)
SLICE_END = next(i for i, s in enumerate(APP_TRY.body) if _assigns(s, "timing"))
APP_SLICE = APP_TRY.body[:SLICE_END + 1]
APP_TAIL = APP_TRY.body[SLICE_END + 1:]
ENGINE_FN = _single_function(DECISION_TREE, "evaluate_stage2")
ENGINE_TRY = _single_try(ENGINE_FN)


# --- the only permitted differences, applied to a copy of app.py's slice ---

def _rename(old, new, expected):
    """Rename every Name `old` to `new`; app.py must use it exactly `expected` times."""
    def apply(tree):
        """Rename in `tree`; return (count as expected, detail)."""
        hits = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == old]
        for node in hits:
            node.id = new
        return len(hits) == expected, f"{len(hits)} uses of {old} (expected {expected})"
    apply.label = f"rename {old} -> {new}"
    return apply


def _calls_passing(tree, function_name):
    """Calls that pass `function_name` as a positional argument (the profile_call wrapper)."""
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and any(isinstance(a, ast.Name) and a.id == function_name for a in n.args)]


def _insert_positional_after(function_name, after_offset, new_name):
    """In profile_call(..., function_name, df, ...), insert `new_name` right after `df`."""
    def apply(tree):
        """Insert the argument in each matching call; return (exactly one call, detail)."""
        calls = _calls_passing(tree, function_name)
        for call in calls:
            position = next(i for i, a in enumerate(call.args)
                            if isinstance(a, ast.Name) and a.id == function_name) + after_offset + 1
            call.args.insert(position, ast.Name(id=new_name, ctx=ast.Load()))
        return len(calls) == 1, f"{len(calls)} calls passing {function_name} (expected 1)"
    apply.label = f"pass {new_name} positionally to {function_name}"
    return apply


def _append_keyword(function_name, keyword):
    """In profile_call(..., function_name, ...), append `keyword=keyword`."""
    def apply(tree):
        """Append the keyword to each matching call; return (exactly one call, detail)."""
        calls = _calls_passing(tree, function_name)
        for call in calls:
            call.keywords.append(ast.keyword(arg=keyword, value=ast.Name(id=keyword, ctx=ast.Load())))
        return len(calls) == 1, f"{len(calls)} calls passing {function_name} (expected 1)"
    apply.label = f"pass {keyword}={keyword} to {function_name}"
    return apply


ALLOWED_TRANSFORMS = (
    _rename("TECHNICAL_FEATURE_STORE", "feature_store", expected=1),
    _rename("MARKET_OPEN", "market_open", expected=1),
    _insert_positional_after("relative_strength_vs_nifty", 1, "nifty_hist_df"),
    _append_keyword("compute_volume_quality_score", "market_open"),
    _append_keyword("compute_breakout_quality_score", "market_open"),
)

# app.py statements after `timing` that are deliberately NOT copied (live-only).
# If app.py adds, removes or reorders any of these, re-review what moved.
EXPECTED_APP_TAIL = (
    "assign:equity_observed_at,equity_received_at,equity_lineage",
    "assign:equity_decision_clock",
    "assign:equity_universe",
    "assign:equity_context",
    "assign:equity_evidence_bundle",
    "expr:observation.observe",
    "assign:equity_governance",
    "if:not equity_governance['allow_trade']",
    "expr:_archive_stage2",
    "return",
)

# Keys the engine adds to the pass record beyond what app.py archives.
ENGINE_EXTRA_RETURN = {
    "action": "action", "action_reason": "action_reason", "timing": "timing",
    "governance_evaluated": "False",
}


def _summary(stmt):
    """Short shape label for one statement (used to pin app.py's live-only tail)."""
    if isinstance(stmt, ast.Assign):
        names = [n.id for t in stmt.targets for n in ast.walk(t) if isinstance(n, ast.Name)]
        return "assign:" + ",".join(names)
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        return "expr:" + ast.unparse(stmt.value.func)
    if isinstance(stmt, ast.If):
        return "if:" + ast.unparse(stmt.test)
    if isinstance(stmt, ast.Return):
        return "return"
    return type(stmt).__name__


SIGNATURE_CHANGED_HELPERS = ("relative_strength_vs_nifty", "compute_volume_quality_score",
                             "compute_breakout_quality_score")
RENAME_TARGETS = ("feature_store", "market_open")


def _transformed_app_slice():
    """app.py's decision slice with ALLOWED_TRANSFORMS applied (fails on unexpected counts)."""
    module = ast.Module(body=copy.deepcopy(APP_SLICE), type_ignores=[])
    names = [n.id for n in ast.walk(module) if isinstance(n, ast.Name)]
    for helper in SIGNATURE_CHANGED_HELPERS:
        # Any second reference (e.g. a direct call) would take the engine helper's
        # default where app.py's version reads a page global.
        assert names.count(helper) == 1, f"{helper} referenced {names.count(helper)}x in app.py's slice"
    for target in RENAME_TARGETS:
        assert target not in names, f"app.py's slice already uses {target}; a rename would merge two names"
    for transform in ALLOWED_TRANSFORMS:
        ok, detail = transform(module)
        assert ok, f"{transform.label}: {detail} - app.py changed; re-review equity_stage2_decision.py"
    return module.body


def _dump(node):
    """Version-stable AST dump (Python 3.13 omits empty fields unless asked)."""
    try:
        return ast.dump(node, show_empty=True)
    except TypeError:  # Python < 3.13 always shows them
        return ast.dump(node)


# sha256 over app.py's evaluate_stock outside the copied core: its signature, every
# statement before the `try:` (local imports, capture object, key lookup,
# _archive_stage2, _reject) and every live-only statement after `timing`.
EXPECTED_APP_OUTSIDE_CORE_SHA256 = "d32b64b1392740598ce35822c5b7a20b38cc773aba4685f128fa6d4c4c0d6302"


def _app_outside_core_digest():
    """Digest of app.py's evaluate_stock minus the copied slice and handler."""
    import hashlib
    parts = [_dump(APP_FN.args)]
    parts += [_dump(s) for s in APP_FN.body[:APP_FN.body.index(APP_TRY)]]
    parts += [_dump(s) for s in APP_TAIL]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _module_scope_bindings(tree):
    """{name: [binding kinds]} for every binding that can change a module-level name:
    statements executed at module scope (including inside if/for/while/try/with
    blocks, not inside def/class bodies), plus any `global` declaration anywhere."""
    found = {}

    def add(name, kind):
        """Record one binding of `name` with its kind."""
        found.setdefault(name, []).append(kind)

    def bind_target(target, kind):
        """Record every name bound by an assignment-like target."""
        for node in ast.walk(target):
            if isinstance(node, ast.Name):
                add(node.id, kind)

    def visit(statements):
        """Walk statements run at module scope (into blocks, not into def/class bodies)."""
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                add(node.name, "def")
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    add(alias.asname or alias.name.split(".")[0], "import")
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    bind_target(target, "assign")
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                bind_target(node.target, "assign")
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                bind_target(node.target, "for")
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        bind_target(item.optional_vars, "with")
            elif isinstance(node, ast.Delete):
                for target in node.targets:
                    bind_target(target, "del")
            if isinstance(node, ast.Try) or (hasattr(ast, "TryStar") and isinstance(node, ast.TryStar)):
                for handler in node.handlers:
                    if handler.name:
                        add(handler.name, "except")
                    visit(handler.body)
            for field in ("body", "orelse", "finalbody"):
                visit(getattr(node, field, []) or [])
            if isinstance(node, ast.Match):
                for case in node.cases:
                    visit(case.body)

    visit(tree.body)
    for node in ast.walk(tree):  # conservative: anywhere in the file
        if isinstance(node, ast.Global):
            for name in node.names:
                add(name, "global")
        elif isinstance(node, ast.NamedExpr):
            bind_target(node.target, "walrus")
    return found


def _module_bindings(tree):
    """{bound name: dotted origin} for top-level imports in `tree`."""
    bindings = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            for alias in node.names:
                bindings[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return bindings


def _top_level_defs(tree):
    """Names defined at top level of `tree` by def/class/assignment."""
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return names


def _free_names(statements):
    """Names the statements read but never bind (i.e. what they need from outside)."""
    # Parse the wrapper instead of constructing FunctionDef by hand: its fields differ
    # across Python versions (e.g. `type_params`, added in 3.12).
    wrapper = ast.parse("def _probe():\n    pass\n")
    wrapper.body[0].body = copy.deepcopy(statements)
    ast.fix_missing_locations(wrapper)
    table = symtable.symtable(ast.unparse(wrapper), "probe", "exec").get_children()[0]
    found = set()

    def walk(scope):
        """Collect names a scope reads as globals, recursing into child scopes."""
        for symbol in scope.get_symbols():
            if symbol.is_referenced() and symbol.is_global():
                found.add(symbol.get_name())
        for child in scope.get_children():
            walk(child)

    walk(table)
    return found - set(dir(builtins))


# --- tests ---

def test_app_slice_anchor_and_length_are_stable():
    """The slice ends at `timing = ...` and spans the reviewed number of statements."""
    assert _summary(APP_SLICE[-1]) == "assign:timing"
    assert len(APP_SLICE) == 127, "app.py's decision core changed size; re-review the copy"


def test_app_live_only_tail_is_unchanged():
    """Nothing new appeared after `timing` in app.py that the copy would silently miss."""
    assert tuple(_summary(s) for s in APP_TAIL) == EXPECTED_APP_TAIL


@pytest.mark.parametrize("index", range(len(APP_SLICE)))
def test_each_decision_statement_matches_app(index):
    """Statement `index` of the engine's try-body equals app.py's after the allowed transforms."""
    expected = _transformed_app_slice()
    actual = ENGINE_TRY.body[:-2]
    assert len(actual) == len(expected), f"engine has {len(actual)} decision statements, app.py {len(expected)}"
    if ast.dump(expected[index]) != ast.dump(actual[index]):
        pytest.fail(
            f"statement {index} (app.py line {APP_SLICE[index].lineno}) drifted. "
            f"Allowed: {[t.label for t in ALLOWED_TRANSFORMS]}\n"
            f"--- app.py (after allowed transforms) ---\n{ast.unparse(expected[index])}\n"
            f"--- equity_stage2_decision.py ---\n{ast.unparse(actual[index])}")


def test_exception_handler_matches_app():
    """The `except` handler (error label + reject) is app.py's, and neither side adds else/finally."""
    assert ast.dump(ast.Module(body=APP_TRY.handlers, type_ignores=[])) == \
        ast.dump(ast.Module(body=ENGINE_TRY.handlers, type_ignores=[]))
    assert not APP_TRY.orelse and not APP_TRY.finalbody
    assert not ENGINE_TRY.orelse and not ENGINE_TRY.finalbody


def test_pass_record_carries_exactly_what_app_archives():
    """The engine's pass return mirrors app.py's `_archive_stage2(True, ...)` call, plus listed extras."""
    archive = next(n for n in ast.walk(APP_TRY) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "_archive_stage2" and n.args
                   and isinstance(n.args[0], ast.Constant) and n.args[0].value is True)
    app_fields = {k.arg: ast.dump(k.value) for k in archive.keywords}
    assert set(app_fields) == {"score", "entry", "stop", "target", "features"}

    final = ENGINE_TRY.body[-1]
    assert isinstance(final, ast.Return) and isinstance(final.value, ast.Tuple)
    record, error = final.value.elts
    assert isinstance(error, ast.Constant) and error.value is None
    assert isinstance(record, ast.Dict)
    engine_fields = {k.value: v for k, v in zip(record.keys, record.values)}
    assert set(engine_fields) == set(app_fields) | set(ENGINE_EXTRA_RETURN)
    for name, dumped in app_fields.items():
        assert ast.dump(engine_fields[name]) == dumped, f"pass-record field {name!r} differs from app.py"
    for name, source in ENGINE_EXTRA_RETURN.items():
        assert ast.unparse(engine_fields[name]) == source


def test_final_capture_call_matches_app_and_sees_the_same_inputs():
    """The engine repeats app.py's last `observation.observe(locals(), ...)`; the skipped live-only
    statements before it bind no captured input name, so both snapshots record the same inputs."""
    from equity_observation_capture import INPUTS
    app_observe = [s for s in APP_TAIL if _summary(s) == "expr:observation.observe"]
    assert len(app_observe) == 1
    assert ast.dump(ENGINE_TRY.body[-2]) == ast.dump(app_observe[0])
    skipped = APP_TAIL[:APP_TAIL.index(app_observe[0])]
    bound = {n.id for s in skipped for n in ast.walk(s) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    captured_specials = {"latest", "raw_quote", "cost_estimate"}
    assert not bound & (set(INPUTS) | captured_specials), sorted(bound & (set(INPUTS) | captured_specials))


def test_reject_returns_what_app_reject_returns():
    """Engine `_reject` returns app.py `_reject`'s value; only app.py also archives."""
    app_reject = next(s for s in APP_FN.body if isinstance(s, ast.FunctionDef) and s.name == "_reject")
    engine_reject = next(s for s in ENGINE_FN.body if isinstance(s, ast.FunctionDef) and s.name == "_reject")
    assert [a.arg for a in app_reject.args.args] == [a.arg for a in engine_reject.args.args]
    app_return = next(s for s in app_reject.body if isinstance(s, ast.Return))
    engine_return = next(s for s in engine_reject.body if isinstance(s, ast.Return))
    assert ast.dump(app_return) == ast.dump(engine_return)


def test_pre_try_state_matches_app():
    """`raw_quote = {}` is initialised before the try in both, so the error path sees the same state."""
    app_pre = [ast.dump(s) for s in APP_FN.body[:APP_FN.body.index(APP_TRY)]]
    engine_pre = ENGINE_FN.body[:ENGINE_FN.body.index(ENGINE_TRY)]
    raw_quote_init = [s for s in engine_pre if _assigns(s, "raw_quote")]
    assert len(raw_quote_init) == 1 and ast.dump(raw_quote_init[0]) in app_pre


def test_every_page_global_is_a_same_named_parameter():
    """Every name the app slice reads from the scan page becomes a keyword-only parameter of that name."""
    engine_module_names = set(_module_bindings(DECISION_TREE)) | _top_level_defs(DECISION_TREE)
    engine_locals_before_try = {"raw_quote", "_reject"}
    needed = _free_names(_transformed_app_slice() + list(APP_TRY.handlers[0].body)) | {"ticker"}
    expected_params = needed - engine_module_names - engine_locals_before_try - {"exc"}
    params = {a.arg for a in ENGINE_FN.args.args} | {a.arg for a in ENGINE_FN.args.kwonlyargs}
    assert params == expected_params, (
        f"missing params: {sorted(expected_params - params)}, unused params: {sorted(params - expected_params)}")
    assert [a.arg for a in ENGINE_FN.args.args] == ["ticker"]


def test_module_imports_bind_the_same_objects_as_app():
    """Imported names bind what app.py binds; engine helpers must be parity-guarded copies of app defs."""
    app_imports = _module_bindings(APP_TREE)
    app_defs = _top_level_defs(APP_TREE)
    local_imports = {}
    for node in APP_FN.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                local_imports[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    problems = []
    for name, origin in _module_bindings(DECISION_TREE).items():
        if origin.startswith("equity_stage2_engine."):
            if name not in ENGINE_SHARED or name not in app_defs:
                problems.append(f"{name}: not a parity-guarded copy of an app.py definition")
        else:
            # Inside evaluate_stock a local import shadows any module-level one.
            app_origin = local_imports.get(name, app_imports.get(name))
            if app_origin != origin:
                problems.append(f"{name}: app.py binds {app_origin}, engine {origin}")
    assert not problems, problems


def test_engine_bound_names_have_exactly_one_module_scope_binding_in_app():
    """Each name the copied code takes from a module (not a parameter) is bound exactly once at
    app.py module scope, so a later rebinding (re-import, reassignment, `except as`, `global`)
    cannot make app.py's slice use a different object than the engine does."""
    params = {a.arg for a in ENGINE_FN.args.args} | {a.arg for a in ENGINE_FN.args.kwonlyargs}
    local_in_app_fn = {"observation", "key", "raw_quote", "_reject", "profile_call", "profile_span",
                       "evidence_identity_key", "scanner_observation_id", "_archive_stage2", "EquityCapture"}
    needed = _free_names(APP_SLICE + list(APP_TRY.handlers[0].body))
    module_names = sorted(needed - params - local_in_app_fn - {"MARKET_OPEN", "TECHNICAL_FEATURE_STORE", "exc"})
    bindings = _module_scope_bindings(APP_TREE)
    bad = {name: bindings.get(name, []) for name in module_names if len(bindings.get(name, [])) != 1}
    assert not bad, bad
    assert set(module_names) <= set(_module_bindings(DECISION_TREE)), "engine must import every module name"


def test_engine_module_and_function_structure_is_pinned():
    """No code outside the copied slice: module = docstring + imports + evaluate_stage2;
    function = docstring, `raw_quote = {}`, `_reject`, try; `_reject` = docstring + return."""
    kinds = [type(n).__name__ for n in DECISION_TREE.body]
    assert kinds[0] == "Expr" and kinds[-1] == "FunctionDef" and DECISION_TREE.body[-1] is ENGINE_FN
    assert set(kinds[1:-1]) <= {"Import", "ImportFrom"}, kinds
    body = ENGINE_FN.body
    assert [type(s).__name__ for s in body] == ["Expr", "Assign", "FunctionDef", "Try"]
    assert _assigns(body[1], "raw_quote") and body[2].name == "_reject" and body[3] is ENGINE_TRY
    assert [type(s).__name__ for s in body[2].body] == ["Expr", "Return"]
    args = ENGINE_FN.args
    assert not (ENGINE_FN.decorator_list or args.vararg or args.kwarg or args.defaults or args.posonlyargs)
    assert all(default is None for default in args.kw_defaults), "parameters must be required (no defaults)"


def test_app_evaluate_stock_outside_the_core_is_pinned():
    """app.py's evaluate_stock outside the copied core (setup before `try:`, `_reject`,
    `_archive_stage2`, live-only tail incl. the governance reject) matches the reviewed digest.
    If this fails: re-review whether the change affects Stage-2 decisions or what the caller
    must archive; update equity_stage2_decision.py if so; then update the digest."""
    assert _app_outside_core_digest() == EXPECTED_APP_OUTSIDE_CORE_SHA256


def test_engine_free_names_all_resolve():
    """Every name the decision module reads is a parameter, import, local, or builtin (no NameError)."""
    module_names = set(_module_bindings(DECISION_TREE)) | _top_level_defs(DECISION_TREE) | set(dir(builtins))
    unresolved = []

    def walk(scope):
        """Collect unresolved global reads in a scope and its child scopes."""
        for symbol in scope.get_symbols():
            if symbol.is_referenced() and symbol.is_global() and symbol.get_name() not in module_names:
                unresolved.append(f"{scope.get_name()}: {symbol.get_name()}")
        for child in scope.get_children():
            walk(child)

    walk(symtable.symtable(DECISION_SOURCE, "equity_stage2_decision.py", "exec"))
    assert not unresolved, unresolved
