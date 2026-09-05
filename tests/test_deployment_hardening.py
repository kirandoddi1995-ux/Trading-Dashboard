from pathlib import Path

import pytest

from deployment_security import (
    assess_database_role,
    authorize_identity,
    local_auth_bypass_allowed,
    missing_oidc_settings,
)
from environment_preflight import find_dependency_conflicts


ROOT = Path(__file__).resolve().parents[1]


class _Distribution:
    def __init__(self, name, version, requires=()):
        self.metadata = {"Name": name}
        self.version = version
        self.requires = list(requires)


def test_production_auth_is_before_service_initialization():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    page = source.index("st.set_page_config")
    gate = source.index("AUTHENTICATED_USER = require_streamlit_auth(st)")
    observability = source.index("OBSERVABILITY = observability.get_registry()")
    cache_schema = source.index("\n_ensure_cache_schema()\n", gate)
    first_service = source.index("MARKET_DATA_GATEWAY =")
    first_store = source.index("TECHNICAL_FEATURE_STORE =")
    assert page < gate < observability < cache_schema < first_service < first_store


def test_oidc_configuration_and_authorization_fail_closed():
    assert "client_secret" in missing_oidc_settings({"auth": {"client_id": "x"}})
    allowed, reason = authorize_identity(
        {"email": "intruder@example.com", "email_verified": True},
        allowed_emails=["owner@example.com"],
    )
    assert allowed is False and "not authorized" in reason
    allowed, _ = authorize_identity(
        {"email": "owner@example.com", "email_verified": True},
        allowed_emails=["OWNER@EXAMPLE.COM"],
    )
    assert allowed is True
    assert authorize_identity(
        {"email": "owner@example.com", "email_verified": False},
        allowed_emails=["owner@example.com"],
    )[0] is False


@pytest.mark.parametrize(
    ("app_env", "auth_mode", "flag", "expected"),
    [
        ("development", "disabled", "1", True),
        ("production", "disabled", "1", False),
        ("development", "oidc", "1", False),
        ("development", "disabled", "0", False),
    ],
)
def test_insecure_auth_bypass_requires_three_explicit_local_controls(app_env, auth_mode, flag, expected):
    assert local_auth_bypass_allowed(
        app_env=app_env, auth_mode=auth_mode, environ={"QUANT_ALLOW_INSECURE_LOCAL": flag},
    ) is expected


def test_owner_database_roles_and_privileges_are_rejected():
    safe, reasons = assess_database_role({
        "current_user": "postgres", "rolsuper": False, "rolcreatedb": False,
        "rolcreaterole": False, "rolreplication": False, "rolbypassrls": False,
        "schema_create": True,
    })
    assert safe is False
    assert any("administrative" in reason for reason in reasons)
    assert any("schema DDL" in reason for reason in reasons)

    safe, reasons = assess_database_role({
        "current_user": "quant_app_runtime", "rolsuper": False, "rolcreatedb": False,
        "rolcreaterole": False, "rolreplication": False, "rolbypassrls": False,
        "schema_create": False,
    })
    assert safe is True and reasons == []


def test_runtime_role_template_preserves_append_only_ledger_and_no_schema_create():
    sql = (ROOT / "database_runtime_role.sql.example").read_text(encoding="utf-8").upper()
    assert "REVOKE CREATE ON SCHEMA QUANT_APP" in sql
    assert "REVOKE UPDATE, DELETE, TRUNCATE" in sql
    assert "EVIDENCE_LEDGER_EVENTS" in sql
    assert "REPLACE_WITH_A_LONG_RANDOM_PASSWORD" in sql


def test_tensorflow_protobuf_mismatch_is_detected_without_importing_tensorflow():
    conflicts = find_dependency_conflicts([
        _Distribution("tensorflow", "2.21.0", ["protobuf>=6.31.1,<8.0.0"]),
        _Distribution("protobuf", "5.29.6"),
    ])
    assert conflicts == [{
        "package": "tensorflow", "dependency": "protobuf",
        "required": "<8.0.0,>=6.31.1", "actual": "5.29.6",
    }]


def test_release_inputs_pin_auth_and_exclude_tensorflow():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").casefold()
    constraints = (ROOT / "constraints.txt").read_text(encoding="utf-8").casefold()
    assert "authlib==1.8.0" in requirements
    assert "protobuf==7.36.0" in constraints
    assert "tensorflow" not in requirements
