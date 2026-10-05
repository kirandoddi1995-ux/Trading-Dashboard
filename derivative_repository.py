"""Restricted reference storage and opt-in headless ingestion. No startup DDL."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import gzip
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

from derivative_contracts import FoundationError, digest, stamp, resolve_historical_contract
from derivative_restrictions import ban_url, parse_ban
from derivative_commissioning import (
    STORAGE_SQL, TABLES_SQL, assess, authorised, validate_source, validate_pilot_scope,
)


class DerivativeRepository:
    def __init__(self, connect):
        self.connect = connect

    def historical(self, key, *, now, version=None, rule_version=None):
        """Monitoring lookup survives expiry/master removal; never an entry fallback."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT payload,version FROM derivatives_reference.exchange_rules "
                        "WHERE instrument_key=%s AND known_at<=%s "
                        "AND (%s::text IS NULL OR version=%s) ORDER BY known_at DESC,version LIMIT 1",
                        (key,now,rule_version,rule_version))
            row = cur.fetchone()
            if not row or digest(row[0]) != row[1]:
                raise FoundationError('Historical reviewed contract unavailable')
            rules = row[0]
            if version is not None and rules['master_hash'] != version:
                raise FoundationError('Historical contract lineage mismatch')
            cur.execute("SELECT payload FROM derivatives_reference.contract_versions WHERE version=%s AND known_at<=%s",
                        (rules['master_hash'],now))
            row = cur.fetchone()
            if not row:
                raise FoundationError('Historical master unavailable')
            return resolve_historical_contract(row[0],rules,now=now)

    def reviewed(self, kind, key, *, now):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT payload,version FROM derivatives_monitor.records WHERE kind=%s "
                        "AND instrument_key=%s AND known_at<=%s ORDER BY known_at DESC,version LIMIT 1", (kind,key,now))
            row = cur.fetchone()
            if not row:
                return None
            if digest(row[0]) != row[1]:
                raise FoundationError('Reviewed record hash mismatch')
            return row[0]

    def publish_adjustment(self, event, old_master, new_master, new_rules, review):
        """Owner-only review transaction, never invoked by runtime/monitor ingestion.

        Preserve old rows and atomically publish lineage + exact replacement terms.
        No pricing event can take this route. Conflicts are errors, not overwrites.
        """
        from derivative_corporate_actions import validate_adjustment
        event_version = validate_adjustment(event,old_master,new_master)
        if (new_rules.get('master_hash') != digest(new_master) or review.get('event_version') != event_version
                or review.get('contract_version') != digest(new_master) or review.get('rule_version') != digest(new_rules)
                or stamp(review['quotes_after']) < stamp(event['effective_at'])):
            raise FoundationError('Adjustment review linkage mismatch')
        with self.connect() as conn, conn.cursor() as cur:
            for master in (old_master,new_master):
                cur.execute('INSERT INTO derivatives_reference.contract_versions VALUES(%s,%s::jsonb,%s) ON CONFLICT DO NOTHING',
                            (digest(master),json.dumps(master),event['known_at']))
            cur.execute('INSERT INTO derivatives_reference.exchange_rules VALUES(%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING',
                        (digest(new_rules),new_master['instrument_key'],new_rules['known_at'],json.dumps(new_rules,default=str)))
            for kind,payload in (('CONTRACT_ADJUSTMENT',event),('ADJUSTMENT_REVIEW',review)):
                cur.execute('INSERT INTO derivatives_monitor.records VALUES(%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING',
                            (digest(payload),kind,new_master['instrument_key'],event['known_at'],json.dumps(payload,default=str)))

    def monitor_state(self):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT account_key,status,checked_at,valid_until,unresolved_critical FROM derivatives_monitor.state WHERE singleton")
            row = cur.fetchone()
            return dict(zip(('account_key','status','checked_at','valid_until','unresolved_critical'),row)) if row else None

    def lifecycle_context(self, key, *, now, account_key):
        state = self.monitor_state()
        if not state or state['account_key'] != account_key:
            raise FoundationError('Monitor account unavailable or mismatched')
        return dict(state, broker_policy=self.reviewed('BROKER_POLICY',key,now=now),
                    adjustment_review=self.reviewed('ADJUSTMENT_REVIEW',key,now=now))

    @contextmanager
    def monitor_lock(self):
        # Serialize polls across hosts without a host-specific lock service.
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_xact_lock(71943012)')
            if not cur.fetchone()[0]:
                raise FoundationError('Monitor already running')
            yield

    def set_monitor_state(self, account_key, status, now, ttl, critical=True):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO derivatives_monitor.state VALUES(true,%s,%s,%s,%s,%s) "
                        "ON CONFLICT(singleton) DO UPDATE SET account_key=excluded.account_key,status=excluded.status,"
                        "checked_at=excluded.checked_at,valid_until=excluded.valid_until,unresolved_critical=excluded.unresolved_critical",
                        (account_key,status,now,stamp(now)+timedelta(seconds=ttl),critical))

    def positions(self):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT position_key,payload FROM derivatives_monitor.positions ORDER BY position_key')
            return dict(cur.fetchall())

    def save_position(self, key, payload, now):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO derivatives_monitor.positions VALUES(%s,%s,%s,%s,%s::jsonb,%s) "
                        "ON CONFLICT(position_key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                        (key,payload['account_key'],payload['instrument_key'],payload['product'],json.dumps(payload,default=str),now))

    def alert(self, code, now):
        # One retryable record per condition; no token, account, or position data in email.
        key = digest({'alert':code})
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO derivatives_monitor.alerts(alert_id,code,first_seen,last_seen,next_attempt) "
                        "VALUES(%s,%s,%s,%s,%s) ON CONFLICT(alert_id) DO UPDATE SET active=true,last_seen=excluded.last_seen,"
                        "next_attempt=CASE WHEN derivatives_monitor.alerts.active THEN derivatives_monitor.alerts.next_attempt ELSE excluded.next_attempt END,"
                        "acknowledged_at=CASE WHEN derivatives_monitor.alerts.active THEN derivatives_monitor.alerts.acknowledged_at ELSE NULL END",
                        (key,code,now,now,now))

    def clear_alert(self, code):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('UPDATE derivatives_monitor.alerts SET active=false WHERE alert_id=%s',(digest({'alert':code}),))

    def alerts(self):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('SELECT alert_id,code,last_seen,acknowledged_at,delivered_at,last_error FROM derivatives_monitor.alerts WHERE active ORDER BY last_seen DESC')
            return [dict(zip(('alert_id','code','last_seen','acknowledged_at','delivered_at','last_error'),r)) for r in cur.fetchall()]

    def acknowledge(self, key, now):
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute('UPDATE derivatives_monitor.alerts SET acknowledged_at=%s WHERE alert_id=%s AND active',(now,key))

    def claim_email(self, now):
        token = str(uuid4())
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("WITH due AS (SELECT alert_id FROM derivatives_monitor.alerts WHERE active AND next_attempt<=%s "
                        "AND (lease_until IS NULL OR lease_until<=%s) ORDER BY next_attempt FOR UPDATE SKIP LOCKED LIMIT 1) "
                        "UPDATE derivatives_monitor.alerts a SET lease_token=%s::uuid,lease_until=%s,attempts=attempts+1 "
                        "FROM due WHERE a.alert_id=due.alert_id RETURNING a.alert_id,a.code,a.attempts",
                        (now,now,token,stamp(now)+timedelta(minutes=2)))
            row = cur.fetchone()
            return (*row,token) if row else None

    def finish_email(self, key, token, now, *, success, attempts):
        delay = 21600 if success else min(3600,60 * 2**min(attempts,6))
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE derivatives_monitor.alerts SET lease_token=NULL,lease_until=NULL,next_attempt=%s,"
                        "delivered_at=CASE WHEN %s THEN %s ELSE delivered_at END,last_error=%s WHERE alert_id=%s AND lease_token=%s::uuid",
                        (stamp(now)+timedelta(seconds=delay),success,now,None if success else 'EMAIL_DELIVERY_FAILED',key,token))

    @staticmethod
    def _health(cur, kind, trading_date, status, now, source_hash=None):
        cur.execute("INSERT INTO derivatives_reference.source_health(kind,trading_date,status,updated_at,source_hash) "
                    "VALUES(%s,%s,%s,%s,%s) ON CONFLICT(kind,trading_date) DO UPDATE "
                    "SET status=excluded.status,updated_at=excluded.updated_at,source_hash=excluded.source_hash "
                    "WHERE derivatives_reference.source_health.updated_at<=excluded.updated_at",
                    (kind,trading_date,status,now,source_hash))

    def mark_pending(self, kind, trading_date, now):
        # Commit before fetching: a failed refresh must not leave yesterday's/same-day
        # successful snapshot masquerading as the result of the failed attempt.
        with self.connect() as conn, conn.cursor() as cur:
            self._health(cur,kind,trading_date,"UNKNOWN",now)

    def ingest_master(self, records, *, venue, trading_date, raw, received_at):
        if venue not in {"NSE", "BSE"} or not records or len(records) > 10000:
            raise FoundationError("Empty or unsupported instrument master")
        keys = [r.get("instrument_key") for r in records]
        if None in keys or len(set(keys)) != len(keys):
            raise FoundationError("Duplicate/missing instrument identifiers")
        if any(r.get("exchange") != venue or r.get("segment") != venue + "_FO" for r in records):
            raise FoundationError("Instrument venue mismatch")
        versions = {r["instrument_key"]: digest(r) for r in records}
        # One scoped daily manifest; raw selected records are recoverable in version rows.
        with self.connect() as conn, conn.cursor() as cur:
            for record in records:
                cur.execute("INSERT INTO derivatives_reference.contract_versions(version,payload,known_at) "
                            "VALUES (%s,%s::jsonb,%s) ON CONFLICT DO NOTHING",
                            (digest(record), json.dumps(record), received_at))
            self._source(cur, "MASTER_" + venue, trading_date, versions, raw, received_at)
            self._health(cur,"MASTER_"+venue,trading_date,"READY",received_at,hashlib.sha256(raw).hexdigest())

    @staticmethod
    def _source(cur, kind, trading_date, payload, raw, received_at):
        source_hash = hashlib.sha256(raw).hexdigest()
        cur.execute("INSERT INTO derivatives_reference.source_snapshots "
                    "(kind,trading_date,source_hash,payload,raw,received_at) "
                    "VALUES (%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT DO NOTHING",
                    (kind, trading_date, source_hash, json.dumps(payload),
                     gzip.compress(raw, mtime=0), received_at))

    def ingest_ban(self, raw, *, trading_date, source, received_at):
        ban = parse_ban(raw, trading_date=trading_date, source=source, received_at=received_at)
        with self.connect() as conn, conn.cursor() as cur:
            self._source(cur, "NSE_BAN", trading_date, {"source": source}, raw, received_at)
            self._health(cur,"NSE_BAN",trading_date,"READY",received_at,ban.sha256)
        return ban

    def load(self, key, *, venue, trading_date, now):
        """No previous-date fallback and no selection of reference data known in the future."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT kind,status FROM derivatives_reference.source_health "
                        "WHERE trading_date=%s AND updated_at<=%s", (trading_date,now))
            health = dict(cur.fetchall())
            if health.get("MASTER_"+venue) != "READY":
                return None, None, None
            cur.execute("WITH latest AS (SELECT s.payload FROM derivatives_reference.source_snapshots s "
                        "JOIN derivatives_reference.source_health h USING(kind,trading_date,source_hash) "
                        "WHERE s.kind=%s AND s.trading_date=%s AND s.received_at<=%s AND h.status='READY') "
                        "SELECT c.payload FROM latest s JOIN derivatives_reference.contract_versions c "
                        "ON c.version=s.payload->>%s", ("MASTER_" + venue, trading_date, now, key))
            row = cur.fetchone()
            master = row[0] if row else None
            cur.execute("SELECT payload,version FROM derivatives_reference.exchange_rules WHERE instrument_key=%s "
                        "AND known_at<=%s ORDER BY known_at DESC LIMIT 1", (key, now))
            row = cur.fetchone()
            rules = row[0] if row else None
            if row and digest(rules) != row[1]:
                raise FoundationError("Stored exchange rule fingerprint mismatch")
            cur.execute("SELECT s.raw,s.payload,s.received_at,s.source_hash FROM derivatives_reference.source_snapshots s "
                        "JOIN derivatives_reference.source_health h USING(kind,trading_date,source_hash) "
                        "WHERE s.kind='NSE_BAN' AND s.trading_date=%s AND s.received_at<=%s "
                        "AND h.status='READY'", (trading_date, now))
            row = cur.fetchone()
            ban = (parse_ban(gzip.decompress(bytes(row[0])), trading_date=trading_date,
                             source=row[1]["source"], received_at=row[2])
                   if row and health.get("NSE_BAN") == "READY" else None)
            if ban is not None and ban.sha256 != row[3]:
                raise FoundationError("Retained ban source hash mismatch")
        return master, rules, ban

    def record_snapshot(self, result, *, now):
        if not result.eligible:
            raise FoundationError("Cannot record rejected snapshot as eligible")
        payload = dict(result.snapshot, ban_status=result.ban_status)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO derivatives_reference.decision_snapshots "
                        "(snapshot_id,contract_version,rule_version,recorded_at,payload) "
                        "VALUES (%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING",
                        (result.snapshot["snapshot_id"], result.contract.version,
                         result.contract.rule_version, now, json.dumps(payload, default=str)))


def collect(repo, client, *, trading_date, underlyings, now, clock=None):
    """Bounded watchlist only; no broad chain/tick ingestion or secret-bearing output."""
    stamp(now)
    if not underlyings or len(underlyings) > 30:
        raise FoundationError("Configure 1–30 derivative underlying keys")
    if any(not isinstance(key,str) or not key.startswith(('NSE_EQ|','NSE_INDEX|','BSE_EQ|','BSE_INDEX|')) for key in underlyings):
        raise FoundationError("Unsupported underlying venue")
    counts = {}
    receipt_clock = clock or (lambda: datetime.now(timezone.utc))
    last_received = stamp(now)
    def received():
        nonlocal last_received
        value = stamp(receipt_clock())
        if value < last_received:
            raise FoundationError("Receipt clock moved backwards")
        last_received = value
        return value
    needs_nse = any(key.startswith('NSE_') for key in underlyings)
    if needs_nse:
        repo.mark_pending("NSE_BAN",trading_date,now)
    for venue in ("NSE", "BSE"):
        if not any(key.startswith(venue + "_") for key in underlyings):
            continue
        repo.mark_pending("MASTER_"+venue,trading_date,now)
        url = f"https://assets.upstox.com/market-quote/instruments/exchange/{venue}.json.gz"
        response = client.get(url, timeout=(5, 30))
        response.raise_for_status()
        content = response.content
        if content[:2] == b"\x1f\x8b":
            content = gzip.decompress(content)
        records = [r for r in json.loads(content) if r.get("underlying_key") in underlyings
                   and r.get("segment") == venue + "_FO"]
        # Retain exactly the scoped source records, not megabytes of unrelated masters daily.
        raw = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
        validate_source(raw)
        repo.ingest_master(records, venue=venue, trading_date=trading_date, raw=raw, received_at=received())
        counts[venue] = len(records)
    if needs_nse:
        response = client.get(ban_url(trading_date), timeout=(5, 20))
        response.raise_for_status()
        validate_source(response.content)
        repo.ingest_ban(response.content, trading_date=trading_date, source=response.url, received_at=received())
    return counts


def main():
    parser = argparse.ArgumentParser(description="Ingest scoped derivative reference data; never runs DDL")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--mode", choices=("preview", "check", "pilot"), default="preview")
    args = parser.parse_args()
    if args.mode == "preview":
        print(json.dumps({"status": "PREVIEW", "network_calls": 0, "writes": 0,
                          "recurring_ingestion_commissioned": False, "approval_authority": False}))
        return 0
    import psycopg
    import requests
    try:
        if args.mode == "pilot" and not authorised(
                "pilot", event=os.environ.get("DERIVATIVE_RUN_EVENT", ""),
                confirmation=os.environ.get("DERIVATIVE_PILOT_CONFIRMATION", "false")):
            raise FoundationError("One-run manual pilot confirmation required")
        url = os.environ["DERIVATIVE_REFERENCE_DATABASE_URL"]
        underlyings = json.loads(os.environ.get("DERIVATIVE_UNDERLYINGS_JSON", "[]"))
        if not isinstance(underlyings, list) or not all(isinstance(k, str) for k in underlyings):
            raise FoundationError("Invalid underlying configuration")
        def connect():
            conn = psycopg.connect(url, connect_timeout=10,
                                   options="-c statement_timeout=10000 -c lock_timeout=2000" +
                                   (" -c default_transaction_read_only=on" if args.mode == "check" else ""))
            try:
                role = conn.execute("SELECT rolname,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication "
                                    "FROM pg_roles WHERE rolname=current_user").fetchone()
                if not role or role[0] != "quant_derivative_ingestor" or any(role[1:]):
                    raise FoundationError("Restricted derivative ingestion role required")
                tables = conn.execute(TABLES_SQL).fetchone()
                if not tables or tables[0] != 9 or tables[1] is not True:
                    raise FoundationError("Nine derivative tables with RLS required")
                sizes = conn.execute(STORAGE_SQL).fetchone()
                report = assess(*sizes) if sizes else None
                if report is None or (args.mode == "pilot" and not report["pilot_storage_allowed"]):
                    raise FoundationError("Pilot storage admission blocked")
                return conn
            except BaseException:
                conn.close()
                raise
        if args.mode == "check":
            with connect() as conn:
                report = assess(*conn.execute(STORAGE_SQL).fetchone())
                print(json.dumps(report))
            return 0 if report["pilot_storage_allowed"] else 1
        validate_pilot_scope(args.date, underlyings, datetime.now(timezone.utc))
        with requests.Session() as client:
            result = collect(DerivativeRepository(connect), client, trading_date=args.date,
                             underlyings=underlyings, now=datetime.now(timezone.utc))
        print(json.dumps({"status": "SUCCESS", "contracts": result}))
        return 0
    except Exception:
        print(json.dumps({"status": "FAILED", "reason": "Derivative reference ingestion failed; entries remain fail-closed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
