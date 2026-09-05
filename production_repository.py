"""Durable PostgreSQL persistence for production evidence.

SQLite remains the low-latency local cache.  This repository stores the
small, irreplaceable records needed for point-in-time replay, calibration and
audit in PostgreSQL/Supabase.  Credentials are accepted only as constructor
arguments or environment variables and are never logged.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import threading
import urllib.parse
import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Iterable, Mapping

from evidence_ledger import GENESIS_HASH, LEDGER_SCHEMA_VERSION, canonical_json
from deployment_security import assess_database_role

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:  # Local/offline tests may intentionally omit PostgreSQL.
    psycopg = None
    Jsonb = None


SCHEMA = "quant_app"
SCHEMA_VERSION = 4


class RepositoryUnavailable(RuntimeError):
    """The durable repository is not configured or cannot be reached."""


def _safe_database_url_shape(database_url: str | None) -> dict:
    """Return non-secret connection metadata suitable for CI diagnostics."""
    text = str(database_url or "")
    result = {
        "parseable": False,
        "scheme_valid": text.startswith(("postgresql://", "postgres://")),
        "has_whitespace": any(char.isspace() for char in text),
        "has_surrounding_quotes": text[:1] in {"'", '"'} or text[-1:] in {"'", '"'},
    }
    try:
        parsed = urllib.parse.urlsplit(text)
        password = urllib.parse.unquote(parsed.password or "")
        result.update({
            "parseable": bool(parsed.scheme and parsed.hostname),
            "scheme": parsed.scheme,
            "username": urllib.parse.unquote(parsed.username or ""),
            "host": parsed.hostname or "",
            "port": parsed.port,
            "database": parsed.path.lstrip("/"),
            "password_present": parsed.password is not None,
            "password_length": len(password),
            "password_alphanumeric": bool(password) and password.isalnum(),
        })
    except Exception:
        result["parseable"] = False
    return result


def _connection_error_code(exc: Exception) -> str:
    """Classify a connection failure without returning provider text or secrets."""
    message = str(exc).casefold()
    checks = (
        (("password authentication failed", "authentication failed", "no password supplied"),
         "AUTHENTICATION_FAILED"),
        (("tenant or user not found", "user not found", "unknown tenant"),
         "POOLER_IDENTITY_NOT_FOUND"),
        (("circuit breaker", "too many authentication failures"),
         "POOLER_CIRCUIT_BREAKER"),
        (("worker_not_found", "worker not found"), "POOLER_NOT_READY"),
        (("could not translate host name", "name or service not known", "nodename nor servname",
          "temporary failure in name resolution"), "DNS_RESOLUTION_FAILED"),
        (("timeout", "timed out"), "CONNECTION_TIMEOUT"),
        (("network is unreachable", "no route to host"), "NETWORK_UNREACHABLE"),
        (("connection refused",), "CONNECTION_REFUSED"),
        (("gssapi", "gssencmode"), "GSS_NEGOTIATION_FAILED"),
        (("ssl", "tls"), "TLS_NEGOTIATION_FAILED"),
        (("server closed the connection unexpectedly", "connection reset by peer"),
         "CONNECTION_DROPPED"),
    )
    for needles, code in checks:
        if any(needle in message for needle in needles):
            return code
    return "OPERATIONAL_ERROR"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _utc_datetime(value) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _json(value):
    clean = json.loads(json.dumps(value or {}, default=str))
    return Jsonb(clean) if Jsonb is not None else clean


def _finite_decimal(value):
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except Exception:
        return None


def finite_or_raise(value, name: str) -> float:
    parsed = _finite_decimal(value)
    if parsed is None:
        raise ValueError(f"{name} must be finite")
    return float(parsed)


def _date_value(value):
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%d %b %Y", "%d-%b-%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _executemany(conn, statement: str, rows) -> None:
    """Execute a parameter batch through a DB-API cursor.

    Psycopg 3 exposes ``executemany`` on cursors, not connections. Keeping the
    compatibility detail here prevents bulk archive methods from accidentally
    using the SQLite-style connection API.
    """
    with conn.cursor() as cur:
        cur.executemany(statement, rows)


class ProductionRepository:
    """Small DB-API repository with idempotent PostgreSQL upserts."""

    def __init__(self, database_url: str | None = None, *, connect_timeout: int = 10,
                 evidence_signing_key: str | bytes | None = None,
                 schema_mode: str = "migrate", enforce_restricted_role: bool = False):
        self._database_url = str(database_url or os.environ.get("DATABASE_URL") or "").strip()
        self._connect_timeout = max(3, int(connect_timeout))
        if evidence_signing_key is None:
            evidence_signing_key = os.environ.get("EVIDENCE_LEDGER_SIGNING_KEY", "")
        if isinstance(evidence_signing_key, str):
            evidence_signing_key = evidence_signing_key.encode("utf-8")
        self._evidence_signing_key = evidence_signing_key or b""
        self._evidence_key_id = (hashlib.sha256(self._evidence_signing_key).hexdigest()[:16]
                                 if self._evidence_signing_key else "unsigned")
        self._schema_ready = False
        self._lock = threading.Lock()
        self._schema_mode = str(schema_mode).strip().casefold()
        if self._schema_mode not in {"migrate", "validate"}:
            raise ValueError("schema_mode must be 'migrate' or 'validate'")
        self._enforce_restricted_role = bool(enforce_restricted_role)

    @property
    def configured(self) -> bool:
        return self._database_url.startswith(("postgresql://", "postgres://"))

    @contextmanager
    def connect(self):
        if not self.configured:
            raise RepositoryUnavailable("DATABASE_URL is not configured")
        if psycopg is None:
            raise RepositoryUnavailable("psycopg is not installed")
        # The connection string is deliberately never included in exceptions or logs.
        try:
            conn = psycopg.connect(
                self._database_url,
                connect_timeout=self._connect_timeout,
                application_name="quant-terminal",
                sslmode="require",
            )
        except Exception as exc:
            code = _connection_error_code(exc)
            raise RepositoryUnavailable(f"PostgreSQL connection failed [{code}]") from exc
        try:
            yield conn
        finally:
            conn.close()

    def _migrate_schema(self) -> None:
        if self._schema_ready:
            return
        with self._lock:
            if self._schema_ready:
                return
            with self.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.schema_migrations (
                            version INTEGER PRIMARY KEY,
                            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.collection_runs (
                            run_id UUID PRIMARY KEY,
                            mode TEXT NOT NULL,
                            scheduled_for TIMESTAMPTZ,
                            started_at TIMESTAMPTZ NOT NULL,
                            finished_at TIMESTAMPTZ,
                            status TEXT NOT NULL,
                            provider TEXT NOT NULL,
                            record_count INTEGER NOT NULL DEFAULT 0,
                            error_kind TEXT,
                            error_message TEXT,
                            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                        )
                    """)
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.universe_snapshots (
                            snapshot_date DATE PRIMARY KEY,
                            observed_at TIMESTAMPTZ NOT NULL,
                            source TEXT NOT NULL,
                            instrument_count INTEGER NOT NULL,
                            payload_hash TEXT NOT NULL,
                            is_complete BOOLEAN NOT NULL,
                            schema_version INTEGER NOT NULL
                        )
                    """)
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.universe_membership (
                            snapshot_date DATE NOT NULL REFERENCES {SCHEMA}.universe_snapshots(snapshot_date)
                                ON DELETE CASCADE,
                            instrument_key TEXT NOT NULL,
                            trading_symbol TEXT NOT NULL,
                            isin TEXT,
                            name TEXT,
                            exchange TEXT,
                            segment TEXT,
                            instrument_type TEXT,
                            security_type TEXT,
                            sector TEXT,
                            source TEXT NOT NULL,
                            observed_at TIMESTAMPTZ NOT NULL,
                            raw JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            PRIMARY KEY (snapshot_date, instrument_key)
                        )
                    """)
                    cur.execute(f"CREATE INDEX IF NOT EXISTS universe_symbol_date_idx ON {SCHEMA}.universe_membership(trading_symbol, snapshot_date)")
                    cur.execute(f"CREATE INDEX IF NOT EXISTS universe_isin_date_idx ON {SCHEMA}.universe_membership(isin, snapshot_date)")
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.universe_snapshot_versions (
                            snapshot_id TEXT PRIMARY KEY,
                            snapshot_date DATE NOT NULL,
                            observed_at TIMESTAMPTZ NOT NULL,
                            source TEXT NOT NULL,
                            instrument_count INTEGER NOT NULL,
                            payload_hash TEXT NOT NULL,
                            is_complete BOOLEAN NOT NULL,
                            schema_version INTEGER NOT NULL,
                            UNIQUE(snapshot_date,payload_hash)
                        )
                    """)
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.universe_membership_versions (
                            snapshot_id TEXT NOT NULL REFERENCES {SCHEMA}.universe_snapshot_versions(snapshot_id),
                            instrument_key TEXT NOT NULL,
                            trading_symbol TEXT NOT NULL,
                            isin TEXT,
                            name TEXT,
                            exchange TEXT,
                            segment TEXT,
                            instrument_type TEXT,
                            security_type TEXT,
                            sector TEXT,
                            source TEXT NOT NULL,
                            observed_at TIMESTAMPTZ NOT NULL,
                            raw JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            PRIMARY KEY(snapshot_id,instrument_key)
                        )
                    """)
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.feature_observations (
                            feature_id TEXT PRIMARY KEY,
                            instrument_key TEXT NOT NULL,
                            feature_name TEXT NOT NULL,
                            effective_at TIMESTAMPTZ NOT NULL,
                            available_at TIMESTAMPTZ NOT NULL,
                            observed_at TIMESTAMPTZ NOT NULL,
                            source TEXT NOT NULL,
                            value JSONB NOT NULL,
                            payload_hash TEXT NOT NULL,
                            UNIQUE(instrument_key,feature_name,effective_at,available_at,payload_hash)
                        )
                    """)
                    cur.execute(f"CREATE INDEX IF NOT EXISTS feature_available_idx ON {SCHEMA}.feature_observations(instrument_key,feature_name,available_at)")
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.market_quotes (
                            observed_at TIMESTAMPTZ NOT NULL,
                            trade_date DATE NOT NULL,
                            instrument_key TEXT NOT NULL,
                            source TEXT NOT NULL,
                            last_price NUMERIC,
                            open NUMERIC,
                            high NUMERIC,
                            low NUMERIC,
                            previous_close NUMERIC,
                            volume NUMERIC,
                            open_interest NUMERIC,
                            raw JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            PRIMARY KEY (observed_at, instrument_key)
                        )
                    """)
                    cur.execute(f"CREATE INDEX IF NOT EXISTS quote_key_date_idx ON {SCHEMA}.market_quotes(instrument_key, trade_date)")
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.scanner_observations (
                            observation_id TEXT PRIMARY KEY,
                            as_of_date DATE NOT NULL,
                            observed_at TIMESTAMPTZ NOT NULL,
                            instrument_key TEXT NOT NULL,
                            trading_symbol TEXT NOT NULL,
                            strategy_version TEXT NOT NULL,
                            universe_snapshot_date DATE NOT NULL,
                            stage1_pass BOOLEAN NOT NULL,
                            stage2_pass BOOLEAN NOT NULL,
                            rejection_reason TEXT,
                            score DOUBLE PRECISION,
                            entry DOUBLE PRECISION,
                            stop DOUBLE PRECISION,
                            target DOUBLE PRECISION,
                            feature_json JSONB NOT NULL DEFAULT '{{}}'::jsonb
                        )
                    """)
                    cur.execute(f"CREATE INDEX IF NOT EXISTS scanner_date_strategy_idx ON {SCHEMA}.scanner_observations(as_of_date, strategy_version)")
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.corporate_actions (
                            isin TEXT NOT NULL,
                            action_type TEXT NOT NULL,
                            ex_date DATE NOT NULL,
                            record_date DATE,
                            amount DOUBLE PRECISION,
                            ratio TEXT,
                            source TEXT NOT NULL,
                            observed_at TIMESTAMPTZ NOT NULL,
                            raw JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            PRIMARY KEY (isin,action_type,ex_date,source)
                        )
                    """)
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.instrument_enrichment_checks (
                            isin TEXT NOT NULL,
                            resource TEXT NOT NULL,
                            checked_at TIMESTAMPTZ NOT NULL,
                            status TEXT NOT NULL,
                            PRIMARY KEY (isin,resource)
                        )
                    """)
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.prediction_targets (
                            observation_id TEXT NOT NULL REFERENCES {SCHEMA}.scanner_observations(observation_id)
                                ON DELETE CASCADE,
                            horizon_sessions INTEGER NOT NULL,
                            target_version TEXT NOT NULL,
                            entry_date DATE NOT NULL,
                            label_end_date DATE NOT NULL,
                            outcome_date DATE NOT NULL,
                            outcome TEXT NOT NULL,
                            target_before_stop BOOLEAN NOT NULL,
                            gross_return DOUBLE PRECISION NOT NULL,
                            net_return DOUBLE PRECISION NOT NULL,
                            benchmark_return DOUBLE PRECISION,
                            excess_return DOUBLE PRECISION,
                            positive_excess BOOLEAN,
                            cost_bps DOUBLE PRECISION NOT NULL,
                            entry_quality TEXT NOT NULL DEFAULT 'daily_open_fallback',
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            PRIMARY KEY (observation_id, horizon_sessions, target_version)
                        )
                    """)
                    cur.execute(
                        f"ALTER TABLE {SCHEMA}.prediction_targets ADD COLUMN IF NOT EXISTS "
                        "entry_quality TEXT NOT NULL DEFAULT 'daily_open_fallback'"
                    )
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.validation_runs (
                            run_id TEXT PRIMARY KEY,
                            created_at TIMESTAMPTZ NOT NULL,
                            strategy_version TEXT NOT NULL,
                            target_version TEXT NOT NULL,
                            horizon_sessions INTEGER NOT NULL,
                            training_samples INTEGER NOT NULL,
                            oos_samples INTEGER NOT NULL,
                            metrics JSONB NOT NULL,
                            model JSONB NOT NULL,
                            status TEXT NOT NULL,
                            status_reason TEXT NOT NULL,
                            result JSONB,
                            result_hash TEXT
                        )
                    """)
                    cur.execute(f"ALTER TABLE {SCHEMA}.validation_runs ADD COLUMN IF NOT EXISTS result JSONB")
                    cur.execute(f"ALTER TABLE {SCHEMA}.validation_runs ADD COLUMN IF NOT EXISTS result_hash TEXT")
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.mf_nav (
                            scheme_code TEXT NOT NULL,
                            nav_date DATE NOT NULL,
                            isin_growth TEXT,
                            isin_reinvestment TEXT,
                            scheme_name TEXT NOT NULL,
                            amc TEXT,
                            category TEXT,
                            plan TEXT,
                            option_name TEXT,
                            nav NUMERIC NOT NULL,
                            source TEXT NOT NULL,
                            observed_at TIMESTAMPTZ NOT NULL,
                            source_hash TEXT NOT NULL,
                            PRIMARY KEY (scheme_code, nav_date)
                        )
                    """)
                    cur.execute(f"CREATE INDEX IF NOT EXISTS mf_nav_category_date_idx ON {SCHEMA}.mf_nav(category, nav_date)")
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.mf_disclosures (
                            scheme_code TEXT NOT NULL,
                            effective_date DATE NOT NULL,
                            scheme_name TEXT,
                            category TEXT,
                            ter DOUBLE PRECISION,
                            benchmark TEXT,
                            benchmark_riskometer TEXT,
                            riskometer TEXT,
                            aum DOUBLE PRECISION,
                            status TEXT,
                            merger_into TEXT,
                            source TEXT NOT NULL,
                            observed_at TIMESTAMPTZ NOT NULL,
                            payload_hash TEXT NOT NULL,
                            raw JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            PRIMARY KEY (scheme_code, effective_date, source)
                        )
                    """)
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.data_quality_events (
                            event_id UUID PRIMARY KEY,
                            observed_at TIMESTAMPTZ NOT NULL,
                            component TEXT NOT NULL,
                            severity TEXT NOT NULL,
                            code TEXT NOT NULL,
                            message TEXT NOT NULL,
                            details JSONB NOT NULL DEFAULT '{{}}'::jsonb
                        )
                    """)
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.resilience_state_events (
                            event_id UUID PRIMARY KEY,
                            idempotency_key TEXT NOT NULL UNIQUE,
                            observed_at TIMESTAMPTZ NOT NULL,
                            correlation_id TEXT NOT NULL,
                            safety_state TEXT NOT NULL,
                            control_name TEXT NOT NULL,
                            code TEXT NOT NULL,
                            detail TEXT NOT NULL,
                            policy_version TEXT NOT NULL,
                            policy_hash TEXT NOT NULL,
                            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                        )
                    """)
                    cur.execute(f"CREATE INDEX IF NOT EXISTS resilience_state_time_idx ON {SCHEMA}.resilience_state_events(observed_at,safety_state)")
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.collector_leases (
                            lease_name TEXT PRIMARY KEY,
                            owner_id TEXT NOT NULL,
                            fencing_token BIGINT NOT NULL,
                            acquired_at TIMESTAMPTZ NOT NULL,
                            renewed_at TIMESTAMPTZ NOT NULL,
                            expires_at TIMESTAMPTZ NOT NULL
                        )
                    """)
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.runtime_attestations (
                            attestation_id UUID PRIMARY KEY,
                            observed_at TIMESTAMPTZ NOT NULL,
                            release_id TEXT NOT NULL,
                            config_hash TEXT NOT NULL,
                            model_hash TEXT NOT NULL,
                            dependency_hash TEXT NOT NULL,
                            signature_valid BOOLEAN NOT NULL,
                            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                        )
                    """)
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.execution_surveillance_events (
                            event_id UUID PRIMARY KEY,
                            idempotency_key TEXT NOT NULL UNIQUE,
                            observed_at TIMESTAMPTZ NOT NULL,
                            correlation_id TEXT NOT NULL,
                            order_id TEXT NOT NULL,
                            previous_status TEXT NOT NULL,
                            status TEXT NOT NULL,
                            ordered_quantity NUMERIC NOT NULL,
                            cumulative_quantity NUMERIC NOT NULL,
                            expected_price NUMERIC,
                            average_fill_price NUMERIC,
                            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                        )
                    """)
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.recovery_drills (
                            drill_id UUID PRIMARY KEY,
                            performed_at TIMESTAMPTZ NOT NULL,
                            backup_id TEXT NOT NULL,
                            rpo_minutes DOUBLE PRECISION NOT NULL,
                            rto_minutes DOUBLE PRECISION NOT NULL,
                            ledger_verified BOOLEAN NOT NULL,
                            runtime_role_verified BOOLEAN NOT NULL,
                            status TEXT NOT NULL,
                            evidence_hash TEXT NOT NULL,
                            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                        )
                    """)
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS {SCHEMA}.evidence_ledger_events (
                            event_id UUID PRIMARY KEY,
                            aggregate_id TEXT NOT NULL,
                            sequence_no INTEGER NOT NULL,
                            event_type TEXT NOT NULL,
                            recorded_at TIMESTAMPTZ NOT NULL,
                            effective_at TIMESTAMPTZ NOT NULL,
                            source TEXT NOT NULL,
                            actor_id TEXT NOT NULL,
                            idempotency_key TEXT NOT NULL UNIQUE,
                            payload JSONB NOT NULL,
                            previous_hash TEXT NOT NULL,
                            event_hash TEXT NOT NULL UNIQUE,
                            hash_algorithm TEXT NOT NULL,
                            schema_version INTEGER NOT NULL,
                            key_id TEXT,
                            UNIQUE(aggregate_id, sequence_no)
                        )
                    """)
                    cur.execute(f"ALTER TABLE {SCHEMA}.evidence_ledger_events ADD COLUMN IF NOT EXISTS key_id TEXT")
                    cur.execute(f"CREATE INDEX IF NOT EXISTS evidence_ledger_aggregate_idx ON {SCHEMA}.evidence_ledger_events(aggregate_id,sequence_no)")
                    cur.execute(f"""
                        CREATE OR REPLACE FUNCTION {SCHEMA}.reject_evidence_ledger_mutation()
                        RETURNS trigger LANGUAGE plpgsql AS $$
                        BEGIN
                            RAISE EXCEPTION 'evidence ledger events are immutable';
                        END;
                        $$
                    """)
                    cur.execute(f"DROP TRIGGER IF EXISTS evidence_ledger_no_update ON {SCHEMA}.evidence_ledger_events")
                    cur.execute(f"DROP TRIGGER IF EXISTS evidence_ledger_no_delete ON {SCHEMA}.evidence_ledger_events")
                    cur.execute(f"CREATE TRIGGER evidence_ledger_no_update BEFORE UPDATE ON {SCHEMA}.evidence_ledger_events FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_evidence_ledger_mutation()")
                    cur.execute(f"CREATE TRIGGER evidence_ledger_no_delete BEFORE DELETE ON {SCHEMA}.evidence_ledger_events FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_evidence_ledger_mutation()")
                    cur.execute(f"DROP TRIGGER IF EXISTS resilience_state_no_update ON {SCHEMA}.resilience_state_events")
                    cur.execute(f"DROP TRIGGER IF EXISTS resilience_state_no_delete ON {SCHEMA}.resilience_state_events")
                    cur.execute(f"CREATE TRIGGER resilience_state_no_update BEFORE UPDATE ON {SCHEMA}.resilience_state_events FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_evidence_ledger_mutation()")
                    cur.execute(f"CREATE TRIGGER resilience_state_no_delete BEFORE DELETE ON {SCHEMA}.resilience_state_events FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_evidence_ledger_mutation()")
                    cur.execute(
                        f"INSERT INTO {SCHEMA}.schema_migrations(version) VALUES (%s) ON CONFLICT DO NOTHING",
                        (SCHEMA_VERSION,),
                    )
                conn.commit()
            self._schema_ready = True

    def _validate_runtime_schema(self) -> None:
        """Verify migrations and least privilege without executing any DDL."""
        with self.connect() as conn:
            role_row = conn.execute(f"""
                SELECT current_user,r.rolsuper,r.rolcreatedb,r.rolcreaterole,
                       r.rolreplication,r.rolbypassrls,
                       has_schema_privilege(current_user,%s,'CREATE'),
                       to_regclass(%s)
                FROM pg_roles r WHERE r.rolname=current_user
            """, (SCHEMA, f"{SCHEMA}.schema_migrations")).fetchone()
            if not role_row:
                raise RepositoryUnavailable("Database role identity could not be verified")
            role = dict(zip(
                ("current_user", "rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication",
                 "rolbypassrls", "schema_create", "schema_migrations"),
                role_row,
            ))
            if role["schema_migrations"] is None:
                raise RepositoryUnavailable("Database schema is missing; run the migration job first")
            if self._enforce_restricted_role:
                restricted, reasons = assess_database_role(role)
                if not restricted:
                    raise RepositoryUnavailable("Restricted runtime database role required: " + "; ".join(reasons))
            version_row = conn.execute(
                f"SELECT COALESCE(MAX(version),0) FROM {SCHEMA}.schema_migrations"
            ).fetchone()
            version = int(version_row[0]) if version_row else 0
            if version < SCHEMA_VERSION:
                raise RepositoryUnavailable(
                    f"Database schema version {version} is older than required version {SCHEMA_VERSION}"
                )
            if self._enforce_restricted_role:
                permissions = conn.execute("""
                    SELECT
                      has_table_privilege(current_user,%s,'SELECT'),
                      has_table_privilege(current_user,%s,'INSERT'),
                      has_table_privilege(current_user,%s,'UPDATE'),
                      has_table_privilege(current_user,%s,'DELETE')
                """, (
                    f"{SCHEMA}.schema_migrations",
                    f"{SCHEMA}.evidence_ledger_events",
                    f"{SCHEMA}.evidence_ledger_events",
                    f"{SCHEMA}.evidence_ledger_events",
                )).fetchone()
                if not permissions or permissions[0] is not True or permissions[1] is not True:
                    raise RepositoryUnavailable("Runtime database role is missing required read/append grants")
                if permissions[2] is True or permissions[3] is True:
                    raise RepositoryUnavailable("Runtime role must not update or delete evidence ledger events")

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        if self._schema_mode == "migrate":
            self._migrate_schema()
            return
        with self._lock:
            if self._schema_ready:
                return
            self._validate_runtime_schema()
            self._schema_ready = True

    def health(self) -> dict:
        if not self.configured:
            return {"configured": False, "connected": False, "status": "Not configured"}
        try:
            self.ensure_schema()
            with self.connect() as conn:
                value = conn.execute("SELECT 1").fetchone()[0]
            return {"configured": True, "connected": value == 1, "status": "Connected"}
        except Exception as exc:
            return {
                "configured": True,
                "connected": False,
                "status": str(exc),
                "connection_shape": _safe_database_url_shape(self._database_url),
            }

    def acquire_collector_lease(self, lease_name: str, owner_id: str, *, ttl_seconds=180) -> dict | None:
        """Acquire a distributed lease and return a monotonically increasing fencing token."""
        self.ensure_schema()
        ttl_seconds = max(int(ttl_seconds), 10)
        if not str(lease_name).strip() or not str(owner_id).strip():
            raise ValueError("lease_name and owner_id are required")
        with self.connect() as conn:
            row = conn.execute(f"""
                INSERT INTO {SCHEMA}.collector_leases(
                    lease_name,owner_id,fencing_token,acquired_at,renewed_at,expires_at
                ) VALUES (%s,%s,1,NOW(),NOW(),NOW() + (%s * INTERVAL '1 second'))
                ON CONFLICT(lease_name) DO UPDATE SET
                    owner_id=EXCLUDED.owner_id,
                    fencing_token={SCHEMA}.collector_leases.fencing_token + 1,
                    acquired_at=NOW(),renewed_at=NOW(),expires_at=EXCLUDED.expires_at
                WHERE {SCHEMA}.collector_leases.expires_at <= NOW()
                   OR {SCHEMA}.collector_leases.owner_id=EXCLUDED.owner_id
                RETURNING lease_name,owner_id,fencing_token,acquired_at,renewed_at,expires_at
            """, (str(lease_name), str(owner_id), ttl_seconds)).fetchone()
            conn.commit()
        if not row:
            return None
        names = ("lease_name", "owner_id", "fencing_token", "acquired_at", "renewed_at", "expires_at")
        return dict(zip(names, row))

    def renew_collector_lease(self, lease_name: str, owner_id: str, fencing_token: int,
                              *, ttl_seconds=180) -> bool:
        """Renew only the current fenced owner; stale workers cannot revive themselves."""
        self.ensure_schema()
        with self.connect() as conn:
            row = conn.execute(f"""
                UPDATE {SCHEMA}.collector_leases
                SET renewed_at=NOW(),expires_at=NOW() + (%s * INTERVAL '1 second')
                WHERE lease_name=%s AND owner_id=%s AND fencing_token=%s AND expires_at>NOW()
                RETURNING fencing_token
            """, (max(int(ttl_seconds), 10), str(lease_name), str(owner_id), int(fencing_token))).fetchone()
            conn.commit()
        return bool(row)

    def release_collector_lease(self, lease_name: str, owner_id: str, fencing_token: int) -> bool:
        self.ensure_schema()
        with self.connect() as conn:
            row = conn.execute(f"""
                UPDATE {SCHEMA}.collector_leases SET expires_at=NOW(),renewed_at=NOW()
                WHERE lease_name=%s AND owner_id=%s AND fencing_token=%s
                RETURNING fencing_token
            """, (str(lease_name), str(owner_id), int(fencing_token))).fetchone()
            conn.commit()
        return bool(row)

    def record_resilience_snapshot(self, snapshot: Mapping, *, metadata=None) -> int:
        """Append each safety finding idempotently for audit and incident correlation."""
        self.ensure_schema()
        findings = list(snapshot.get("findings") or [])
        if not findings:
            findings = [{"control": "control_plane", "code": "HEALTHY", "detail": "No active findings"}]
        rows = []
        observed_at = _utc_datetime(snapshot.get("evaluated_at") or _utcnow())
        for index, finding in enumerate(findings):
            identity = canonical_json({
                "correlation_id": snapshot.get("correlation_id"), "index": index,
                "state": snapshot.get("state"), "finding": finding,
            })
            idempotency_key = hashlib.sha256(identity.encode()).hexdigest()
            rows.append((
                str(uuid.uuid4()), idempotency_key, observed_at,
                str(snapshot.get("correlation_id") or "unknown"), str(snapshot.get("state") or "UNKNOWN"),
                str(finding.get("control") or "unknown"), str(finding.get("code") or "UNKNOWN"),
                str(finding.get("detail") or "")[:1000], str(snapshot.get("policy_version") or "unknown"),
                str(snapshot.get("policy_hash") or "unknown"), _json(metadata),
            ))
        with self.connect() as conn:
            _executemany(conn, f"""
                INSERT INTO {SCHEMA}.resilience_state_events VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(idempotency_key) DO NOTHING
            """, rows)
            conn.commit()
        return len(rows)

    def record_runtime_attestation(self, *, release_id, config_hash, model_hash,
                                   dependency_hash, signature_valid, metadata=None) -> str:
        self.ensure_schema()
        attestation_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(f"""
                INSERT INTO {SCHEMA}.runtime_attestations VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (attestation_id, _utcnow(), str(release_id), str(config_hash), str(model_hash),
                    str(dependency_hash), bool(signature_valid), _json(metadata)))
            conn.commit()
        return attestation_id

    def record_recovery_drill(self, result: Mapping, *, backup_id, metadata=None) -> str:
        self.ensure_schema()
        material = canonical_json({"result": dict(result), "backup_id": str(backup_id)})
        drill_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(f"""
                INSERT INTO {SCHEMA}.recovery_drills VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                drill_id, _utc_datetime(result.get("performed_at") or _utcnow()), str(backup_id),
                finite_or_raise(result.get("rpo_minutes"), "rpo_minutes"),
                finite_or_raise(result.get("rto_minutes"), "rto_minutes"),
                bool(result.get("ledger_verified")), bool(result.get("runtime_role_verified")),
                str(result.get("status") or "UNKNOWN"), hashlib.sha256(material.encode()).hexdigest(),
                _json(metadata),
            ))
            conn.commit()
        return drill_id

    def start_run(self, mode: str, *, scheduled_for=None, provider="Upstox Analytics", metadata=None) -> str:
        self.ensure_schema()
        run_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                f"INSERT INTO {SCHEMA}.collection_runs(run_id,mode,scheduled_for,started_at,status,provider,metadata) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (run_id, str(mode), scheduled_for, _utcnow(), "RUNNING", provider, _json(metadata)),
            )
            conn.commit()
        return run_id

    def finish_run(self, run_id: str, *, status: str, record_count=0, error_kind=None,
                   error_message=None, metadata=None) -> None:
        self.ensure_schema()
        safe_message = str(error_message or "")[:500] or None
        with self.connect() as conn:
            conn.execute(
                f"UPDATE {SCHEMA}.collection_runs SET finished_at=%s,status=%s,record_count=%s,error_kind=%s,error_message=%s,metadata=metadata || %s WHERE run_id=%s",
                (_utcnow(), str(status), int(record_count), error_kind, safe_message, _json(metadata), run_id),
            )
            conn.commit()

    def archive_universe(self, records: Iterable[Mapping], snapshot_date, *, source="Upstox BOD NSE JSON",
                         minimum_complete=1000) -> dict:
        self.ensure_schema()
        rows = []
        for item in records:
            key = str(item.get("instrument_key") or "").strip()
            symbol = str(item.get("trading_symbol") or item.get("tradingsymbol") or "").strip().upper()
            if not key or not symbol:
                continue
            rows.append({
                "instrument_key": key, "trading_symbol": symbol,
                "isin": item.get("isin"), "name": item.get("name"),
                "exchange": item.get("exchange"), "segment": item.get("segment"),
                "instrument_type": item.get("instrument_type"), "security_type": item.get("security_type"),
                "sector": item.get("sector"), "raw": dict(item),
            })
        rows = list({row["instrument_key"]: row for row in rows}.values())
        rows.sort(key=lambda row: row["instrument_key"])
        payload_hash = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
        observed_at = _utcnow()
        complete = len(rows) >= int(minimum_complete)
        snapshot_id = hashlib.sha256(f"{snapshot_date}|{payload_hash}".encode()).hexdigest()
        with self.connect() as conn:
            existing = conn.execute(
                f"SELECT is_complete FROM {SCHEMA}.universe_snapshots WHERE snapshot_date=%s",
                (snapshot_date,),
            ).fetchone()
            conn.execute(
                f"INSERT INTO {SCHEMA}.universe_snapshot_versions VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(snapshot_id) DO NOTHING",
                (snapshot_id, snapshot_date, observed_at, source, len(rows), payload_hash, complete, SCHEMA_VERSION),
            )
            _executemany(conn,
                f"INSERT INTO {SCHEMA}.universe_membership_versions VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(snapshot_id,instrument_key) DO NOTHING",
                [(snapshot_id, r["instrument_key"], r["trading_symbol"], r["isin"], r["name"],
                  r["exchange"], r["segment"], r["instrument_type"], r["security_type"], r["sector"],
                  source, observed_at, _json(r["raw"])) for r in rows],
            )
            preserve_canonical = bool(existing and existing[0] and not complete)
            if not preserve_canonical:
                conn.execute(
                    f"INSERT INTO {SCHEMA}.universe_snapshots VALUES (%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT(snapshot_date) DO UPDATE SET observed_at=EXCLUDED.observed_at,source=EXCLUDED.source,instrument_count=EXCLUDED.instrument_count,payload_hash=EXCLUDED.payload_hash,is_complete=EXCLUDED.is_complete,schema_version=EXCLUDED.schema_version",
                    (snapshot_date, observed_at, source, len(rows), payload_hash, complete, SCHEMA_VERSION),
                )
                conn.execute(f"DELETE FROM {SCHEMA}.universe_membership WHERE snapshot_date=%s", (snapshot_date,))
                _executemany(conn,
                    f"INSERT INTO {SCHEMA}.universe_membership VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [(snapshot_date, r["instrument_key"], r["trading_symbol"], r["isin"], r["name"],
                      r["exchange"], r["segment"], r["instrument_type"], r["security_type"], r["sector"],
                      source, observed_at, _json(r["raw"])) for r in rows],
                )
            conn.commit()
        return {"date": str(snapshot_date), "count": len(rows), "complete": complete,
                "payload_hash": payload_hash, "canonical_preserved": preserve_canonical}

    def record_feature_observation(self, *, instrument_key: str, feature_name: str, value,
                                   effective_at, available_at, source: str) -> str:
        self.ensure_schema()
        effective_at = _utc_datetime(effective_at)
        available_at = _utc_datetime(available_at)
        payload_text = canonical_json({
            "instrument_key": instrument_key, "feature_name": feature_name, "value": value,
            "effective_at": effective_at, "available_at": available_at, "source": source,
        })
        payload_hash = hashlib.sha256(payload_text.encode()).hexdigest()
        feature_id = hashlib.sha256(
            f"{instrument_key}|{feature_name}|{effective_at}|{available_at}|{payload_hash}".encode()
        ).hexdigest()
        with self.connect() as conn:
            conn.execute(f"""
                INSERT INTO {SCHEMA}.feature_observations VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(feature_id) DO NOTHING
            """, (
                feature_id, str(instrument_key), str(feature_name), effective_at, available_at,
                _utcnow(), str(source), _json(json.loads(payload_text)["value"]), payload_hash,
            ))
            conn.commit()
        return feature_id

    def corporate_action_candidates(self, *, limit=100, refresh_days=30) -> list[str]:
        """Return dated-universe ISINs not checked recently."""
        self.ensure_schema()
        with self.connect() as conn:
            rows = conn.execute(f"""
                SELECT DISTINCT u.isin
                FROM {SCHEMA}.universe_membership u
                LEFT JOIN {SCHEMA}.instrument_enrichment_checks c
                  ON c.isin=u.isin AND c.resource='corporate_actions'
                WHERE u.snapshot_date=(SELECT MAX(snapshot_date) FROM {SCHEMA}.universe_snapshots)
                  AND u.isin IS NOT NULL AND u.isin<>''
                  AND (c.checked_at IS NULL OR c.checked_at < NOW() - (%s * INTERVAL '1 day'))
                ORDER BY u.isin LIMIT %s
            """, (max(1, int(refresh_days)), max(1, int(limit)))).fetchall()
        return [str(row[0]) for row in rows]

    def archive_corporate_actions(self, isin: str, actions: Iterable[Mapping],
                                  *, source="Upstox Corporate Actions API") -> int:
        self.ensure_schema()
        now = _utcnow()
        rows = []
        for item in actions or ():
            details = {
                str(detail.get("name") or "").strip().lower(): detail.get("value")
                for detail in (item.get("event_details") or []) if isinstance(detail, Mapping)
            }
            action_type = str(item.get("name") or item.get("type") or "").strip()
            ex_date = _date_value(
                item.get("ex_date") or item.get("expiry_date") or details.get("ex date")
                or details.get("ex dividend date") or details.get("ex split date")
            )
            if not action_type or ex_date is None:
                continue
            rows.append((
                str(isin), action_type, ex_date,
                _date_value(item.get("record_date") or details.get("record date")),
                float(_finite_decimal(item.get("amount"))) if _finite_decimal(item.get("amount")) is not None else None,
                item.get("ratio"), source, now, _json(dict(item)),
            ))
        if rows:
            with self.connect() as conn:
                _executemany(conn, f"""
                    INSERT INTO {SCHEMA}.corporate_actions VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(isin,action_type,ex_date,source) DO UPDATE SET
                        record_date=EXCLUDED.record_date,amount=EXCLUDED.amount,ratio=EXCLUDED.ratio,
                        observed_at=EXCLUDED.observed_at,raw=EXCLUDED.raw
                """, rows)
                conn.commit()
        return len(rows)

    def mark_enrichment_checked(self, isin: str, resource: str, status: str) -> None:
        self.ensure_schema()
        with self.connect() as conn:
            conn.execute(f"""
                INSERT INTO {SCHEMA}.instrument_enrichment_checks VALUES (%s,%s,%s,%s)
                ON CONFLICT(isin,resource) DO UPDATE SET checked_at=EXCLUDED.checked_at,status=EXCLUDED.status
            """, (str(isin), str(resource), _utcnow(), str(status)[:40]))
            conn.commit()

    def archive_quotes(self, quotes: Iterable[Mapping], *, observed_at=None, source="Upstox Market Quote V3") -> int:
        self.ensure_schema()
        observed_at = observed_at or _utcnow()
        rows = []
        for item in quotes:
            key = str(item.get("instrument_key") or item.get("instrument_token") or "").strip()
            if not key:
                continue
            ohlc = item.get("ohlc") or item.get("live_ohlc") or {}
            previous = item.get("prev_ohlc") or {}
            provider_time = item.get("last_trade_time") or item.get("ts")
            trade_date = observed_at.date()
            try:
                numeric_time = float(provider_time)
                if numeric_time > 10_000_000_000:
                    numeric_time /= 1000.0
                trade_date = dt.datetime.fromtimestamp(numeric_time, dt.timezone.utc).date()
            except (TypeError, ValueError, OSError):
                pass
            rows.append((
                observed_at, trade_date, key, source,
                _finite_decimal(item.get("last_price")), _finite_decimal(ohlc.get("open")),
                _finite_decimal(ohlc.get("high")), _finite_decimal(ohlc.get("low")),
                _finite_decimal(previous.get("close") or ohlc.get("close")),
                _finite_decimal(item.get("volume") or ohlc.get("volume")),
                _finite_decimal(item.get("oi") or item.get("open_interest")), _json(dict(item)),
            ))
        if not rows:
            return 0
        with self.connect() as conn:
            _executemany(conn,
                f"INSERT INTO {SCHEMA}.market_quotes VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                rows,
            )
            conn.commit()
        return len(rows)

    def upsert_scanner_observations(self, records: Iterable[Mapping]) -> int:
        self.ensure_schema()
        rows = []
        for item in records:
            key = str(item.get("instrument_key") or "").strip()
            symbol = str(item.get("trading_symbol") or "").strip().upper()
            as_of = str(item.get("as_of_date") or "")
            strategy = str(item.get("strategy_version") or "")
            if not key or not symbol or not as_of or not strategy:
                continue
            observation_id = item.get("observation_id") or hashlib.sha256(f"{as_of}|{key}|{strategy}".encode()).hexdigest()
            rows.append((
                observation_id, as_of, item.get("observed_at") or _utcnow(), key, symbol, strategy,
                item.get("universe_snapshot_date") or as_of, bool(item.get("stage1_pass")),
                bool(item.get("stage2_pass")), item.get("rejection_reason"), item.get("score"),
                item.get("entry"), item.get("stop"), item.get("target"), _json(item.get("features")),
            ))
        if not rows:
            return 0
        with self.connect() as conn:
            _executemany(conn, f"""
                INSERT INTO {SCHEMA}.scanner_observations VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(observation_id) DO UPDATE SET
                    observed_at=EXCLUDED.observed_at, stage1_pass=EXCLUDED.stage1_pass,
                    stage2_pass=EXCLUDED.stage2_pass, rejection_reason=EXCLUDED.rejection_reason,
                    score=COALESCE(EXCLUDED.score,{SCHEMA}.scanner_observations.score),
                    entry=COALESCE(EXCLUDED.entry,{SCHEMA}.scanner_observations.entry),
                    stop=COALESCE(EXCLUDED.stop,{SCHEMA}.scanner_observations.stop),
                    target=COALESCE(EXCLUDED.target,{SCHEMA}.scanner_observations.target),
                    feature_json=CASE WHEN EXCLUDED.feature_json='{{}}'::jsonb THEN {SCHEMA}.scanner_observations.feature_json ELSE EXCLUDED.feature_json END
            """, rows)
            conn.commit()
        return len(rows)

    def save_prediction_target(self, observation_id: str, target: Mapping) -> None:
        self.ensure_schema()
        with self.connect() as conn:
            conn.execute(f"""
                INSERT INTO {SCHEMA}.prediction_targets(
                    observation_id,horizon_sessions,target_version,entry_date,label_end_date,outcome_date,
                    outcome,target_before_stop,gross_return,net_return,benchmark_return,excess_return,
                    positive_excess,cost_bps,entry_quality)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(observation_id,horizon_sessions,target_version) DO UPDATE SET
                    entry_date=EXCLUDED.entry_date,label_end_date=EXCLUDED.label_end_date,
                    outcome_date=EXCLUDED.outcome_date,outcome=EXCLUDED.outcome,
                    target_before_stop=EXCLUDED.target_before_stop,gross_return=EXCLUDED.gross_return,
                    net_return=EXCLUDED.net_return,benchmark_return=EXCLUDED.benchmark_return,
                    excess_return=EXCLUDED.excess_return,positive_excess=EXCLUDED.positive_excess,
                    cost_bps=EXCLUDED.cost_bps,entry_quality=EXCLUDED.entry_quality
            """, (
                observation_id, target["horizon_sessions"], target["target_version"], target["entry_date"],
                target["label_end_date"], target["outcome_date"], target["outcome"],
                bool(target["target_before_stop"]), target["gross_return"], target["net_return"],
                target.get("benchmark_return"), target.get("excess_return"),
                (None if target.get("positive_excess") is None else bool(target["positive_excess"])),
                target["cost_bps"], target.get("entry_quality", "daily_open_fallback"),
            ))
            conn.commit()

    def save_validation_run(self, run_id: str, result: Mapping, *, horizon_sessions: int,
                            strategy_version: str, target_version: str) -> None:
        self.ensure_schema()
        with self.connect() as conn:
            conn.execute(f"""
                INSERT INTO {SCHEMA}.validation_runs(
                    run_id,created_at,strategy_version,target_version,horizon_sessions,
                    training_samples,oos_samples,metrics,model,status,status_reason,result,result_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(run_id) DO UPDATE SET
                    metrics=EXCLUDED.metrics,model=EXCLUDED.model,status=EXCLUDED.status,
                    status_reason=EXCLUDED.status_reason,oos_samples=EXCLUDED.oos_samples,
                    training_samples=EXCLUDED.training_samples,result=EXCLUDED.result,
                    result_hash=EXCLUDED.result_hash
            """, (
                run_id, _utcnow(), strategy_version, target_version, int(horizon_sessions),
                int(result.get("training_samples", 0)), int(result.get("oos_samples", 0)),
                _json(result.get("metrics")), _json({
                    "model": result.get("model"), "return_quantiles": result.get("return_quantiles"),
                    "policy": result.get("policy"), "folds": result.get("folds"),
                    "maturity": result.get("maturity"),
                }), result.get("status", "INSUFFICIENT_EVIDENCE"), result.get("reason", "Unknown"),
                _json(result), hashlib.sha256(canonical_json(result).encode()).hexdigest(),
            ))
            conn.commit()

    def pending_observations(self, *, horizons=(5, 10, 20), target_version="net-excess-execution-v2",
                             limit=100) -> list[dict]:
        """Return passed signals missing at least one requested horizon label."""
        self.ensure_schema()
        horizons = tuple(sorted({int(value) for value in horizons if int(value) > 0}))
        if not horizons:
            return []
        with self.connect() as conn:
            rows = conn.execute(f"""
                SELECT o.observation_id,o.as_of_date,o.observed_at,o.instrument_key,o.trading_symbol,
                       o.entry,o.stop,o.target,o.feature_json,
                       ARRAY(
                           SELECT h FROM UNNEST(%s::int[]) AS h
                           WHERE NOT EXISTS (
                               SELECT 1 FROM {SCHEMA}.prediction_targets t
                               WHERE t.observation_id=o.observation_id AND t.horizon_sessions=h
                                 AND t.target_version=%s
                           )
                       ) AS missing_horizons
                FROM {SCHEMA}.scanner_observations o
                WHERE o.stage2_pass=TRUE AND o.entry IS NOT NULL AND o.stop IS NOT NULL AND o.target IS NOT NULL
                ORDER BY o.as_of_date,o.instrument_key
                LIMIT %s
            """, (list(horizons), str(target_version), int(limit))).fetchall()
        names = ["observation_id", "as_of_date", "observed_at", "instrument_key", "trading_symbol",
                 "entry", "stop", "target", "features", "missing_horizons"]
        return [dict(zip(names, row)) for row in rows if row[-1]]

    def archive_mf_nav(self, records: Iterable[Mapping], *, source="AMFI NAVOpen.txt", source_hash="") -> int:
        self.ensure_schema()
        now = _utcnow()
        rows = []
        for item in records:
            nav = _finite_decimal(item.get("nav"))
            if not item.get("scheme_code") or not item.get("nav_date") or nav is None or nav <= 0:
                continue
            rows.append((
                str(item["scheme_code"]), item["nav_date"], item.get("isin_growth"),
                item.get("isin_reinvestment"), item.get("scheme_name"), item.get("amc"),
                item.get("category"), item.get("plan"), item.get("option"), nav,
                source, now, source_hash or item.get("source_hash") or "unknown",
            ))
        if not rows:
            return 0
        with self.connect() as conn:
            _executemany(conn, f"""
                INSERT INTO {SCHEMA}.mf_nav VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(scheme_code,nav_date) DO UPDATE SET
                    isin_growth=EXCLUDED.isin_growth,isin_reinvestment=EXCLUDED.isin_reinvestment,
                    scheme_name=EXCLUDED.scheme_name,amc=EXCLUDED.amc,category=EXCLUDED.category,
                    plan=EXCLUDED.plan,option_name=EXCLUDED.option_name,nav=EXCLUDED.nav,
                    source=EXCLUDED.source,observed_at=EXCLUDED.observed_at,source_hash=EXCLUDED.source_hash
            """, rows)
            conn.commit()
        return len(rows)

    def archive_mf_disclosures(self, records: Iterable[Mapping], *, source="AMFI official disclosure") -> int:
        self.ensure_schema()
        now = _utcnow()
        rows = []
        for item in records:
            code = str(item.get("scheme_code") or item.get("schemeCode") or "").strip()
            effective = item.get("effective_date") or item.get("performance_as_of") or item.get("risk_as_of")
            if not code or not effective:
                continue
            payload = json.loads(json.dumps(dict(item), default=str))
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            rows.append((
                code, effective, item.get("scheme_name") or item.get("schemeName"), item.get("category"),
                item.get("ter"), item.get("benchmark_name") or item.get("benchmark"),
                item.get("benchmark_riskometer"), item.get("riskometer"), item.get("aum"),
                item.get("status", "active"), item.get("merger_into"), source,
                now, digest, _json(payload),
            ))
        if not rows:
            return 0
        with self.connect() as conn:
            _executemany(conn, f"""
                INSERT INTO {SCHEMA}.mf_disclosures VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(scheme_code,effective_date,source) DO UPDATE SET
                    scheme_name=EXCLUDED.scheme_name,category=EXCLUDED.category,ter=EXCLUDED.ter,
                    benchmark=EXCLUDED.benchmark,benchmark_riskometer=EXCLUDED.benchmark_riskometer,
                    riskometer=EXCLUDED.riskometer,aum=EXCLUDED.aum,status=EXCLUDED.status,
                    merger_into=EXCLUDED.merger_into,observed_at=EXCLUDED.observed_at,
                    payload_hash=EXCLUDED.payload_hash,raw=EXCLUDED.raw
            """, rows)
            conn.commit()
        return len(rows)

    def record_quality_event(self, component: str, severity: str, code: str, message: str, details=None) -> str:
        self.ensure_schema()
        event_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                f"INSERT INTO {SCHEMA}.data_quality_events VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (event_id, _utcnow(), component, severity, code, str(message)[:1000], _json(details)),
            )
            conn.commit()
        return event_id

    def append_evidence_event(self, *, aggregate_id: str, event_type: str, payload: Mapping,
                              effective_at=None, source="quant-terminal", actor_id="system",
                              idempotency_key=None) -> dict:
        """Append one durable event under a transaction-level aggregate lock."""
        self.ensure_schema()
        aggregate_id = str(aggregate_id).strip()
        event_type = str(event_type).strip().upper()
        if not aggregate_id or not event_type:
            raise ValueError("aggregate_id and event_type are required")
        event_id = str(uuid.uuid4())
        idempotency_key = str(idempotency_key or uuid.uuid4())
        recorded_at = _utcnow()
        effective_at = _utc_datetime(effective_at or recorded_at)
        payload_text = canonical_json(payload)
        algorithm = "HMAC-SHA256" if self._evidence_signing_key else "SHA256 hash chain"
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (aggregate_id,))
            existing = conn.execute(
                f"SELECT event_id,aggregate_id,sequence_no,event_type,recorded_at,effective_at,source,actor_id,idempotency_key,payload,previous_hash,event_hash,hash_algorithm,schema_version,key_id FROM {SCHEMA}.evidence_ledger_events WHERE idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if existing:
                existing_payload = existing[9]
                if not isinstance(existing_payload, Mapping):
                    existing_payload = json.loads(str(existing_payload))
                same_request = (
                    str(existing[1]) == aggregate_id
                    and str(existing[3]) == event_type
                    and str(existing[6]) == str(source)
                    and str(existing[7]) == str(actor_id)
                    and canonical_json(existing_payload) == payload_text
                )
                if not same_request:
                    raise ValueError("Idempotency key is already bound to different durable evidence")
                conn.commit()
                return {"event_id": str(existing[0]), "aggregate_id": existing[1],
                        "sequence_no": int(existing[2]), "event_hash": existing[11], "duplicate": True}
            previous = conn.execute(
                f"SELECT sequence_no,event_hash FROM {SCHEMA}.evidence_ledger_events WHERE aggregate_id=%s ORDER BY sequence_no DESC LIMIT 1",
                (aggregate_id,),
            ).fetchone()
            sequence_no = int(previous[0]) + 1 if previous else 1
            previous_hash = str(previous[1]) if previous else GENESIS_HASH
            material = canonical_json({
                "event_id": event_id, "aggregate_id": aggregate_id, "sequence_no": sequence_no,
                "event_type": event_type, "recorded_at": recorded_at.isoformat(),
                "effective_at": effective_at.isoformat(), "source": source, "actor_id": actor_id,
                "idempotency_key": idempotency_key, "payload_json": payload_text,
                "previous_hash": previous_hash, "hash_algorithm": algorithm,
                "schema_version": LEDGER_SCHEMA_VERSION, "key_id": self._evidence_key_id,
            })
            if self._evidence_signing_key:
                event_hash = hmac.new(self._evidence_signing_key, material.encode(), hashlib.sha256).hexdigest()
            else:
                event_hash = hashlib.sha256(material.encode()).hexdigest()
            conn.execute(f"""
                INSERT INTO {SCHEMA}.evidence_ledger_events(
                    event_id,aggregate_id,sequence_no,event_type,recorded_at,effective_at,source,
                    actor_id,idempotency_key,payload,previous_hash,event_hash,hash_algorithm,schema_version,key_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                event_id, aggregate_id, sequence_no, event_type, recorded_at, effective_at,
                str(source), str(actor_id), idempotency_key, _json(json.loads(payload_text)),
                previous_hash, event_hash, algorithm, LEDGER_SCHEMA_VERSION, self._evidence_key_id,
            ))
            conn.commit()
        return {"event_id": event_id, "aggregate_id": aggregate_id, "sequence_no": sequence_no,
                "event_hash": event_hash, "duplicate": False}

    def stats(self) -> dict:
        if not self.configured:
            return {"configured": False}
        self.ensure_schema()
        with self.connect() as conn:
            row = conn.execute(f"""
                SELECT
                    (SELECT COUNT(*) FROM {SCHEMA}.universe_snapshots),
                    (SELECT COUNT(*) FROM {SCHEMA}.scanner_observations),
                    (SELECT COUNT(*) FROM {SCHEMA}.prediction_targets WHERE target_version='net-excess-execution-v2'),
                    (SELECT COUNT(*) FROM {SCHEMA}.mf_nav),
                    (SELECT MAX(finished_at) FROM {SCHEMA}.collection_runs WHERE status='SUCCESS'),
                    (SELECT COUNT(*) FROM {SCHEMA}.evidence_ledger_events)
            """).fetchone()
        return {
            "configured": True, "universe_days": int(row[0]), "observations": int(row[1]),
            "targets": int(row[2]), "mf_nav_rows": int(row[3]), "last_successful_collection": row[4],
            "ledger_events": int(row[5]),
        }
