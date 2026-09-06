import datetime as dt
import json

import pytest

from managed_secrets import (
    InMemorySecretProvider, RotationCoordinator, SecretProviderError,
    SecretValue, load_independent_approver_keys,
)
from observability import AlertRouter, MetricEvent, safe_endpoint
from recovery_drill import build_plan, request_restore
from secondary_quote_provider import KiteSecondaryQuoteProvider, SecondaryQuoteUnavailable


UTC = dt.timezone.utc


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class Session:
    def __init__(self, response=None):
        self.response = response or Response()
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.response


def test_managed_rotation_validates_before_retiring_old_and_never_reports_values():
    provider = InMemorySecretProvider({"artifact": b"a" * 32})
    coordinator = RotationCoordinator(provider)
    result = coordinator.rotate(
        secret_id="artifact", old_version="1", new_value=SecretValue(b"b" * 32),
        validate=lambda candidate: candidate.reveal_bytes() == b"b" * 32,
        rotation_id="rotation-1",
    )
    assert result["status"] == "ROTATED_AND_VALIDATED"
    assert "b" * 32 not in json.dumps(result)
    with pytest.raises(SecretProviderError):
        provider.access("artifact", "1")


def test_failed_rotation_keeps_old_version_enabled():
    provider = InMemorySecretProvider({"artifact": b"a" * 32})
    with pytest.raises(SecretProviderError, match="failed validation"):
        RotationCoordinator(provider).rotate(
            secret_id="artifact", old_version="1", new_value=SecretValue(b"b" * 32),
            validate=lambda candidate: False,
        )
    assert provider.access("artifact", "1").reveal_bytes() == b"a" * 32


def test_independent_approvers_require_distinct_managed_references():
    provider = InMemorySecretProvider({"risk": b"r" * 32, "deploy": b"d" * 32})
    keys = load_independent_approver_keys(provider, {"risk": "risk", "deploy": "deploy"})
    assert set(keys) == {"risk", "deploy"}
    with pytest.raises(SecretProviderError, match="distinct"):
        load_independent_approver_keys(provider, {"risk": "risk", "deploy": "risk"})


def test_kite_secondary_quotes_are_read_only_mapped_and_timestamped():
    payload = {"data": {"NSE:INFY": {
        "timestamp": "2026-09-06T10:00:00+05:30", "last_price": 1500,
        "depth": {"buy": [{"price": 1499.9}], "sell": [{"price": 1500.1}]},
    }}}
    session = Session(Response(200, payload))
    provider = KiteSecondaryQuoteProvider(
        api_key="key", access_token="token", symbol_map={"NSE_EQ|INFY": "NSE:INFY"},
        session=session,
    )
    quotes = provider.fetch(
        ["NSE_EQ|INFY"], now=dt.datetime(2026, 9, 6, 4, 30, 1, tzinfo=UTC),
    )
    assert quotes["NSE_EQ|INFY"].bid == 1499.9
    assert quotes["NSE_EQ|INFY"].exchange_at == "2026-09-06T04:30:00+00:00"
    assert session.calls[0][0] == "GET"
    assert "token" not in safe_endpoint(session.calls[0][1])


def test_secondary_quote_missing_mapping_fails_closed_without_request():
    session = Session()
    provider = KiteSecondaryQuoteProvider(
        api_key="key", access_token="token", symbol_map={"NSE_EQ|INFY": "NSE:INFY"},
        session=session,
    )
    with pytest.raises(SecondaryQuoteUnavailable, match="mapping missing"):
        provider.fetch(["NSE_EQ|TCS"])
    assert session.calls == []


def test_alert_router_sends_only_redacted_failure_context():
    session = Session(Response(202))
    router = AlertRouter("https://alerts.example.com/hook?secret=hidden", session=session,
                         signing_key="x" * 32)
    router.emit(MetricEvent(1.0, "collector", "scan", 20.0, ok=False,
                            status="FAILED", correlation_id="corr"))
    body = session.calls[0][2]["data"].decode()
    assert "hidden" not in body
    assert session.calls[0][2]["headers"]["X-Quant-Signature"]


def test_recovery_is_plan_only_until_distinct_target_and_confirmation():
    plan = build_plan(
        source_project_ref="production", dr_project_ref="isolated-dr",
        recovery_time=dt.datetime.now(UTC) - dt.timedelta(hours=1),
    )
    session = Session(Response(200, {"ok": True}))
    planned = request_restore(
        plan, access_token="", session=session, confirmation_token="", execute=False,
    )
    assert planned["network_write"] is False and session.calls == []
    with pytest.raises(ValueError, match="confirmation"):
        request_restore(
            plan, access_token="management-token", session=session,
            confirmation_token="wrong", execute=True,
        )
    operator = request_restore(
        plan, access_token="", session=session,
        confirmation_token=plan.confirmation_token, execute=True,
    )
    assert operator["status"] == "OPERATOR_ACTION_REQUIRED"
    assert operator["network_write"] is False and session.calls == []
    with pytest.raises(ValueError, match="distinct"):
        build_plan(
            source_project_ref="production", dr_project_ref="production",
            recovery_time=dt.datetime.now(UTC) - dt.timedelta(hours=1),
        )
