"""Shared equity release configuration with value-free provenance diagnostics."""
from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

NAMES = ('EXPECTED_APP_BUILD', 'RESILIENCE_POLICY_SHA256', 'EXPECTED_EQUITY_CODE_SHA256')


def _valid(name: str, value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if name == 'EXPECTED_APP_BUILD':
        return len(value) <= 200 and all(32 <= ord(char) < 127 for char in value)
    return re.fullmatch(r'[0-9a-f]{64}', value) is not None


def resolve(secrets: Mapping[str, Any], environment: Mapping[str, str], *,
            actual: Mapping[str, Any] | None = None) -> tuple[dict[str, str], dict[str, Any]]:
    """Root first, environment second; never search sections for accepted values.

    Explicit invalid roots, parse/read errors or differing sources fail closed.
    Section inspection finds misplacement only. It never supplies expectations.
    Returned values are server-private; ONLY diagnostics may be logged/displayed.
    """
    values: dict[str, str] = {}
    diagnostics: dict[str, Any] = {}
    sentinel = object()
    try:
        roots = {name: secrets.get(name, sentinel) for name in NAMES}
        misplaced: dict[str, list[str]] = {name: [] for name in NAMES}
        for section, content in secrets.items():
            if isinstance(content, Mapping):
                label = section if isinstance(section, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,63}', section) else '[section]'
                for name in NAMES:
                    if name in content:
                        misplaced[name].append(label)
    except Exception:
        # Do not echo exception text: TOML errors may contain credential lines.
        return {}, {name: dict(status='SECRETS_READ_ERROR', source='NONE',
                              root_present=None, environment_present=name in environment,
                              matches_actual=None, misplaced_sections=[])
                    for name in NAMES}
    for name in NAMES:
        root = roots[name]
        env = environment.get(name, sentinel)
        source = 'STREAMLIT_ROOT' if root is not sentinel else 'ENVIRONMENT' if env is not sentinel else 'NONE'
        selected = root if root is not sentinel else env
        status = 'MISSING' if selected is sentinel else 'VALID' if _valid(name, selected) else 'INVALID_FORMAT'
        if root is not sentinel and env is not sentinel and root != env:
            status = 'SOURCE_CONFLICT'
        if status == 'VALID':
            assert isinstance(selected, str)  # Established by _valid; retain typed output.
            values[name] = selected
        diagnostics[name] = dict(status=status, source=source,
            root_present=root is not sentinel, environment_present=env is not sentinel,
            misplaced_sections=misplaced[name],
            matches_actual=(values[name] == actual[name]) if name in values and actual is not None and name in actual else None)
    return values, diagnostics
