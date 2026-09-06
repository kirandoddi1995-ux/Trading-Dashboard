"""Managed secret loading and zero-downtime rotation primitives.

Secret values are intentionally wrapped in a redacted type and are never
included in rotation events.  The Google Secret Manager adapter is optional at
runtime and uses Application Default Credentials; tests use the in-memory
provider so synthetic keys cannot enter the production evidence store.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import threading
import uuid
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol


UTC = dt.timezone.utc


class SecretProviderError(RuntimeError):
    pass


class SecretValue:
    __slots__ = ("_value",)

    def __init__(self, value: str | bytes):
        raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        if not raw:
            raise SecretProviderError("Secret value is empty")
        self._value = raw

    def reveal_bytes(self) -> bytes:
        return bytes(self._value)

    def reveal_text(self) -> str:
        return self._value.decode("utf-8")

    def fingerprint(self) -> str:
        return hashlib.sha256(self._value).hexdigest()[:16]

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    __str__ = __repr__


@dataclass(frozen=True)
class SecretVersion:
    secret_id: str
    version_id: str
    created_at: str
    enabled: bool
    fingerprint: str


class ManagedSecretProvider(Protocol):
    def access(self, secret_id: str, version: str = "latest") -> SecretValue: ...
    def add_version(self, secret_id: str, value: SecretValue) -> SecretVersion: ...
    def disable_version(self, secret_id: str, version: str) -> None: ...


class GoogleSecretManagerProvider:
    """Minimal Google Secret Manager REST adapter using ADC credentials."""

    def __init__(self, project_id: str, *, session=None):
        if not str(project_id).strip():
            raise SecretProviderError("Google Cloud project id is required")
        self.project_id = str(project_id).strip()
        if session is None:
            try:
                import google.auth
                from google.auth.transport.requests import AuthorizedSession
            except ImportError as exc:
                raise SecretProviderError("google-auth is required for Google Secret Manager") from exc
            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            session = AuthorizedSession(credentials)
        self.session = session

    def _base(self, secret_id: str) -> str:
        name = str(secret_id).strip()
        if not name or "/" in name:
            raise SecretProviderError("Secret id must be a simple Google Secret Manager name")
        return f"https://secretmanager.googleapis.com/v1/projects/{self.project_id}/secrets/{name}"

    @staticmethod
    def _json(response) -> dict:
        status = int(getattr(response, "status_code", 0))
        if status < 200 or status >= 300:
            raise SecretProviderError(f"Secret Manager request failed with HTTP {status}")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise SecretProviderError("Secret Manager returned an invalid payload")
        return dict(payload)

    def access(self, secret_id: str, version: str = "latest") -> SecretValue:
        payload = self._json(self.session.get(
            f"{self._base(secret_id)}/versions/{str(version)}:access", timeout=15,
        ))
        encoded = str((payload.get("payload") or {}).get("data") or "")
        try:
            return SecretValue(base64.b64decode(encoded, validate=True))
        except (ValueError, TypeError) as exc:
            raise SecretProviderError("Secret Manager payload was not valid base64") from exc

    def add_version(self, secret_id: str, value: SecretValue) -> SecretVersion:
        payload = self._json(self.session.post(
            f"{self._base(secret_id)}:addVersion",
            json={"payload": {"data": base64.b64encode(value.reveal_bytes()).decode("ascii")}},
            timeout=15,
        ))
        version_id = str(payload.get("name") or "").rsplit("/", 1)[-1]
        if not version_id:
            raise SecretProviderError("Secret Manager did not return a version id")
        return SecretVersion(
            str(secret_id), version_id, str(payload.get("createTime") or ""),
            str(payload.get("state") or "ENABLED") == "ENABLED", value.fingerprint(),
        )

    def disable_version(self, secret_id: str, version: str) -> None:
        self._json(self.session.post(
            f"{self._base(secret_id)}/versions/{str(version)}:disable", json={}, timeout=15,
        ))


class InMemorySecretProvider:
    """Test-only provider. It is never selected by production configuration."""

    def __init__(self, values: Mapping[str, str | bytes] | None = None):
        self._values: dict[str, list[tuple[str, SecretValue, bool, str]]] = {}
        for name, value in dict(values or {}).items():
            self.add_version(name, SecretValue(value))

    def access(self, secret_id: str, version: str = "latest") -> SecretValue:
        rows = self._values.get(str(secret_id), [])
        candidates = [row for row in rows if row[2] and (version == "latest" or row[0] == str(version))]
        if not candidates:
            raise SecretProviderError("Secret version is unavailable")
        return candidates[-1][1]

    def add_version(self, secret_id: str, value: SecretValue) -> SecretVersion:
        rows = self._values.setdefault(str(secret_id), [])
        version = str(len(rows) + 1)
        created = dt.datetime.now(UTC).isoformat()
        rows.append((version, value, True, created))
        return SecretVersion(str(secret_id), version, created, True, value.fingerprint())

    def disable_version(self, secret_id: str, version: str) -> None:
        rows = self._values.get(str(secret_id), [])
        for index, row in enumerate(rows):
            if row[0] == str(version):
                rows[index] = (row[0], row[1], False, row[3])
                return
        raise SecretProviderError("Secret version is unavailable")


class RotationCoordinator:
    """Create, verify, then activate a version before retiring the old one."""

    def __init__(self, provider: ManagedSecretProvider, recorder: Callable[..., object] | None = None):
        self.provider = provider
        self.recorder = recorder
        self._lock = threading.Lock()

    def rotate(self, *, secret_id: str, old_version: str, new_value: SecretValue,
               validate: Callable[[SecretValue], bool], rotation_id: str | None = None) -> dict:
        if not callable(validate):
            raise SecretProviderError("A real post-rotation validator is required")
        with self._lock:
            identifier = str(rotation_id or uuid.uuid4())
            created = self.provider.add_version(secret_id, new_value)
            event = {
                "rotation_id": identifier, "secret_id": str(secret_id),
                "old_version": str(old_version), "new_version": created.version_id,
                "new_fingerprint": created.fingerprint,
                "rotated_at": dt.datetime.now(UTC).isoformat(),
            }
            try:
                if validate(self.provider.access(secret_id, created.version_id)) is not True:
                    raise SecretProviderError("New secret version failed validation")
            except Exception:
                self.provider.disable_version(secret_id, created.version_id)
                raise
            self.provider.disable_version(secret_id, old_version)
            result = {**event, "status": "ROTATED_AND_VALIDATED"}
            if self.recorder is not None:
                self.recorder(
                    aggregate_id=f"secret-rotation:{secret_id}",
                    event_type="SECRET_ROTATED", payload=result,
                    effective_at=dt.datetime.now(UTC),
                    idempotency_key=f"secret-rotation:{identifier}", source="managed-secret-rotation",
                )
            return result


def load_independent_approver_keys(provider: ManagedSecretProvider,
                                   references: Mapping[str, str]) -> dict[str, bytes]:
    refs = {str(identity).strip(): str(secret_id).strip()
            for identity, secret_id in dict(references or {}).items()}
    if len(refs) < 2 or len(set(refs.values())) != len(refs):
        raise SecretProviderError("Two independent identities with distinct secret references are required")
    keys = {identity: provider.access(secret_id).reveal_bytes() for identity, secret_id in refs.items()}
    if any(len(key) < 32 for key in keys.values()):
        raise SecretProviderError("Every approval key must contain at least 32 bytes")
    return keys


def parse_reference_map(raw: str) -> dict[str, str]:
    try:
        result = json.loads(str(raw or "{}"))
    except json.JSONDecodeError as exc:
        raise SecretProviderError("Managed secret reference map is invalid JSON") from exc
    if not isinstance(result, Mapping):
        raise SecretProviderError("Managed secret reference map must be an object")
    return {str(key): str(value) for key, value in result.items()}
