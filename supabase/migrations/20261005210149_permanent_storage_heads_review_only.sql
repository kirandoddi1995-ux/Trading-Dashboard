-- REVIEW ONLY: unfinished storage group. NO hosted application authorized.
-- Requires both preceding permanent_storage migrations. Disabled by default.
-- No automatic bootstrap: owner must verify available original signatures and
-- pin the audited terminal heads before enabling tracking or pruning.
BEGIN;
SET LOCAL lock_timeout='2s';
SET LOCAL statement_timeout='30s';
SELECT pg_advisory_xact_lock(hashtext('quant-storage-schema-v1'));
DO $preflight$
BEGIN
  IF to_regclass('quant_storage.ledger_control') IS NULL
     OR to_regclass('quant_storage.catalog_roots') IS NULL
     OR to_regclass('quant_app.evidence_ledger_events') IS NULL THEN
    RAISE EXCEPTION 'STORAGE_HEAD_DEPENDENCY_MISSING';
  END IF;
  IF (SELECT nspowner FROM pg_namespace WHERE nspname='quant_storage')
       IS DISTINCT FROM current_user::regrole
     OR obj_description('quant_storage.ledger_control'::regclass,'pg_class')
       IS DISTINCT FROM 'permanent-storage-ledger-control-v1' THEN
    RAISE EXCEPTION 'STORAGE_HEAD_OWNER_OR_VERSION_UNEXPECTED';
  END IF;
  IF EXISTS(SELECT 1 FROM pg_class WHERE oid=to_regclass('quant_storage.ledger_hot_heads')
            AND (relowner<>current_user::regrole OR obj_description(oid,'pg_class')
                 IS DISTINCT FROM 'permanent-storage-hot-heads-v1')) THEN
    RAISE EXCEPTION 'STORAGE_HEAD_VERSION_UNEXPECTED';
  END IF;
END;
$preflight$;
CREATE TABLE IF NOT EXISTS quant_storage.ledger_hot_heads (
  aggregate_id text PRIMARY KEY CHECK(octet_length(aggregate_id) BETWEEN 1 AND 900),
  sequence_no bigint NOT NULL CHECK(sequence_no>=1),
  event_hash text NOT NULL CHECK(event_hash ~ '^[0-9a-f]{64}$')
);
COMMENT ON TABLE quant_storage.ledger_hot_heads IS 'permanent-storage-hot-heads-v1';
DO $shape$
BEGIN
  IF (SELECT array_agg(attname::text ORDER BY attname) FROM pg_attribute
      WHERE attrelid='quant_storage.ledger_hot_heads'::regclass
        AND attnum>0 AND NOT attisdropped) IS DISTINCT FROM
       ARRAY['aggregate_id','event_hash','sequence_no']::text[]
     OR EXISTS(SELECT 1 FROM pg_policy
                WHERE polrelid='quant_storage.ledger_hot_heads'::regclass
                  AND polname NOT IN ('storage_head_reader','storage_head_owner')) THEN
    RAISE EXCEPTION 'STORAGE_HEAD_SHAPE_UNEXPECTED';
  END IF;
