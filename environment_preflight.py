"""Detect contaminated Python environments before tests or deployment."""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


def find_dependency_conflicts(distributions=None) -> list[dict]:
    """Return installed dependency conflicts without importing heavy packages."""
    distributions = list(distributions if distributions is not None else metadata.distributions())
    installed = {}
    for dist in distributions:
        name = canonicalize_name(dist.metadata.get("Name") or "")
        if name:
            installed[name] = str(dist.version)
    environment = default_environment()
    conflicts = []
    for dist in distributions:
        package = str(dist.metadata.get("Name") or "unknown")
        for raw in dist.requires or ():
            try:
                requirement = Requirement(raw)
                if requirement.marker and not requirement.marker.evaluate(environment):
                    continue
                dependency = canonicalize_name(requirement.name)
                actual = installed.get(dependency)
                if actual is None:
                    conflicts.append({
                        "package": package, "dependency": requirement.name,
                        "required": str(requirement.specifier) or "installed", "actual": "missing",
                    })
                    continue
                if requirement.specifier and Version(actual) not in requirement.specifier:
                    conflicts.append({
                        "package": package, "dependency": requirement.name,
                        "required": str(requirement.specifier), "actual": actual,
                    })
            except (InvalidVersion, ValueError):
                conflicts.append({
                    "package": package, "dependency": "unparseable metadata",
                    "required": str(raw), "actual": "unknown",
                })
    return conflicts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate the active Python dependency environment")
    parser.add_argument("--strict", action="store_true", help="Return a failing exit code on any conflict")
    args = parser.parse_args(argv)
    conflicts = find_dependency_conflicts()
    result = {
        "ok": not conflicts,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "remediation": (
            "Use a clean Python 3.13 virtual environment and reinstall requirements.txt; "
            "do not install this application into the TensorFlow/Anaconda environment."
            if conflicts else "None"
        ),
    }
    print(json.dumps(result, indent=2))
    return 1 if args.strict and conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
