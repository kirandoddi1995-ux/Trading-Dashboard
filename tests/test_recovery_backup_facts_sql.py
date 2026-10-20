"""Static safety contract, NOT a claim that PostgreSQL executed this query."""
from pathlib import Path
import re


def test_catalog_only_bounded_rollback_no_business_rows_or_secrets() -> None:
    raw = (Path(__file__).resolve().parents[1] / 'sql/recovery_backup_facts_read_only.sql').read_text()
    sql = re.sub(r'--[^\n]*', '', raw).strip()
    assert sql.startswith('BEGIN READ ONLY;') and sql.endswith('ROLLBACK;')
    assert "statement_timeout = '10s'" in sql and "lock_timeout = '2s'" in sql
    assert 'k.ord <= i.indnkeyatts' in sql
    assert 'false AS backup_existence_established' in sql
    assert 'false AS physical_disk_free_established' in sql
    for forbidden in ('pg_authid', 'rolpassword', 'pg_get_functiondef', 'quant_app.',
                      'equity_research.', 'COPY ', 'INSERT ', 'UPDATE ', 'DELETE ',
                      'ALTER ', 'CREATE ', 'DROP ', 'COMMIT', 'pg_read_file', 'pg_ls_dir'):
        assert forbidden not in sql
    assert "pg_has_role('pg_read_all_stats', 'USAGE')" in sql
    assert "has_database_privilege(oid, 'CONNECT')" in sql
    assert "ELSE 'UNKNOWN_PERMISSION_OR_BOUND'" in sql
    assert 'databases <= 64 AND all_visible' in sql
    assert 'LIMIT 128' in sql and 'octet_length(extversion) <= 128' in sql
    assert sql.count('WITH targets(schema_name, relation_name) AS (VALUES') == 2
    assert sql.count("('equity_research', 'outcomes')") == 2
    assert 'LEFT JOIN pg_class' in sql  # Missing targets must not silently disappear.
