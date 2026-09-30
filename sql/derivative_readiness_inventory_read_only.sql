-- READ ONLY: run this entire SELECT before applying anything, and again afterwards.
-- One JSON result; no table contents, passwords, connection strings or pg_authid.
-- Object presence is NOT proof that a particular draft was applied correctly.
WITH schemas AS (
  SELECT oid,nspname FROM pg_namespace WHERE nspname IN
    ('quant_app','equity_operations','equity_research','derivatives_reference','derivatives_monitor')
), tables AS (
  SELECT c.*,n.nspname FROM pg_class c JOIN schemas n ON n.oid=c.relnamespace
  WHERE c.relkind IN ('r','p')
), roles AS (
  SELECT oid,rolname,rolcanlogin,rolinherit,rolsuper,rolbypassrls,rolcreaterole,
    rolcreatedb,rolreplication,rolconnlimit FROM pg_roles WHERE rolname IN ('quant_app_runtime','quant_archive_worker',
    'equity_research_collector','quant_derivative_ingestor','quant_derivative_monitor',
    'quant_derivative_watchdog','anon','authenticated','service_role')
), expected(name) AS (VALUES
  ('derivatives_reference.contract_versions'),('derivatives_reference.source_snapshots'),
  ('derivatives_reference.source_health'),('derivatives_reference.exchange_rules'),
  ('derivatives_reference.decision_snapshots'),('derivatives_monitor.records'),
  ('derivatives_monitor.state'),('derivatives_monitor.positions'),('derivatives_monitor.alerts')
)
SELECT jsonb_build_object(
  'checked_at',CURRENT_TIMESTAMP,
  'database_bytes',pg_database_size(current_database()),
  'schemas',(SELECT jsonb_agg(jsonb_build_object('name',n.nspname,
    'owner',pg_get_userbyid(n.nspowner),'acl',n.nspacl::text) ORDER BY n.nspname)
    FROM pg_namespace n WHERE n.oid IN (SELECT oid FROM schemas)),
  'expected_derivative_tables',(SELECT jsonb_agg(jsonb_build_object(
    'table',name,'present',to_regclass(name) IS NOT NULL) ORDER BY name) FROM expected),
  'migration_history_table_present',to_regclass('supabase_migrations.schema_migrations') IS NOT NULL,
  'tables',COALESCE((SELECT jsonb_agg(jsonb_build_object(
    'table',nspname||'.'||relname,'owner',pg_get_userbyid(relowner),
    'rls_enabled',relrowsecurity,'rls_forced',relforcerowsecurity,
    'estimated_rows',reltuples,'total_bytes',pg_total_relation_size(oid),
    'columns',(SELECT jsonb_agg(jsonb_build_object('name',a.attname,
       'type',format_type(a.atttypid,a.atttypmod),'not_null',a.attnotnull) ORDER BY a.attnum)
       FROM pg_attribute a WHERE a.attrelid=t.oid AND a.attnum>0 AND NOT a.attisdropped),
    'constraints',(SELECT jsonb_agg(jsonb_build_object('name',co.conname,
       'definition',pg_get_constraintdef(co.oid)) ORDER BY co.conname)
       FROM pg_constraint co WHERE co.conrelid=t.oid)
  ) ORDER BY nspname,relname) FROM tables t),'[]'::jsonb),
  'roles',COALESCE((SELECT jsonb_agg(jsonb_build_object('name',rolname,
    'login',rolcanlogin,'inherit',rolinherit,'superuser',rolsuper,'bypass_rls',rolbypassrls,
    'create_role',rolcreaterole,'create_db',rolcreatedb,'replication',rolreplication,
    'connection_limit',rolconnlimit) ORDER BY rolname) FROM roles),'[]'::jsonb),
  'role_memberships',COALESCE((SELECT jsonb_agg(jsonb_build_object(
    'member',member.rolname,'granted_role',parent.rolname,'admin_option',m.admin_option))
    FROM pg_auth_members m JOIN pg_roles member ON member.oid=m.member
    JOIN pg_roles parent ON parent.oid=m.roleid
    WHERE m.member IN (SELECT oid FROM roles) OR m.roleid IN (SELECT oid FROM roles)),'[]'::jsonb),
  'derivative_effective_privileges',COALESCE((SELECT jsonb_agg(jsonb_build_object(
    'role',r.rolname,'table',t.nspname||'.'||t.relname,
    'schema_usage',has_schema_privilege(r.oid,t.relnamespace,'USAGE'),
    'schema_create',has_schema_privilege(r.oid,t.relnamespace,'CREATE'),
    'table_privileges',ARRAY(SELECT p FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE',
        'TRUNCATE','REFERENCES','TRIGGER']) p WHERE has_table_privilege(r.oid,t.oid,p)),
    'column_writes',(SELECT jsonb_agg(a.attname||':'||p ORDER BY a.attnum,p)
       FROM pg_attribute a CROSS JOIN unnest(ARRAY['INSERT','UPDATE']) p
       WHERE a.attrelid=t.oid AND a.attnum>0 AND NOT a.attisdropped
         AND has_column_privilege(r.oid,t.oid,a.attnum,p))
  ) ORDER BY r.rolname,t.nspname,t.relname) FROM roles r CROSS JOIN tables t
  WHERE t.nspname IN ('derivatives_reference','derivatives_monitor')),'[]'::jsonb),
  'derivative_policies',COALESCE((SELECT jsonb_agg(jsonb_build_object(
    'schema',schemaname,'table',tablename,'policy',policyname,'roles',roles,
    'command',cmd,'permissive',permissive,'using',qual,'check',with_check)
    ORDER BY schemaname,tablename,policyname) FROM pg_policies
    WHERE schemaname IN ('derivatives_reference','derivatives_monitor')),'[]'::jsonb),
  'triggers',COALESCE((SELECT jsonb_agg(jsonb_build_object(
    'table',t.nspname||'.'||t.relname,'trigger',g.tgname,'enabled',g.tgenabled,
    'function',g.tgfoid::regprocedure::text) ORDER BY t.nspname,t.relname,g.tgname)
    FROM pg_trigger g JOIN tables t ON g.tgrelid=t.oid WHERE NOT g.tgisinternal),'[]'::jsonb),
  'function_fingerprints',COALESCE((SELECT jsonb_agg(jsonb_build_object(
    'function',p.oid::regprocedure::text,'security_definer',p.prosecdef,
    'definition_md5',md5(pg_get_functiondef(p.oid))) ORDER BY p.oid::regprocedure::text)
    FROM pg_proc p JOIN schemas s ON s.oid=p.pronamespace WHERE p.prokind IN ('f','p')),'[]'::jsonb),
  'default_grants',COALESCE((SELECT jsonb_agg(jsonb_build_object(
    'owner',pg_get_userbyid(d.defaclrole),'schema',n.nspname,'object_type',d.defaclobjtype,
    'acl',d.defaclacl::text)) FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
    WHERE d.defaclnamespace=0 OR d.defaclnamespace IN (SELECT oid FROM schemas)),'[]'::jsonb)
) AS readiness_inventory;