END;
$shape$;
ALTER TABLE quant_storage.ledger_hot_heads ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_storage.ledger_hot_heads FORCE ROW LEVEL SECURITY;
REVOKE ALL ON quant_storage.ledger_hot_heads FROM PUBLIC,quant_app_runtime,quant_storage_archiver;
DO $permissions$
DECLARE role_name text;
BEGIN
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role',
                                  'quant_archive_worker','equity_research_collector'] LOOP
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
      EXECUTE format('REVOKE ALL ON quant_storage.ledger_hot_heads FROM %I',role_name);
    END IF;
  END LOOP;
  DROP POLICY IF EXISTS storage_head_owner ON quant_storage.ledger_hot_heads;
  EXECUTE format('CREATE POLICY storage_head_owner ON quant_storage.ledger_hot_heads
                 FOR ALL TO %I USING(true) WITH CHECK(true)',current_user);
END;
$permissions$;
GRANT SELECT ON quant_storage.ledger_hot_heads TO quant_app_runtime,quant_storage_archiver;
DROP POLICY IF EXISTS storage_head_reader ON quant_storage.ledger_hot_heads;
CREATE POLICY storage_head_reader ON quant_storage.ledger_hot_heads
  FOR SELECT TO quant_app_runtime,quant_storage_archiver USING(true);

-- Trigger-only SECURITY DEFINER is deliberate: granting the runtime direct head
-- UPDATE/DELETE would let a truncated ledger redefine its own claimed terminal.
-- No API calls, dynamic SQL, secret or caller-selected durable table is used.
-- Private owner-owned schema, fully qualified objects, pg_temp last, PUBLIC and
-- worker EXECUTE revoked; trigger context checked before privileged work.
CREATE OR REPLACE FUNCTION quant_storage.assert_plain_ledger_stage(stage_name text)
RETURNS void LANGUAGE plpgsql SECURITY INVOKER
SET search_path=pg_catalog,quant_storage,pg_temp AS $plain$
DECLARE relation_oid oid; expected text[]; actual text[];
BEGIN
  CASE stage_name
    WHEN 'quant_storage_append_stage' THEN
      expected=ARRAY['aggregate_id:text','cold_hash:text','cold_sequence:bigint',
                     'generation:bigint','reader_fingerprint:text','receipt_sha256:text','root:text'];
    WHEN 'quant_storage_ledger_rows' THEN
      expected=ARRAY['aggregate_id:text','event_hash:text','event_id:uuid',
                     'sequence_no:bigint','source_sha256:text'];
    ELSE RAISE EXCEPTION 'STORAGE_TEMP_STAGE_UNSAFE';
  END CASE;
  relation_oid=to_regclass('pg_temp.'||stage_name);
  -- Never execute caller-supplied view/RLS/custom-domain/generated expressions
  -- inside a privileged trigger. Only physical heap rows of built-in types.
  IF NOT EXISTS(SELECT 1 FROM pg_class WHERE oid=relation_oid AND relkind='r'
                 AND relpersistence='t' AND relnamespace=pg_my_temp_schema()
                 AND NOT relrowsecurity AND NOT relforcerowsecurity AND NOT relhasrules
                 AND relam=(SELECT oid FROM pg_am WHERE amname='heap')) THEN
    RAISE EXCEPTION 'STORAGE_TEMP_STAGE_UNSAFE';
  END IF;
  SELECT array_agg(attname::text||':'||atttypid::regtype::text ORDER BY attname)
    INTO actual FROM pg_attribute WHERE attrelid=relation_oid AND attnum>0 AND NOT attisdropped;
  IF actual IS DISTINCT FROM expected OR EXISTS(SELECT 1 FROM pg_attribute
      WHERE attrelid=relation_oid AND attnum>0 AND NOT attisdropped AND attgenerated<>'') THEN
    RAISE EXCEPTION 'STORAGE_TEMP_STAGE_UNSAFE';
  END IF;
END;
$plain$;
-- Deliberate private locking boundary: runtime has no catalog UPDATE privilege.
-- It neither edits permanent rows nor fetches remote evidence. The private
-- application verifies original signatures before staging the root-bound proof.
CREATE OR REPLACE FUNCTION quant_storage.lock_ledger_append(expected_sequence bigint,expected_hash text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,quant_storage,pg_temp AS $lock_append$
DECLARE proof record; pinned record; terminal record; tracking boolean; approved text;
BEGIN
  SELECT heads_enabled,reader_fingerprint INTO tracking,approved
    FROM quant_storage.ledger_control WHERE singleton;
  IF tracking IS DISTINCT FROM true THEN RAISE EXCEPTION 'STORAGE_HEADS_NOT_COMMISSIONED'; END IF;
  IF to_regclass('pg_temp.quant_storage_append_stage') IS NULL THEN
    RAISE EXCEPTION 'STORAGE_COLD_APPEND_STAGE_MISSING';
  END IF;
  PERFORM quant_storage.assert_plain_ledger_stage('quant_storage_append_stage');
  IF (SELECT count(*) FROM pg_temp.quant_storage_append_stage)<>1 THEN
    RAISE EXCEPTION 'STORAGE_COLD_APPEND_STAGE_INVALID';
  END IF;
  SELECT * INTO proof FROM pg_temp.quant_storage_append_stage;
  SELECT generation,root,receipt_sha256 INTO pinned
    FROM quant_storage.catalog_roots WHERE scope='ledger' FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'STORAGE_HEAD_ROOT_MISSING'; END IF;
  IF proof.generation IS DISTINCT FROM pinned.generation
     OR proof.root IS DISTINCT FROM pinned.root
     OR proof.receipt_sha256 IS DISTINCT FROM pinned.receipt_sha256 THEN
    RAISE EXCEPTION 'STORAGE_APPEND_ROOT_CHANGED';
  END IF;
  IF approved IS NULL OR proof.reader_fingerprint IS DISTINCT FROM approved
     OR proof.aggregate_id IS NULL OR octet_length(proof.aggregate_id) NOT BETWEEN 1 AND 900
     OR proof.cold_sequence IS NULL OR proof.cold_sequence<0
     OR proof.cold_hash IS NULL OR proof.cold_hash !~ '^[0-9a-f]{64}$'
     OR (proof.cold_sequence=0 AND proof.cold_hash<>repeat('0',64))
     OR (pinned.generation=0 AND proof.cold_sequence<>0)
     OR ((expected_sequence IS NULL)<>(expected_hash IS NULL))
     OR (expected_sequence IS NOT NULL AND (expected_sequence<1 OR expected_hash !~ '^[0-9a-f]{64}$')) THEN
    RAISE EXCEPTION 'STORAGE_COLD_APPEND_STAGE_INVALID';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext(proof.aggregate_id));
  SELECT sequence_no,event_hash INTO terminal FROM quant_storage.ledger_hot_heads
    WHERE aggregate_id=proof.aggregate_id;
  IF terminal.sequence_no IS DISTINCT FROM expected_sequence
     OR terminal.event_hash IS DISTINCT FROM expected_hash THEN
    RAISE EXCEPTION 'STORAGE_APPEND_TERMINAL_CHANGED';
  END IF;
END;
$lock_append$;
REVOKE ALL ON FUNCTION quant_storage.lock_ledger_append(bigint,text) FROM PUBLIC,quant_storage_archiver;
GRANT EXECUTE ON FUNCTION quant_storage.lock_ledger_append(bigint,text) TO quant_app_runtime;
DO $lock_acl$
DECLARE role_name text;
BEGIN
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role',
                                  'quant_archive_worker','equity_research_collector'] LOOP
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
      EXECUTE format('REVOKE ALL ON FUNCTION quant_storage.lock_ledger_append(bigint,text) FROM %I',role_name);
    END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a
    LEFT JOIN pg_roles r ON r.oid=a.grantee
    WHERE p.oid='quant_storage.lock_ledger_append(bigint,text)'::regprocedure
      AND a.grantee<>p.proowner AND NOT COALESCE(r.rolsuper OR r.rolbypassrls,false)
      AND NOT(r.rolname='quant_app_runtime' AND a.privilege_type='EXECUTE' AND NOT a.is_grantable)) THEN
    RAISE EXCEPTION 'STORAGE_APPEND_LOCK_GRANT_UNEXPECTED';
  END IF;
