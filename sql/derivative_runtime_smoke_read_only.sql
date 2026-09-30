-- AFTER both drafts and catalog permission review. Run the whole file as the SQL
-- Editor owner. SET LOCAL ROLE simulates permissions, NOT the app's connection.
-- READ ONLY and rolled back: no data changes. Nine rows, each rls_active=true,
-- visible_sample_rows=0 for new empty tables (1 is allowed if already populated).
BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL ROLE quant_app_runtime;
SELECT current_user AS role, 'derivatives_reference.contract_versions' AS relation,
 row_security_active('derivatives_reference.contract_versions') AS rls_active,
 (SELECT count(*) FROM (SELECT 1 FROM derivatives_reference.contract_versions LIMIT 1) s) AS visible_sample_rows
UNION ALL SELECT current_user,'derivatives_reference.source_snapshots',row_security_active('derivatives_reference.source_snapshots'),
 (SELECT count(*) FROM (SELECT 1 FROM derivatives_reference.source_snapshots LIMIT 1) s)
UNION ALL SELECT current_user,'derivatives_reference.source_health',row_security_active('derivatives_reference.source_health'),
 (SELECT count(*) FROM (SELECT 1 FROM derivatives_reference.source_health LIMIT 1) s)
UNION ALL SELECT current_user,'derivatives_reference.exchange_rules',row_security_active('derivatives_reference.exchange_rules'),
 (SELECT count(*) FROM (SELECT 1 FROM derivatives_reference.exchange_rules LIMIT 1) s)
UNION ALL SELECT current_user,'derivatives_reference.decision_snapshots',row_security_active('derivatives_reference.decision_snapshots'),
 (SELECT count(*) FROM (SELECT 1 FROM derivatives_reference.decision_snapshots LIMIT 1) s)
UNION ALL SELECT current_user,'derivatives_monitor.records',row_security_active('derivatives_monitor.records'),
 (SELECT count(*) FROM (SELECT 1 FROM derivatives_monitor.records LIMIT 1) s)
UNION ALL SELECT current_user,'derivatives_monitor.state',row_security_active('derivatives_monitor.state'),
 (SELECT count(*) FROM (SELECT 1 FROM derivatives_monitor.state LIMIT 1) s)
UNION ALL SELECT current_user,'derivatives_monitor.positions',row_security_active('derivatives_monitor.positions'),
 (SELECT count(*) FROM (SELECT 1 FROM derivatives_monitor.positions LIMIT 1) s)
UNION ALL SELECT current_user,'derivatives_monitor.alerts',row_security_active('derivatives_monitor.alerts'),
 (SELECT count(*) FROM (SELECT 1 FROM derivatives_monitor.alerts LIMIT 1) s);
ROLLBACK;
