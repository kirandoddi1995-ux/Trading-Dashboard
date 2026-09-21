"""Dependency closure and credential-free checks of the actual release artifact."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile


MANIFEST = "SHA256_MANIFEST.json"


def safe_member(root, name):
    """Reject traversal and symlinks, including links within the source root."""
    root = Path(root).resolve()
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise ValueError(f"Unsafe release member: {name}")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"Symlink release member: {name}")
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError(f"Missing or unsafe release member: {name}")
    return path


def module_index(root):
    """Index local source only, never import it during discovery.

    Top-level modules and regular Python packages are supported. Non-Python
    resources remain explicitly allowlisted; arbitrary directories are not swept
    into a release. Package symlinks are rejected rather than followed.
    """
    root = Path(root)
    modules = {}

    def visit(directory, prefix=""):
        for path in sorted(directory.iterdir()):
            if path.name.startswith(".") or path.name == "__pycache__":
                continue
            if path.suffix == ".py" and path.is_file():
                name = prefix.rstrip(".") if path.name == "__init__.py" else prefix + path.stem
                modules[name] = path.relative_to(root).as_posix()
            elif path.is_dir() and (path / "__init__.py").is_file():
                if path.is_symlink():
                    raise ValueError(f"Symlink package: {path.name}")
                visit(path, prefix + path.name + ".")

    visit(root)
    return modules


def release_members(root, seeds):
    """Transitive local imports, including function/conditional/relative imports.

    Literal import_module/__import__ calls are included too. Computed plugin
    names and resource paths must be supplied as explicit seeds by the owner.
    """
    root = Path(root).resolve()
    index = module_index(root)
    reverse = {path: name for name, path in index.items()}
    selected, pending = set(), list(seeds)
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        path = safe_member(root, name)
        selected.add(name)
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=name)
        module = reverse.get(name, "")
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        requested = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                requested.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = package.split(".") if package else []
                    if node.level > len(parts):
                        raise ValueError(f"Invalid relative import in {name}:{node.lineno}")
                    base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
                requested.append(base)
                requested.extend(base + "." + alias.name for alias in node.names if alias.name != "*")
            elif isinstance(node, ast.Call) and node.args:
                func = node.func
                label = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                if label in {"import_module", "__import__"} and isinstance(node.args[0], ast.Constant):
                    target = node.args[0].value
                    if isinstance(target, str) and not target.startswith("."):
                        requested.append(target)
        for target in requested:
            parts = target.split(".")
            for length in range(1, len(parts) + 1):
                dependency = index.get(".".join(parts[:length]))
                if dependency and dependency not in selected:
                    pending.append(dependency)
    return sorted(selected)


# Run as code passed to an isolated interpreter, NOT a helper imported from the
# checkout. The only project path put on sys.path is the extracted bundle.
IMPORT_PROBE = r'''
import importlib, importlib.abc, importlib.machinery, json, pathlib, platform, sys
# Standard-library Windows platform detection may invoke cmd /c ver. Cache it
# before restricting application I/O; no application code has been imported.
platform.platform()
platform.processor()
# Initialize only this known third-party housekeeping dependency while the
# extracted application is still absent from sys.path. Network remains denied;
# font discovery may run the installed system font utility. Never catch import
# failures here: a missing/broken Matplotlib installation must fail the gate.
def no_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("External I/O forbidden in release import verification")
sys.addaudithook(no_network)
importlib.import_module("matplotlib.font_manager")
root = pathlib.Path(sys.argv[1]).resolve()
local_names = set(json.loads(sys.argv[2]))
sys.path[:] = [str(root)] + [p for p in sys.path if p and
    ("site-packages" in pathlib.Path(p).parts or not pathlib.Path(p, "app.py").exists())]

class LocalOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] not in local_names:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, [str(root)] if path is None else path)
        if spec is None or not spec.origin or not pathlib.Path(spec.origin).resolve().is_relative_to(root):
            raise ImportError("Release-local module unavailable: " + fullname)
        return spec
sys.meta_path.insert(0, LocalOnly())

def offline(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "subprocess.Popen", "os.system"}:
        raise RuntimeError("External I/O forbidden in release import verification")
sys.addaudithook(offline)
importlib.import_module("app")
# Import success must not be inferred merely from exit code (e.g. sys.exit(0)).
print("RELEASE_IMPORT_VERIFIED")
'''


def verify_archive(archive, *, timeout=120):
    """Verify ZIP bytes, then import only from its extracted, disposable contents.

    Third-party dependencies come from the invoking interpreter's installed
    environment; requirements/constraints travel with the release. This is not
    a bundled Python interpreter or a provider/authenticated functional test.
    """
    with tempfile.TemporaryDirectory(prefix="quant-release-check-") as temporary:
        home = Path(temporary)
        extracted = home / "bundle"
        extracted.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            if len(names) != len(set(names)) or MANIFEST not in names:
                raise ValueError("Release has duplicate members or no manifest")
            manifest = json.loads(bundle.read(MANIFEST))
            if not isinstance(manifest, dict) or set(names) != set(manifest) | {MANIFEST}:
                raise ValueError("Release manifest membership mismatch")
            for name, digest in manifest.items():
                relative = PurePosixPath(name)
                if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
                    raise ValueError("Unsafe archive member")
                if (bundle.getinfo(name).external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Archive symlink forbidden")
                data = bundle.read(name)
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError(f"Release hash mismatch: {name}")
                destination = extracted / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
        local_names = sorted({n.split(".")[0] for n in module_index(extracted)})
        # Allowlist OS necessities only; no DB, provider, OIDC, telemetry or Drive
        # credentials, PYTHONPATH, user config, or user-site packages are inherited.
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "SYSTEMROOT", "WINDIR", "PATH", "COMSPEC", "PATHEXT", "LANG", "LC_ALL",
        }}
        env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home),
                   LOCALAPPDATA=str(home), TMP=str(home), TEMP=str(home),
                   MPLCONFIGDIR=str(home / "matplotlib"),
                   STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", IMPORT_PROBE, str(extracted), json.dumps(local_names)],
                cwd=extracted, env=env, capture_output=True, text=True,
                timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Extracted release import timed out; release not published") from exc
        if result.returncode != 0 or "RELEASE_IMPORT_VERIFIED" not in result.stdout.splitlines():
            raise RuntimeError("Extracted release import failed; release not published\n" + result.stderr[-12000:])
        return {"files": len(manifest), "import_verified": True}
