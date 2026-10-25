"""Public source identity, not deployment integrity or permission evidence."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re


def _small_text(path: Path, limit: int) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("IDENTITY_SOURCE_UNAVAILABLE")
    return path.read_text(encoding="ascii").strip()


def source_identity(root: Path) -> dict[str, str]:
    """Read only local Git metadata and app source; never infer from an env var.

    Some deployments omit .git. Show UNKNOWN then, with a source-file fingerprint
    useful for comparison. Git HEAD is a claim about the checkout, not proof that
    the working files are clean or that a branch was approved for deployment.
    Worktree gitfiles and linked metadata intentionally return UNKNOWN.
    """
    result = {"commit": "UNKNOWN", "basis": "GIT_METADATA_UNAVAILABLE",
              "app_sha256": "UNKNOWN", "integrity": "NOT_ATTESTED"}
    try:
        app = root / "app.py"
        if not app.is_symlink() and app.is_file() and app.stat().st_size <= 4_000_000:
            result["app_sha256"] = hashlib.sha256(app.read_bytes()).hexdigest()
        git = root / ".git"
        if git.is_symlink() or not git.is_dir():
            return result
        head = _small_text(git / "HEAD", 256)
        if head.startswith("ref: "):
            reference = head[5:]
            if not re.fullmatch(r"refs/(?:heads|tags)/[A-Za-z0-9_/-]+", reference):
                return result
            target = git / reference
            if any(parent.is_symlink() for parent in (target, *target.parents) if parent != root):
                return result
            if target.exists():
                head = _small_text(target, 128)
            else:
                entries = _small_text(git / "packed-refs", 1_000_000).splitlines()
                matches = [line.split(" ", 1)[0] for line in entries
                           if line.endswith(" " + reference) and not line.startswith(("#", "^"))]
                if len(matches) != 1:
                    return result
                head = matches[0]
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
            result.update(commit=head, basis="LOCAL_GIT_HEAD_NOT_CLEANLINESS_PROOF")
    except (OSError, ValueError, UnicodeError):
        pass
    return result