END;
$lock_acl$;

CREATE OR REPLACE FUNCTION quant_storage.advance_hot_head()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,quant_storage,pg_temp AS $append$
DECLARE tracking boolean; approved text; root_record record; terminal record;
        prior record; proof record; before_sequence bigint; before_hash text;
BEGIN
  IF TG_TABLE_SCHEMA<>'quant_app' OR TG_TABLE_NAME<>'evidence_ledger_events'
     OR TG_OP<>'INSERT' OR TG_WHEN<>'AFTER' OR TG_LEVEL<>'ROW' THEN
    RAISE EXCEPTION 'STORAGE_HEAD_TRIGGER_CONTEXT_INVALID';
  END IF;
  SELECT heads_enabled,reader_fingerprint INTO tracking,approved
    FROM quant_storage.ledger_control WHERE singleton;
  IF tracking IS DISTINCT FROM true THEN RETURN NEW; END IF;
  -- Same order as archiving: protected root then aggregate lock, never HTTP here.
  SELECT generation,root,receipt_sha256 INTO root_record
    FROM quant_storage.catalog_roots WHERE scope='ledger' FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'STORAGE_HEAD_ROOT_MISSING'; END IF;
  PERFORM pg_advisory_xact_lock(hashtext(NEW.aggregate_id));
  SELECT sequence_no,event_hash INTO terminal FROM quant_storage.ledger_hot_heads
    WHERE aggregate_id=NEW.aggregate_id FOR UPDATE;
  IF root_record.generation>0 THEN
    IF to_regclass('pg_temp.quant_storage_append_stage') IS NULL THEN
      RAISE EXCEPTION 'STORAGE_COLD_APPEND_STAGE_MISSING';
    END IF;
    PERFORM quant_storage.assert_plain_ledger_stage('quant_storage_append_stage');
    IF (SELECT count(*) FROM pg_temp.quant_storage_append_stage)<>1 THEN
      RAISE EXCEPTION 'STORAGE_COLD_APPEND_STAGE_INVALID';
    END IF;
    SELECT * INTO proof FROM pg_temp.quant_storage_append_stage;
    IF proof.generation IS DISTINCT FROM root_record.generation
       OR proof.root IS DISTINCT FROM root_record.root
       OR proof.receipt_sha256 IS DISTINCT FROM root_record.receipt_sha256
       OR proof.aggregate_id IS DISTINCT FROM NEW.aggregate_id
       OR approved IS NULL OR proof.reader_fingerprint IS DISTINCT FROM approved
       OR proof.cold_sequence IS NULL OR proof.cold_sequence<0
       OR proof.cold_hash IS NULL OR proof.cold_hash !~ '^[0-9a-f]{64}$'
       OR (proof.cold_sequence=0 AND proof.cold_hash<>repeat('0',64)) THEN
      RAISE EXCEPTION 'STORAGE_COLD_APPEND_STAGE_INVALID';
    END IF;
  END IF;
  SELECT sequence_no,event_hash INTO prior FROM quant_app.evidence_ledger_events
    WHERE aggregate_id=NEW.aggregate_id AND event_id<>NEW.event_id
    ORDER BY sequence_no DESC LIMIT 1;
  IF terminal.sequence_no IS NOT NULL THEN
    IF prior.sequence_no IS DISTINCT FROM terminal.sequence_no
       OR prior.event_hash IS DISTINCT FROM terminal.event_hash THEN
      RAISE EXCEPTION 'STORAGE_HOT_TAIL_MISSING_OR_CHANGED';
    END IF;
    before_sequence=terminal.sequence_no; before_hash=terminal.event_hash;
  ELSE
    IF prior.sequence_no IS NOT NULL THEN RAISE EXCEPTION 'STORAGE_HOT_HEAD_MISSING'; END IF;
    IF root_record.generation=0 THEN
      before_sequence=0; before_hash=repeat('0',64);
    ELSE
      -- Proof was verified by the private cold reader BEFORE the locked append.
      -- SQL binds its snapshot to the protected root, not an event's own claim.
      before_sequence=proof.cold_sequence; before_hash=proof.cold_hash;
    END IF;
  END IF;
  IF before_sequence=9223372036854775807 OR NEW.sequence_no<>before_sequence+1
     OR NEW.previous_hash<>before_hash OR NEW.event_hash !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'STORAGE_HOT_APPEND_PREDECESSOR_MISMATCH';
  END IF;
  INSERT INTO quant_storage.ledger_hot_heads(aggregate_id,sequence_no,event_hash)
    VALUES(NEW.aggregate_id,NEW.sequence_no,NEW.event_hash)
    ON CONFLICT(aggregate_id) DO UPDATE SET
      sequence_no=EXCLUDED.sequence_no,event_hash=EXCLUDED.event_hash;
  RETURN NEW;
