"""Fail-closed deployment controls for the hosted Streamlit application."""

from __future__ import annotations

import os
from collections.abc import Mapping


AUTH_REQUIRED_KEYS = (
    "redirect_uri",
    "cookie_secret",
    "client_id",
    "client_secret",
    "server_metadata_url",
)
ADMIN_DATABASE_ROLES = {
    "postgres",
    "supabase_admin",
    "dashboard_user",
    "service_role",
}


def _value(container, name, default=""):
    try:
        value = container.get(name, default)
    except Exception:
        value = default
    return value


def _csv_set(value) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = str(value or "").split(",")
    return {str(item).strip().casefold() for item in values if str(item).strip()}


def missing_oidc_settings(secrets) -> list[str]:
    auth = _value(secrets, "auth", {})
    if not isinstance(auth, Mapping) and not hasattr(auth, "get"):
        return list(AUTH_REQUIRED_KEYS)
    return [name for name in AUTH_REQUIRED_KEYS if not str(_value(auth, name, "")).strip()]


def local_auth_bypass_allowed(*, app_env: str, auth_mode: str, environ=None) -> bool:
    """Allow an insecure bypass only after two explicit local-development flags."""
    environ = environ or os.environ
    return (
        str(app_env).strip().casefold() == "development"
        and str(auth_mode).strip().casefold() == "disabled"
        and str(environ.get("QUANT_ALLOW_INSECURE_LOCAL", "")).strip() == "1"
    )


def authorize_identity(identity: Mapping, *, allowed_emails=(), allowed_domains=(),
                       require_verified_email=True) -> tuple[bool, str]:
    email = str(identity.get("email") or "").strip().casefold()
    if not email or "@" not in email:
        return False, "The identity provider did not supply a valid email address."
    verified = identity.get("email_verified")
    if require_verified_email and verified not in (True, "true", "True", 1, "1"):
        return False, "The identity provider did not confirm the email address."
    emails = _csv_set(allowed_emails)
    domains = {item.lstrip("@") for item in _csv_set(allowed_domains)}
    if not emails and not domains:
        return False, "No authorized email or domain allowlist is configured."
    domain = email.rsplit("@", 1)[1]
    if email not in emails and domain not in domains:
        return False, "This authenticated account is not authorized for this application."
    return True, "Authorized"


def assess_database_role(role: Mapping) -> tuple[bool, list[str]]:
    """Reject owner/admin roles and any role capable of schema DDL or bypassing RLS."""
    name = str(role.get("current_user") or "").strip().casefold()
    reasons = []
    if not name:
        reasons.append("database role identity is unavailable")
    if name in ADMIN_DATABASE_ROLES:
        reasons.append(f"administrative database role '{name}' is forbidden at runtime")
    for field, label in (
        ("rolsuper", "superuser"),
        ("rolcreatedb", "database creation"),
        ("rolcreaterole", "role creation"),
        ("rolreplication", "replication"),
        ("rolbypassrls", "RLS bypass"),
        ("schema_create", "schema DDL"),
    ):
        if role.get(field) is True:
            reasons.append(f"runtime role has {label} privilege")
    return not reasons, reasons


def require_streamlit_auth(st_module, *, environ=None):
    """Authenticate and authorize before any application service is initialized."""
    environ = environ or os.environ
    secrets = st_module.secrets
    app_env = str(_value(secrets, "APP_ENV", environ.get("APP_ENV", "production"))).strip()
    auth_mode = str(_value(secrets, "APP_AUTH_MODE", environ.get("APP_AUTH_MODE", "oidc"))).strip()

    if local_auth_bypass_allowed(app_env=app_env, auth_mode=auth_mode, environ=environ):
        return {"authenticated": True, "authorization": "explicit-local-development-bypass"}
    if auth_mode.casefold() != "oidc":
        st_module.error("Authentication is required. The insecure bypass is valid only for explicit local development.")
        st_module.stop()
    missing = missing_oidc_settings(secrets)
    if missing:
        st_module.error("Authentication is not configured. Ask the administrator to complete the OIDC settings.")
        st_module.caption("Missing settings: " + ", ".join(missing))
        st_module.stop()

    user = st_module.user
    if not bool(getattr(user, "is_logged_in", False)):
        st_module.title("Quant Terminal")
        st_module.info("Sign in with an approved account to continue.")
        st_module.button("Sign in", on_click=st_module.login, type="primary", key="oidc_sign_in")
        st_module.stop()

    identity = user.to_dict() if hasattr(user, "to_dict") else dict(user)
    allowed_emails = _value(secrets, "AUTH_ALLOWED_EMAILS", "")
    allowed_domains = _value(secrets, "AUTH_ALLOWED_DOMAINS", "")
    require_verified = str(_value(secrets, "AUTH_REQUIRE_VERIFIED_EMAIL", "true")).casefold() != "false"
    authorized, reason = authorize_identity(
        identity,
        allowed_emails=allowed_emails,
        allowed_domains=allowed_domains,
        require_verified_email=require_verified,
    )
    if not authorized:
        st_module.error(reason)
        st_module.button("Sign out", on_click=st_module.logout, key="unauthorized_sign_out")
        st_module.stop()

    st_module.sidebar.button("Sign out", on_click=st_module.logout, key="authorized_sign_out")
    return {"authenticated": True, "authorization": "allowlist", "subject": identity.get("sub")}
