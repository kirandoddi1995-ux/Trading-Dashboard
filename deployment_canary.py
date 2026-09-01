"""Credential-free release canaries; live provider checks are explicit opt-in."""
from __future__ import annotations
import ast, hashlib, json, sqlite3, zipfile
from pathlib import Path


def run_canaries(root):
    root=Path(root); checks={}
    app=root/"app.py"; ast.parse(app.read_text(encoding="utf-8")); checks["app_parses"]=True
    for module in ("provider_contracts.py","quantitative_services.py","iv_surface.py","model_registry.py","mf_archive.py"):
        ast.parse((root/module).read_text(encoding="utf-8")); checks[f"parses:{module}"]=True
    db=sqlite3.connect(":memory:"); checks["sqlite_json"]=db.execute("SELECT json_valid('{}')").fetchone()[0]==1; db.close()
    archives=sorted(root.glob("release-*.zip"),key=lambda p:p.stat().st_mtime,reverse=True)
    if archives:
        with zipfile.ZipFile(archives[0]) as z: checks["latest_zip_integrity"]=z.testzip() is None
    ignored=(root/".gitignore").read_text(encoding="utf-8") if (root/".gitignore").exists() else ""
    checks["secrets_excluded"]=".streamlit/secrets.toml" in ignored
    return {"ok":all(checks.values()),"checks":checks}


if __name__ == "__main__":
    result=run_canaries(Path(__file__).resolve().parent); print(json.dumps(result,indent=2)); raise SystemExit(0 if result["ok"] else 1)