END;
$append$;

CREATE OR REPLACE FUNCTION quant_storage.retire_cold_heads()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,quant_storage,pg_temp AS $retire$
DECLARE aggregate text; terminal record; last_staged record; hot record;
BEGIN
  IF TG_TABLE_SCHEMA<>'quant_storage' OR TG_TABLE_NAME<>'catalog_roots'
     OR TG_OP<>'UPDATE' OR TG_LEVEL<>'ROW' THEN
    RAISE EXCEPTION 'STORAGE_HEAD_TRIGGER_CONTEXT_INVALID';
  END IF;
  IF NEW.scope<>'ledger' THEN RETURN NULL; END IF;
  -- Invoker archive guards already validated role, exact rows and root staging.
  -- Repeat the critical bounded stage/commission requirements, under this owner.
  IF NOT EXISTS(SELECT 1 FROM quant_storage.ledger_control
                WHERE singleton AND pruning_enabled AND heads_enabled)
     OR to_regclass('pg_temp.quant_storage_ledger_rows') IS NULL THEN
    RAISE EXCEPTION 'STORAGE_HEAD_RETIRE_UNCOMMISSIONED';
  END IF;
  PERFORM quant_storage.assert_plain_ledger_stage('quant_storage_ledger_rows');
  FOR aggregate IN SELECT DISTINCT aggregate_id FROM pg_temp.quant_storage_ledger_rows
                     ORDER BY aggregate_id LOOP
    SELECT sequence_no,event_hash INTO terminal FROM quant_storage.ledger_hot_heads
      WHERE aggregate_id=aggregate FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'STORAGE_HOT_HEAD_MISSING'; END IF;
    SELECT sequence_no,event_hash INTO hot FROM quant_app.evidence_ledger_events
      WHERE aggregate_id=aggregate ORDER BY sequence_no DESC LIMIT 1;
    IF hot.sequence_no IS NOT NULL THEN
      IF hot.sequence_no IS DISTINCT FROM terminal.sequence_no
         OR hot.event_hash IS DISTINCT FROM terminal.event_hash THEN
        RAISE EXCEPTION 'STORAGE_HOT_TAIL_MISSING_OR_CHANGED';
      END IF;
    ELSE
      SELECT sequence_no,event_hash INTO last_staged FROM pg_temp.quant_storage_ledger_rows
        WHERE aggregate_id=aggregate ORDER BY sequence_no DESC LIMIT 1;
      IF last_staged.sequence_no IS DISTINCT FROM terminal.sequence_no
         OR last_staged.event_hash IS DISTINCT FROM terminal.event_hash THEN
        RAISE EXCEPTION 'STORAGE_COLD_HEAD_RETIRE_MISMATCH';
      END IF;
      DELETE FROM quant_storage.ledger_hot_heads WHERE aggregate_id=aggregate;
    END IF;
  END LOOP;
  RETURN NULL;
