"""Private research persistence; deliberately does not import ProductionRepository."""
from __future__ import annotations

from equity_research_observations import COHORT, POLICY, PURPOSE, digest

ROLE = 'equity_research_collector'


class ResearchRepository:
    def __init__(self, connection):
        self.connection = connection
        self.verify_permissions()

    def verify_permissions(self):
        row = self.connection.execute("""
            SELECT current_user, session_user, rolsuper, rolbypassrls, rolcreaterole,
                   rolcreatedb, rolreplication,
                   EXISTS (SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid),
                   has_schema_privilege(current_user, 'quant_app', 'USAGE')
            FROM pg_roles WHERE rolname=current_user
        """).fetchone()
        if not row or row[0] != ROLE or row[1] != ROLE or any(row[2:]):
            raise PermissionError('Dedicated restricted research login required')
        forbidden = self.connection.execute("""
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='quant_app' AND c.relkind IN ('r','p','v','m','f')
              AND (has_table_privilege(current_user,c.oid,'INSERT')
                OR has_table_privilege(current_user,c.oid,'UPDATE')
                OR has_table_privilege(current_user,c.oid,'DELETE')
                OR has_table_privilege(current_user,c.oid,'TRUNCATE')
                OR has_table_privilege(current_user,c.oid,'TRIGGER'))
        """).fetchall()
        dangerous_functions = self.connection.execute("""
            SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE p.prosecdef AND n.nspname NOT IN ('pg_catalog','information_schema')
              AND has_schema_privilege(current_user,n.oid,'USAGE')
              AND has_function_privilege(current_user,p.oid,'EXECUTE')
        """).fetchall()
        if forbidden or dangerous_functions:
            raise PermissionError('Research role has effective production writes or privileged function access')
        for table in ('source_decisions', 'observations', 'outcomes'):
            flags = self.connection.execute("""
                SELECT has_table_privilege(current_user,%s,'SELECT'),
                       has_table_privilege(current_user,%s,'INSERT'),
                       has_table_privilege(current_user,%s,'UPDATE'),
                       has_table_privilege(current_user,%s,'DELETE'),
                       has_table_privilege(current_user,%s,'TRUNCATE'),
                       has_table_privilege(current_user,%s,'TRIGGER')
            """, (f'equity_research.{table}',) * 6).fetchone()
            if tuple(flags) != (True, table != 'source_decisions', False, False, False, False):
                raise PermissionError('Unexpected research table privileges')

    def sources(self):
        rows = self.connection.execute(
            'SELECT event_id,event_hash,payload FROM equity_research.source_decisions ORDER BY decision_id'
        ).fetchall()
        if len(rows) != len(COHORT):
            raise ValueError('Research source snapshot must contain exactly 89 decisions')
        return [dict(event_id=str(r[0]), event_hash=r[1], payload=r[2]) for r in rows]

    def register(self, observation):
        identifier = observation['decision_id']
        if identifier not in COHORT or observation['policy'] != POLICY or observation['purpose'] != PURPOSE:
            raise ValueError('Unapproved research cohort or policy')
        from psycopg.types.json import Jsonb
        self.connection.execute("""
            INSERT INTO equity_research.observations(decision_id,payload)
            VALUES (%s,%s) ON CONFLICT (decision_id) DO NOTHING
        """, (identifier, Jsonb(observation)))
        stored = self.connection.execute(
            'SELECT payload FROM equity_research.observations WHERE decision_id=%s', (identifier,)
        ).fetchone()[0]
        original = {k: v for k, v in stored.items() if k != 'enrolled_at'}
        requested = {k: v for k, v in observation.items() if k != 'enrolled_at'}
        if original != requested:
            raise ValueError('Existing research observation differs; never overwrite')
        return stored

    def save_outcome(self, outcome):
        if (outcome['decision_id'] not in COHORT or outcome['policy'] != POLICY
                or outcome['purpose'] != PURPOSE or outcome['approved'] is not False):
            raise ValueError('Not a research-only outcome')
        from psycopg.types.json import Jsonb
        self.connection.execute("""
            INSERT INTO equity_research.outcomes(snapshot_id,decision_id,payload)
            VALUES (%s,%s,%s) ON CONFLICT (snapshot_id) DO NOTHING
        """, (digest(outcome), outcome['decision_id'], Jsonb(outcome)))

    def report(self):
        rows = self.connection.execute("""
            SELECT DISTINCT ON (decision_id) decision_id,payload FROM equity_research.outcomes
            ORDER BY decision_id,recorded_at DESC,snapshot_id DESC
        """).fetchall()
        return [{'decision_id': r[0], **{k: v for k, v in r[1].items()
                if k not in ('source_candles', 'session_calendar', 'missing_minutes')}} for r in rows]
