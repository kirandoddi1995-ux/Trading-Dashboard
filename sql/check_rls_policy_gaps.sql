-- READ ONLY. Run before and after any RLS or grant change (Supabase SQL editor or
-- read-only MCP). Changes nothing.
--
-- Lists every (role, table, privilege) where the role holds a table GRANT on a table
-- with RLS enabled, but no permissive policy for that command applies to the role
-- (directly, via role membership, or via PUBLIC). Such a role is silently locked
-- out: INSERT/UPDATE raise "violates row-level security policy", SELECT/DELETE
-- quietly see zero rows. This is how the 9 Nov 2026 collector outage happened.
--
-- Expected rows (deliberate lock-outs, verified 9 Nov 2026):
--   authenticated      quant_app.mf_nav             SELECT   (app does not use Supabase auth)
--   quant_app_runtime  quant_app.archive_manifests  INSERT,SELECT,UPDATE  (worker-only table; stray grant)
-- Any other row is a real gap: add a policy (see sql/runtime_rls_policies.sql) or
-- revoke the grant, BEFORE enabling RLS.
--
-- Coverage notes:
-- * Reads pg_class.relacl (not information_schema), so grants are listed even for
--   roles the current user is not a member of. A NULL relacl means default
--   privileges (owner only), expanded with acldefault().
-- * PUBLIC grants (grantee 0) are reported as role 'PUBLIC'; only a PUBLIC policy
--   counts as covering them, so the check is conservative there.
-- * The table owner is skipped (RLS does not apply to it) unless the table has
--   FORCE ROW LEVEL SECURITY. Superusers and BYPASSRLS roles are always skipped.

WITH grants AS (
    SELECT n.nspname AS schema_name, c.relname AS table_name, c.oid AS relid,
           CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE r.rolname END AS role_name,
           a.grantee AS roleid, a.privilege_type AS privilege
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    CROSS JOIN LATERAL aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
    LEFT JOIN pg_roles r ON r.oid = a.grantee
    WHERE c.relkind IN ('r', 'p')
      AND c.relrowsecurity
      AND a.privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
      AND (a.grantee = 0 OR (NOT r.rolsuper AND NOT r.rolbypassrls))
      AND (a.grantee <> c.relowner OR c.relforcerowsecurity)
      AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'auth', 'storage', 'realtime',
                            'supabase_functions', 'vault', 'cron', 'net', 'graphql',
                            'graphql_public', 'pgsodium', 'extensions', 'supabase_migrations')
)
SELECT g.role_name, g.schema_name, g.table_name,
       string_agg(g.privilege, ',' ORDER BY g.privilege) AS privileges_without_policy
FROM grants g
WHERE NOT EXISTS (
    SELECT 1
    FROM pg_policy p
    WHERE p.polrelid = g.relid
      AND p.polpermissive
      AND p.polcmd::text IN ('*', CASE g.privilege WHEN 'SELECT' THEN 'r' WHEN 'INSERT' THEN 'a'
                                                   WHEN 'UPDATE' THEN 'w' WHEN 'DELETE' THEN 'd' END)
      AND EXISTS (SELECT 1 FROM unnest(p.polroles) pr
                  WHERE pr = 0 OR (g.roleid <> 0 AND pg_has_role(g.roleid, pr, 'MEMBER')))
)
GROUP BY g.role_name, g.schema_name, g.table_name
ORDER BY g.role_name, g.schema_name, g.table_name;
