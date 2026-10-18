"""All-history operational receipt export on synthetic WASM Postgres, not hosted."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

SQL = Path('sql/archive_catalog_all_read_only.sql')


def test_static_read_only_full_denominator_contract() -> None:
    code = re.sub(r'--[^\n]*', '', SQL.read_text()).upper()
    assert 'REPEATABLE READ READ ONLY' in code
    assert code.rstrip().endswith('ROLLBACK;')
    assert "STATEMENT_TIMEOUT = '10S'" in code
    assert "LOCK_TIMEOUT = '2S'" in code
    assert not re.search(r'\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|COPY|GRANT|VACUUM|LIMIT)\b', code)
    assert code.count('WHERE') == 1 and 'FILTER (WHERE ORDINAL <= 4096 AND FIELDS_BOUNDED)' in code
    assert 'FROM QUANT_APP.ARCHIVE_MANIFESTS' in code
    assert 'VERIFIED_AT' in code and 'COMPLETED_AT' in code


@pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE') or not shutil.which('node'),
                    reason='Disposable WASM Postgres harness not configured')
def test_sql_preserves_old_export_null_deleted_and_overflow() -> None:
    script = r'''
const {PGlite}=require(process.argv[1]);const fs=require('fs');
(async()=>{const db=new PGlite();await db.waitReady;
await db.exec(`CREATE SCHEMA quant_app;
CREATE TABLE quant_app.archive_manifests(batch_id text,source_table text,row_count integer,
file_sha256 text,drive_file_id text,drive_manifest_id text,deleted_count integer,
verified_at timestamptz,completed_at timestamptz);
INSERT INTO quant_app.archive_manifests VALUES
('a','mf_nav',10,'hash','data-a','meta-a',NULL,'2022-01-03',NULL),
('b','equity_research.outcomes',20,'hash','data-b','meta-b',20,'2022-01-04','2022-01-05'),
('c','market_quotes',30,'hash','data-c','meta-c',0,'2022-01-06',NULL),
('d','unknown',40,'hash','data-d','meta-d',4,'2022-01-07','2022-01-08');`);
const sql=fs.readFileSync(process.argv[2],'utf8');
const pick=r=>r.flatMap(x=>x.rows||[]).filter(x=>x.private_archive_all_catalog).map(x=>x.private_archive_all_catalog);
const first=pick(await db.exec(sql));
await db.exec(`INSERT INTO quant_app.archive_manifests(batch_id,drive_file_id) VALUES ('huge',repeat('x',201));`);
const oversized=pick(await db.exec(sql));
await db.exec(`DELETE FROM quant_app.archive_manifests WHERE batch_id='huge';`);
await db.exec(`INSERT INTO quant_app.archive_manifests(batch_id) SELECT 'extra-'||g FROM generate_series(1,4093) g;`);
const overflow=pick(await db.exec(sql));
process.stdout.write(JSON.stringify({first,oversized,overflow}));await db.close();
})().catch(()=>{process.stderr.write('SYNTHETIC_SQL_FAILED');process.exitCode=1;});
'''
    output = subprocess.run(['node', '-e', script, os.environ['EQUITY_TEST_PGLITE_MODULE'], str(SQL)],
                            capture_output=True, text=True, check=True, timeout=60)
    result = json.loads(output.stdout)
    assert len(result['first']) == len(result['overflow']) == 1
    first = result['first'][0]
    assert first['total_count'] == 4 and first['truncated'] is False
    assert [r['batch_id'] for r in first['records']] == ['a', 'b', 'c', 'd']
    assert first['records'][0]['deleted_count'] is None
    assert first['records'][0]['completed_at'] is None
    assert first['records'][0]['verified_at'].startswith('2022-01-03')
    assert first['records'][1]['deleted_count'] == 20
    oversized = result['oversized'][0]
    assert oversized['total_count'] == 5
    assert oversized['records'] == [] and oversized['truncated'] is True
    overflow = result['overflow'][0]
    assert overflow['total_count'] == 4097
    assert overflow['records'] == [] and overflow['truncated'] is True
    assert overflow['status'] == 'BOUND_EXCEEDED_REVIEW_REQUIRED'
