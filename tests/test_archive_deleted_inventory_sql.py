"""Execute operational-metadata SQL against disposable synthetic WASM Postgres."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

SQL = Path('sql/archive_deleted_inventory_read_only.sql')


def test_inventory_is_single_result_fixed_window_read_only() -> None:
    text = SQL.read_text()
    code = re.sub(r'--[^\n]*', '', text).upper()
    assert 'ISOLATION LEVEL REPEATABLE READ READ ONLY' in code
    assert code.rstrip().endswith('ROLLBACK;')
    assert "STATEMENT_TIMEOUT = '10S'" in code
    assert not re.search(r'\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|COPY|GRANT|VACUUM)\b', code)
    assert '2026-10-17 18:25:14+00' in text
    assert 'm.deleted_count > 0' in text
    assert 'LIMIT ' not in code  # never silently truncate expected batches
    assert 'private_recovery_inventory' in text


@pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE') or not shutil.which('node'),
                    reason='Disposable SQL harness not configured')
def test_real_query_includes_every_deleted_receipt_and_excludes_outside_window() -> None:
    script = r'''
const {PGlite}=require(process.argv[1]);
const fs=require('fs');
(async()=>{
 const db=new PGlite();await db.waitReady;
 await db.exec(`CREATE SCHEMA quant_app;
 CREATE TABLE quant_app.archive_manifests(batch_id text,source_table text,row_count integer,
 file_sha256 text,drive_file_id text,drive_manifest_id text,deleted_count integer,completed_at timestamptz);
 INSERT INTO quant_app.archive_manifests VALUES
 ('b','market_quotes',100,'sha','data-b','manifest-b',100,'2026-10-16T22:54:45Z'),
 ('a','scanner_observations',20,'sha','data-a','manifest-a',12,'2026-10-11T00:00:00Z'),
 ('c','universe_membership',30,'sha','data-c','manifest-c',30,'2026-10-17T18:25:14Z'),
 ('old','market_quotes',10,'sha','data-old','manifest-old',10,'2026-10-10T23:59:59Z'),
 ('late','market_quotes',10,'sha','data-late','manifest-late',10,'2026-10-17T18:25:14.001Z'),
 ('zero','market_quotes',10,'sha','data-zero','manifest-zero',0,'2026-10-12T00:00:00Z'),
 ('unfinished','market_quotes',10,'sha','data-u','manifest-u',10,NULL);`);
 const results=await db.exec(fs.readFileSync(process.argv[2],'utf8'));
 const rows=results.flatMap(r=>r.rows||[]).filter(r=>r.private_recovery_inventory);
 process.stdout.write(JSON.stringify(rows));await db.close();
})().catch(()=>{process.stderr.write('SYNTHETIC_SQL_FAILED');process.exitCode=1;});
'''
    output = subprocess.run(['node', '-e', script, os.environ['EQUITY_TEST_PGLITE_MODULE'], str(SQL)],
                            capture_output=True, text=True, check=True, timeout=45)
    rows = json.loads(output.stdout)
    assert len(rows) == 1
    inventory = rows[0]['private_recovery_inventory']
    assert inventory['format'] == 'archive-recovery-inventory-v1'
    assert [b['batch_id'] for b in inventory['batches']] == ['a', 'b', 'c']
    assert sum(b['deleted_count'] for b in inventory['batches']) == 142
    assert inventory['batches'][0]['row_count'] == 20  # partial deletes retain original batch size
    assert inventory['window_start'].startswith('2026-10-11T00:00:00')
