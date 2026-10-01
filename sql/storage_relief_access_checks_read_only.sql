-- EXTRA READ-ONLY CHECKS, before the relief migration. Run each numbered block
-- separately using BEGIN READ ONLY; SET LOCAL statement_timeout='5s';
-- SET LOCAL lock_timeout='1s'; <one block> ROLLBACK;
-- A timeout is a reason to stop/report, not to widen privileges or retry unbounded.

-- A. Connection identity (no secrets); use first on a newly configured connector.
SELECT current_user,session_user,current_setting('transaction_read_only') AS read_only,
       current_setting('statement_timeout') AS statement_timeout,
       current_setting('lock_timeout') AS lock_timeout,
       r.rolsuper,r.rolbypassrls,r.rolcreaterole,r.rolcreatedb
FROM pg_roles r WHERE r.rolname=current_user;

-- B. Actual scanner indexes, including validity and size. No index creation here.
SELECT idx.relname AS index_name,pg_get_indexdef(i.indexrelid) AS definition,
       i.indisvalid,i.indisready,i.indisunique,pg_relation_size(idx.oid) AS bytes,
       s.idx_scan
FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid
LEFT JOIN pg_stat_all_indexes s ON s.indexrelid=i.indexrelid
WHERE i.indrelid='quant_app.scanner_observations'::regclass ORDER BY idx.relname;

-- C. Owner and RLS flags on the two canonical tables.
SELECT c.oid::regclass::text AS relation,pg_get_userbyid(c.relowner) AS owner,
       c.relrowsecurity AS rls_enabled,c.relforcerowsecurity AS rls_forced
FROM pg_class c WHERE c.oid IN ('quant_app.universe_membership'::regclass,
                               'quant_app.universe_snapshots'::regclass);

-- D. Explicit table grants, including PUBLIC and grant option.
SELECT c.oid::regclass::text AS relation,
       CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END AS grantee,
       acl.privilege_type,acl.is_grantable
FROM pg_class c CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) acl
WHERE c.oid IN ('quant_app.universe_membership'::regclass,'quant_app.universe_snapshots'::regclass)
ORDER BY 1,2,3;

-- E. Explicit column grants can exist without table-wide SELECT.
SELECT a.attrelid::regclass::text AS relation,a.attname AS column_name,
       CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END AS grantee,
       acl.privilege_type,acl.is_grantable
FROM pg_attribute a CROSS JOIN LATERAL aclexplode(a.attacl) acl
WHERE a.attrelid IN ('quant_app.universe_membership'::regclass,'quant_app.universe_snapshots'::regclass)
AND a.attnum>0 AND NOT a.attisdropped ORDER BY 1,2,3;

-- F. Effective readers: inherited/PUBLIC/column access; excludes predefined
-- NOLOGIN capability roles but still includes real roles inheriting them.
SELECT c.oid::regclass::text AS relation,r.rolname,r.rolcanlogin,r.rolsuper,r.rolbypassrls,
       has_schema_privilege(r.oid,c.relnamespace,'USAGE') AS schema_usage,
       has_table_privilege(r.oid,c.oid,'SELECT') AS table_select,
       has_any_column_privilege(r.oid,c.oid,'SELECT') AS any_column_select
FROM pg_class c CROSS JOIN pg_roles r
WHERE c.oid IN ('quant_app.universe_membership'::regclass,'quant_app.universe_snapshots'::regclass)
AND r.rolname !~ '^pg_' AND has_any_column_privilege(r.oid,c.oid,'SELECT')
ORDER BY 1,2;

-- G. Existing policies; catalogue evidence only, not proof of all external callers.
SELECT schemaname,tablename,policyname,roles,cmd,qual,with_check FROM pg_policies
WHERE schemaname='quant_app' AND tablename IN ('universe_membership','universe_snapshots')
ORDER BY tablename,policyname;
