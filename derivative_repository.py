"""Restricted reference storage and opt-in headless ingestion. No startup DDL."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import gzip
import hashlib
import json
import os

from derivative_contracts import FoundationError, digest
from derivative_restrictions import ban_url, parse_ban


class DerivativeRepository:
    def __init__(self, connect):
        self.connect = connect

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


def collect(repo, client, *, trading_date, underlyings, now):
    """Bounded watchlist only; no broad chain/tick ingestion or secret-bearing output."""
    if not underlyings or len(underlyings) > 30:
        raise FoundationError("Configure 1–30 derivative underlying keys")
    if any(not isinstance(key,str) or not key.startswith(('NSE_EQ|','NSE_INDEX|','BSE_EQ|','BSE_INDEX|')) for key in underlyings):
        raise FoundationError("Unsupported underlying venue")
    counts = {}
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
        repo.ingest_master(records, venue=venue, trading_date=trading_date, raw=raw, received_at=now)
        counts[venue] = len(records)
    if needs_nse:
        response = client.get(ban_url(trading_date), timeout=(5, 20))
        response.raise_for_status()
        repo.ingest_ban(response.content, trading_date=trading_date, source=response.url, received_at=now)
    return counts


def main():
    parser = argparse.ArgumentParser(description="Ingest scoped derivative reference data; never runs DDL")
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    import psycopg
    import requests
    try:
        url = os.environ["DERIVATIVE_REFERENCE_DATABASE_URL"]
        underlyings = json.loads(os.environ["DERIVATIVE_UNDERLYINGS_JSON"])
        if not isinstance(underlyings, list) or not all(isinstance(k, str) for k in underlyings):
            raise FoundationError("Invalid underlying configuration")
        def connect():
            conn = psycopg.connect(url, connect_timeout=10)
            try:
                role = conn.execute("SELECT rolname,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb "
                                    "FROM pg_roles WHERE rolname=current_user").fetchone()
                if not role or role[0] != "quant_derivative_ingestor" or any(role[1:]):
                    raise FoundationError("Restricted derivative ingestion role required")
                return conn
            except BaseException:
                conn.close()
                raise
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
