from pathlib import Path
from importlib import metadata


ROOT = Path(__file__).resolve().parents[1]


def test_new_type_checks_and_tool_audit_do_not_replace_existing_gates():
    text = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    for value in ("python -m pip_audit -r requirements.txt",
                  "python -m pip_audit -r requirements-equity-study-tools.txt",
                  "--config-file mypy-automation.ini", "--config-file mypy-equity-study.ini",
                  "python -m pip install -r requirements-equity-study-tools.txt"):
        assert value in text
    assert "--ignore-vuln" not in text
    assert "python -m venv /tmp/equity-study-typecheck" in text
    assert "/tmp/equity-study-typecheck/bin/python -m pip install -r requirements-equity-study-tools.txt" in text
    assert "/tmp/equity-study-typecheck/bin/python -m mypy --config-file mypy-equity-study.ini" in text
    assert "python -m pip install 'pip==26.2.2'" in text
    assert "run: python -m pip_audit\n" in text


def test_equity_type_scope_remains_strict_and_tools_are_not_runtime_dependencies():
    config = (ROOT / "mypy-equity-study.ini").read_text(encoding="utf-8")
    assert "strict = True" in config and "ignore" not in config
    for name in ("equity_eod_study_design.py", "equity_eod_study.py", "equity_eod_study_ui.py", "dependency_alert_review.py"):
        assert name in config
    tools = (ROOT / "requirements-equity-study-tools.txt").read_text(encoding="utf-8")
    assert "pandas-stubs==2.3.3.260113" in tools
    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "pandas-stubs" not in runtime


def test_audit_cache_lock_dependency_is_patched_not_excluded():
    constraints = (ROOT / "constraints.txt").read_text(encoding="utf-8")
    assert "filelock==4.2.1" in constraints
    assert "filelock==3.32.4" not in constraints
    assert metadata.version("filelock") == "4.2.1"
    assert metadata.version("pip") == "26.2.2"


def test_audit_cache_filelock_api_roundtrip_remains_compatible(tmp_path):
    from cachecontrol.caches import FileCache
    cache = FileCache(str(tmp_path / "synthetic-audit-cache"))
    cache.set("https://example.invalid/synthetic", b"synthetic bytes")
    assert cache.get("https://example.invalid/synthetic") == b"synthetic bytes"
    cache.delete("https://example.invalid/synthetic")
    assert cache.get("https://example.invalid/synthetic") is None


def test_isolated_study_profile_includes_acquisition_imports_at_reviewed_pins():
    # Constraints restrict versions; they do not install omitted distributions.
    import ast
    source = ast.parse((ROOT / "equity_private_acquire.py").read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(source) if isinstance(node, ast.Import)
               for alias in node.names}
    assert {"certifi", "pyarrow", "pyarrow.parquet"} <= imports
    tools = (ROOT / "requirements-equity-study-tools.txt").read_text(encoding="utf-8")
    constraints = (ROOT / "constraints.txt").read_text(encoding="utf-8")
    direct = {line.strip() for line in tools.splitlines()
              if line.strip() and not line.lstrip().startswith("#")}
    for requirement in ("certifi==2026.10.23", "pyarrow==24.0.0"):
        assert requirement in direct
        assert requirement in constraints.splitlines()
    assert direct == {"-c constraints.txt", "pip==26.2.2", "mypy==2.4.0",
                      "pandas-stubs==2.3.3.260113", "types-pytz==2026.5.0.20261006",
                      "certifi==2026.10.23", "pyarrow==24.0.0"}
