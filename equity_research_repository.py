"""Private research persistence; deliberately does not import ProductionRepository."""
from __future__ import annotations

from equity_research_observations import COHORT, POLICY, PURPOSE, aware, digest

ROLE = 'equity_research_collector'


def outcome_evidence(payload):
    """Compare evidence, not the time an identical provider response was fetched.

    Preserve raw candles, hashes, calendar, gaps, provenance and classifications.
    Non-session time adds no coverage; only normalize validated session gaps.
    Stored records are never changed; the first fetch provenance remains intact.
    """
    evidence = dict(payload)
    evidence.pop('assessed_at', None)
    evidence.pop('fetched_at', None)
    if evidence.get('horizon_complete') is True:
        try:
            close = aware(evidence['horizon_close'])
            through = aware(evidence['requested_data_through'])
            if through >= close:
                evidence['requested_data_through'] = close.isoformat()
        except (KeyError, ValueError, TypeError):
            pass  # Malformed/absent provenance never earns normalization.
    elif evidence.get('horizon_complete') is False:
        try:
            from equity_research_outcomes import sessions_for
            calendar = evidence['session_calendar']
            start = aware(evidence['tracking_start'])
            through = aware(evidence['requested_data_through'])
            fetched = aware(payload['fetched_at'])
            assessed = aware(payload['assessed_at'])
            # Reuse the evaluator's calendar validation; tracking_start must be
            # an eligible minute in its first session. Ambiguity means no dedup.
            sessions = sessions_for({'decision_at': start.isoformat(),
                                     'horizon_sessions': len(calendar['sessions'])}, calendar)
            close = aware(evidence['horizon_close'])
            if (start.second or start.microsecond or close != sessions[-1][1]
                    or not start <= through <= fetched <= assessed or through >= close):
                return evidence
            # Within a session retain the exact cutoff. Across weekends/holidays,
            # normalize only after confirming the expected coverage count agrees.
            if any(opening < through < closing for opening, closing in sessions):
                return evidence
            completed = [(opening, closing) for opening, closing in sessions if closing <= through]
            expected = sum(int((closing - max(opening, start)).total_seconds() // 60)
                           for opening, closing in completed)
            if (completed and type(evidence['expected_minutes']) is int
                    and evidence['expected_minutes'] == expected):
                evidence['requested_data_through'] = completed[-1][1].isoformat()
        except (KeyError, ValueError, TypeError, IndexError, AttributeError, OverflowError):
            pass  # Keep original cutoff if calendar or provenance cannot be verified.
    return evidence


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
              -- Event-trigger functions cannot be called as ordinary SQL functions.
              AND p.prorettype <> 'pg_catalog.event_trigger'::regtype
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
            'SELECT event_id,event_hash,payload,verified_payload_sha256 '
            'FROM equity_research.source_decisions ORDER BY decision_id'
        ).fetchall()
        if len(rows) != len(COHORT):
            raise ValueError('Research source snapshot must contain exactly 89 decisions')
        return [dict(event_id=str(r[0]), event_hash=r[1], payload=r[2],
                     verified_payload_sha256=r[3]) for r in rows]

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
        # Transaction-scoped serialization also prevents two overlapping collectors
        # from storing the same evidence with different fetch timestamps.
        self.connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                                ('equity-research-outcome:' + outcome['decision_id'],))
        previous = self.connection.execute("""
            SELECT payload FROM equity_research.outcomes WHERE decision_id=%s
            ORDER BY recorded_at DESC,snapshot_id DESC LIMIT 1
        """, (outcome['decision_id'],)).fetchone()
        if previous and outcome_evidence(previous[0]) == outcome_evidence(outcome):
            return False
        inserted = self.connection.execute("""
            INSERT INTO equity_research.outcomes(snapshot_id,decision_id,payload)
            VALUES (%s,%s,%s) ON CONFLICT (snapshot_id) DO NOTHING
            RETURNING snapshot_id
        """, (digest(outcome), outcome['decision_id'], Jsonb(outcome))).fetchone()
        return inserted is not None

    def report(self):
        rows = self.connection.execute("""
            SELECT DISTINCT ON (decision_id) decision_id,payload FROM equity_research.outcomes
            ORDER BY decision_id,recorded_at DESC,snapshot_id DESC
        """).fetchall()
        return [{'decision_id': r[0], **{k: v for k, v in r[1].items()
                if k not in ('source_candles', 'session_calendar', 'missing_minutes')}} for r in rows]
