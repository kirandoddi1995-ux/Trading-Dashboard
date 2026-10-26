"""Bounded, offline diagnostics for owner-supplied GitHub REST alert arrays.

No authentication, fetching, dismissal, remediation or deployment approval occurs.
Unknown REST metadata is discarded; only the required diagnostic fields survive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Never, Sequence

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_ALERTS = 10_000
MAX_NAME_LENGTH = 200
MAX_PATH_LENGTH = 512
MAX_ALERT_NUMBER = (1 << 63) - 1
MAX_OBJECT_FIELDS = 64
ERROR = "DEPENDENCY_ALERT_REVIEW_INVALID_INPUT"
STATUS = "DIAGNOSTIC_NOT_DEPLOYMENT_APPROVAL"
SEVERITIES = ("critical", "high", "moderate", "low")
STATES = ("open", "dismissed", "fixed", "auto_dismissed")
KNOWN_DECLARATIONS = frozenset(
    ("requirements.txt", "constraints.txt", "requirements-forward-operations.txt")
)


def _invalid() -> ValueError:
    return ValueError(ERROR)


def _mapping(value: object) -> dict[str, object]:
    if (
        type(value) is not dict
        or len(value) > MAX_OBJECT_FIELDS
        or any(type(key) is not str for key in value)
    ):
        raise _invalid()
    return value


def _name(value: object, limit: int = MAX_NAME_LENGTH) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= limit
        or value != value.strip()
        or any(not char.isprintable() for char in value)
    ):
        raise _invalid()
    return value


def _manifest(value: object) -> str:
    name = _name(value, MAX_PATH_LENGTH)
    # Canonical repository-relative POSIX labels, never local filesystem paths.
    if (
        "\\" in name
        or ":" in name
        or "%" in name
        or any(part in ("", ".", "..") for part in name.split("/"))
    ):
        raise _invalid()
    return name


@dataclass(frozen=True)
class Alert:
    number: int
    state: str
    severity: str
    manifest: str
    ecosystem: str
    package: str
    ghsa: str


def normalize_alerts(value: object) -> tuple[Alert, ...]:
    """Validate the required REST schema atomically; never return partial results."""
    if type(value) is not list or len(value) > MAX_ALERTS:
        raise _invalid()
    alerts: list[Alert] = []
    seen: set[int] = set()
    for item in value:
        row = _mapping(item)
        number = row.get("number")
        if type(number) is not int or not 1 <= number <= MAX_ALERT_NUMBER:
            raise _invalid()
        if number in seen:
            raise _invalid()
        seen.add(number)
        state = _name(row.get("state"))
        advisory = _mapping(row.get("security_advisory"))
        severity = _name(advisory.get("severity"))
        ghsa = _name(advisory.get("ghsa_id"))
        if state not in STATES or severity not in SEVERITIES:
            raise _invalid()
        if re.fullmatch(r"GHSA-[23456789cfghjmpqrvwx]{4}(?:-[23456789cfghjmpqrvwx]{4}){2}", ghsa) is None:
            raise _invalid()
        dependency = _mapping(row.get("dependency"))
        package = _mapping(dependency.get("package"))
        alerts.append(Alert(
            number, state, severity, _manifest(dependency.get("manifest_path")),
            _name(package.get("ecosystem")), _name(package.get("name")), ghsa,
        ))
    return tuple(sorted(alerts, key=lambda alert: alert.number))


def _metadata(attested: bool) -> dict[str, object]:
    if type(attested) is not bool:
        raise _invalid()
    return {
        "status": STATUS,
        "approval_authority": False,
        "complete_export_owner_attested": attested,
        "attestation_is_authentication": False,
        "completeness_independently_verified": False,
        "installed_profile_exposure": "UNVERIFIED",
        "manifest_labels_are_exposure_proof": False,
        "independently_verified": False,
        "profile_audits_clear_repository_alerts": False,
    }


def summarize_alerts(
    value: object, *, complete_export_owner_attested: bool = False,
) -> dict[str, object]:
    """Count supplied alerts, including separate open counts in every grouping."""
    result = _metadata(complete_export_owner_attested)
    alerts = normalize_alerts(value)
    manifests: dict[str, Counter[str]] = {}
    packages: dict[tuple[str, str], Counter[str]] = {}
    ghsas: dict[str, Counter[str]] = {}
    severity = Counter(alert.severity for alert in alerts)
    open_severity = Counter(alert.severity for alert in alerts if alert.state == "open")
    states = Counter(alert.state for alert in alerts)
    for alert in alerts:
        for counts in (
            manifests.setdefault(alert.manifest, Counter()),
            packages.setdefault((alert.ecosystem, alert.package), Counter()),
            ghsas.setdefault(alert.ghsa, Counter()),
        ):
            counts["total"] += 1
            counts["open"] += int(alert.state == "open")
    result.update({
        "source": "SUPPLIED_EXPORT_ONLY",
        "total_alerts": len(alerts),
        "open_alerts": states["open"],
        "severity_counts": {key: severity[key] for key in SEVERITIES},
        "open_severity_counts": {key: open_severity[key] for key in SEVERITIES},
        "state_counts": {key: states[key] for key in STATES},
        "manifests": [
            {"manifest": key, **dict(counts), "location_label": (
                "known_profile_declaration" if key in KNOWN_DECLARATIONS
                else "requires_own_audit"
            )} for key, counts in sorted(manifests.items())
        ],
        "packages": [
            {"ecosystem": key[0], "package": key[1], **dict(counts)}
            for key, counts in sorted(packages.items())
        ],
        "ghsas": [{"ghsa": key, **dict(counts)} for key, counts in sorted(ghsas.items())],
    })
    return result


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid()
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise _invalid()


def review_json(
    raw: bytes, *, complete_export_owner_attested: bool = False,
) -> dict[str, object]:
    """Review at most 2 MiB of UTF-8 JSON and hash the exact supplied bytes."""
    if type(raw) is not bytes or len(raw) > MAX_INPUT_BYTES:
        raise _invalid()
    try:
        value: object = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_json_object,
            parse_constant=_reject_constant,
        )
        result = summarize_alerts(
            value, complete_export_owner_attested=complete_export_owner_attested,
        )
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise _invalid() from None
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    return result


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise _invalid()


def main(argv: Sequence[str] | None = None) -> int:
    """Default preview reads no files. Only paired --input ABSOLUTE --check reads."""
    try:
        arguments = list(sys.argv[1:] if argv is None else argv)
        if not arguments:
            # Bypass argparse's locale/help discovery on the zero-I/O default.
            preview = _metadata(False)
            preview["source"] = "PREVIEW_NO_EXPORT_READ"
            print(json.dumps(preview, sort_keys=True, ensure_ascii=True))
            return 0
        parser = _Parser(description=__doc__, allow_abbrev=False)
        parser.add_argument("--input")
        parser.add_argument("--check", action="store_true")
        parser.add_argument("--complete-export-owner-attested", action="store_true")
        args = parser.parse_args(arguments)
        if (args.input is not None) != args.check:
            raise _invalid()
        if args.check:
            path = Path(args.input)
            if not path.is_absolute() or not path.is_file():
                raise _invalid()
            with path.open("rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_INPUT_BYTES:
                    raise _invalid()
                raw = stream.read(MAX_INPUT_BYTES)
                after = os.fstat(stream.fileno())
                if len(raw) != info.st_size or after.st_size != info.st_size:
                    raise _invalid()
            result = review_json(
                raw, complete_export_owner_attested=args.complete_export_owner_attested,
            )
        else:
            result = _metadata(args.complete_export_owner_attested)
            result["source"] = "PREVIEW_NO_EXPORT_READ"
        print(json.dumps(result, sort_keys=True, ensure_ascii=True))
        return 0
    except (ValueError, OSError, RecursionError, OverflowError):
        print(json.dumps({"error": ERROR, "status": STATUS, "approval_authority": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