END;
$retire$;

CREATE OR REPLACE FUNCTION quant_storage.guard_head_commission()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER
SET search_path=pg_catalog,quant_storage AS $commission$
BEGIN
  IF NEW.heads_enabled AND NOT OLD.heads_enabled THEN
    IF EXISTS(
      WITH actual AS (SELECT DISTINCT ON(aggregate_id) aggregate_id,sequence_no,event_hash
        FROM quant_app.evidence_ledger_events ORDER BY aggregate_id,sequence_no DESC)
      SELECT 1 FROM actual a FULL JOIN quant_storage.ledger_hot_heads h USING(aggregate_id)
        WHERE a.sequence_no IS DISTINCT FROM h.sequence_no
           OR a.event_hash IS DISTINCT FROM h.event_hash) THEN
      RAISE EXCEPTION 'STORAGE_HEAD_BOOTSTRAP_MISMATCH';
    END IF;
  END IF;
  IF OLD.heads_enabled AND NEW.head_audit_sha256 IS DISTINCT FROM OLD.head_audit_sha256 THEN
    RAISE EXCEPTION 'STORAGE_HEAD_AUDIT_IMMUTABLE';
  END IF;
  IF NOT NEW.heads_enabled AND EXISTS(SELECT 1 FROM quant_storage.catalog_roots
                                    WHERE scope='ledger' AND generation>0) THEN
    RAISE EXCEPTION 'STORAGE_COLD_HEAD_TRACKING_REQUIRED';
  END IF;
  RETURN NEW;
END;
$commission$;
REVOKE ALL ON FUNCTION quant_storage.advance_hot_head(),quant_storage.retire_cold_heads(),
  quant_storage.guard_head_commission(),quant_storage.assert_plain_ledger_stage(text)
  FROM PUBLIC,quant_app_runtime,quant_storage_archiver;
DO $function_permissions$
DECLARE role_name text;
BEGIN
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role',
                                  'quant_archive_worker','equity_research_collector'] LOOP
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
      EXECUTE format('REVOKE ALL ON FUNCTION quant_storage.advance_hot_head(),
         quant_storage.retire_cold_heads(),quant_storage.guard_head_commission() FROM %I',role_name);
      EXECUTE format('REVOKE ALL ON FUNCTION quant_storage.assert_plain_ledger_stage(text) FROM %I',role_name);
    END IF;
  END LOOP;
END;
$function_permissions$;
DO $acl_check$
BEGIN
  IF EXISTS(SELECT 1 FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a
      LEFT JOIN pg_roles r ON r.oid=a.grantee
      WHERE c.oid='quant_storage.ledger_hot_heads'::regclass AND a.grantee<>c.relowner
        AND NOT COALESCE(r.rolsuper OR r.rolbypassrls,false)
        AND NOT (r.rolname IN ('quant_app_runtime','quant_storage_archiver')
                 AND a.privilege_type='SELECT' AND NOT a.is_grantable))
     OR EXISTS(SELECT 1 FROM pg_attribute c CROSS JOIN LATERAL aclexplode(c.attacl) a
      LEFT JOIN pg_roles r ON r.oid=a.grantee
      WHERE c.attrelid='quant_storage.ledger_hot_heads'::regclass
        AND a.grantee<>current_user::regrole
        AND NOT COALESCE(r.rolsuper OR r.rolbypassrls,false))
     OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      CROSS JOIN LATERAL aclexplode(p.proacl) a LEFT JOIN pg_roles r ON r.oid=a.grantee
      WHERE n.nspname='quant_storage' AND p.proname IN ('advance_hot_head',
        'retire_cold_heads','guard_head_commission','assert_plain_ledger_stage')
        AND a.grantee<>p.proowner AND NOT COALESCE(r.rolsuper OR r.rolbypassrls,false)) THEN
    RAISE EXCEPTION 'STORAGE_HEAD_GRANT_UNEXPECTED';
  END IF;
END;
$acl_check$;
DROP TRIGGER IF EXISTS storage_hot_head_advance ON quant_app.evidence_ledger_events;
CREATE TRIGGER storage_hot_head_advance AFTER INSERT ON quant_app.evidence_ledger_events
  FOR EACH ROW EXECUTE FUNCTION quant_storage.advance_hot_head();
DROP TRIGGER IF EXISTS storage_cold_head_retire ON quant_storage.catalog_roots;
CREATE CONSTRAINT TRIGGER storage_cold_head_retire AFTER UPDATE ON quant_storage.catalog_roots
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION quant_storage.retire_cold_heads();
DROP TRIGGER IF EXISTS storage_head_commission ON quant_storage.ledger_control;
CREATE TRIGGER storage_head_commission BEFORE UPDATE ON quant_storage.ledger_control
  FOR EACH ROW EXECUTE FUNCTION quant_storage.guard_head_commission();
COMMIT;
