-- REVIEW ONLY. No hosted execution, live factory or migration activation.
-- New namespace: NOT a backfill or replacement of equity_operations.
BEGIN;
CREATE SCHEMA quant_operational_receipts;
REVOKE ALL ON SCHEMA quant_operational_receipts FROM PUBLIC;
CREATE TABLE quant_operational_receipts.control (
  singleton boolean PRIMARY KEY CHECK(singleton), enabled boolean NOT NULL DEFAULT false);
INSERT INTO quant_operational_receipts.control VALUES(true,false);
CREATE TABLE quant_operational_receipts.leases (
  run_id text PRIMARY KEY CHECK(octet_length(run_id) BETWEEN 1 AND 900),
  owner_id text NOT NULL CHECK(octet_length(owner_id) BETWEEN 1 AND 900),
  fence bigint NOT NULL CHECK(fence > 0), expires_at timestamptz NOT NULL);
CREATE TABLE quant_operational_receipts.receipts (
  kind text NOT NULL CHECK(kind IN ('checkpoint','run')), run_id text NOT NULL,
  instrument text NOT NULL, fence bigint NOT NULL CHECK(fence > 0),
  request_text text NOT NULL CHECK(octet_length(request_text) <= 2097152),
  receipt_text text NOT NULL CHECK(octet_length(receipt_text) <= 2100000),
  committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(kind,run_id,instrument,fence),
  FOREIGN KEY(run_id) REFERENCES quant_operational_receipts.leases(run_id));
CREATE TABLE quant_operational_receipts.current_operations (
  kind text NOT NULL, run_id text NOT NULL, instrument text NOT NULL, fence bigint NOT NULL,
  request_text text NOT NULL,
  PRIMARY KEY(kind,run_id,instrument),
  FOREIGN KEY(kind,run_id,instrument,fence)
    REFERENCES quant_operational_receipts.receipts(kind,run_id,instrument,fence));
CREATE FUNCTION quant_operational_receipts.immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'OPERATIONAL_RECEIPT_IMMUTABLE'; END $$;
CREATE TRIGGER immutable_receipts BEFORE UPDATE OR DELETE
ON quant_operational_receipts.receipts FOR EACH ROW
EXECUTE FUNCTION quant_operational_receipts.immutable();

-- Privileged functions are necessary for atomic mutation while callers have no
-- table write grant. Fixed schema, no dynamic SQL, explicit PUBLIC revocation.
CREATE FUNCTION quant_operational_receipts.claim(p_run text,p_owner text,
  p_expected bigint,p_seconds integer) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v quant_operational_receipts.leases; v_now timestamptz;
BEGIN
  IF (SELECT enabled FROM quant_operational_receipts.control WHERE singleton) IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'OPERATIONAL_WRITER_NOT_COMMISSIONED';
  END IF;
  IF p_run IS NULL OR octet_length(p_run) NOT BETWEEN 1 AND 900 OR
     p_owner IS NULL OR octet_length(p_owner) NOT BETWEEN 1 AND 900 OR
     p_expected IS NULL OR p_expected < 0 OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 300 THEN
    RAISE EXCEPTION 'OPERATIONAL_CLAIM_INVALID';
  END IF;
  IF p_expected=0 THEN
    INSERT INTO quant_operational_receipts.leases VALUES
      (p_run,p_owner,1,clock_timestamp()+make_interval(secs=>p_seconds))
      ON CONFLICT DO NOTHING;
    IF NOT FOUND THEN RAISE EXCEPTION 'OPERATIONAL_CLAIM_CONFLICT'; END IF;
    RETURN 1;
  END IF;
  SELECT * INTO v FROM quant_operational_receipts.leases WHERE run_id=p_run FOR UPDATE;
  v_now:=clock_timestamp(); -- AFTER lock acquisition; transaction start is not expiry time.
  IF NOT FOUND OR v.fence<>p_expected OR v.expires_at>v_now OR v.fence=9223372036854775807 THEN
    RAISE EXCEPTION 'OPERATIONAL_TAKEOVER_BLOCKED';
  END IF;
  UPDATE quant_operational_receipts.leases SET owner_id=p_owner,fence=v.fence+1,
    expires_at=v_now+make_interval(secs=>p_seconds) WHERE run_id=p_run;
  RETURN v.fence+1;
END $$;

CREATE FUNCTION quant_operational_receipts.apply(p_owner text,p_kind text,p_run text,
  p_instrument text,p_fence bigint,p_request text,p_receipt text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v quant_operational_receipts.leases; prior text; request jsonb; receipt jsonb;
BEGIN
  IF (SELECT enabled FROM quant_operational_receipts.control WHERE singleton) IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'OPERATIONAL_WRITER_NOT_COMMISSIONED';
  END IF;
  IF p_owner IS NULL OR p_kind IS NULL OR p_kind NOT IN ('checkpoint','run') OR
    p_run IS NULL OR p_instrument IS NULL OR p_fence IS NULL OR p_fence<=0 OR
    p_request IS NULL OR octet_length(p_request)>2097152 OR
    p_receipt IS NULL OR octet_length(p_receipt)>2100000 THEN
    RAISE EXCEPTION 'OPERATIONAL_REQUEST_INVALID';
  END IF;
  request:=p_request::jsonb; receipt:=p_receipt::jsonb;
  IF receipt->>'format' IS DISTINCT FROM 'operational-receipt-history-v1' OR
    receipt->>'kind' IS DISTINCT FROM p_kind OR receipt->'request' IS DISTINCT FROM request OR
    receipt->>'signature' IS NULL OR receipt->>'signature' !~ '^[0-9a-f]{64}$' OR
    receipt->>'key_id' IS NULL OR octet_length(receipt->>'key_id') NOT BETWEEN 1 AND 900 OR
    request->>'run_id' IS DISTINCT FROM p_run OR
    request->>'fencing_token' IS DISTINCT FROM p_fence::text OR
    (p_kind='checkpoint' AND request->>'instrument' IS DISTINCT FROM p_instrument) OR
    (p_kind='run' AND p_instrument<>'') THEN
    RAISE EXCEPTION 'OPERATIONAL_RECEIPT_BINDING_INVALID';
  END IF;
  SELECT * INTO v FROM quant_operational_receipts.leases WHERE run_id=p_run FOR UPDATE;
  IF NOT FOUND OR v.owner_id<>p_owner OR v.fence<>p_fence OR v.expires_at<=clock_timestamp() THEN
    RAISE EXCEPTION 'OPERATIONAL_STALE_OR_EXPIRED_OWNER';
  END IF;
  SELECT receipt_text INTO prior FROM quant_operational_receipts.receipts
    WHERE kind=p_kind AND run_id=p_run AND instrument=p_instrument AND fence=p_fence;
  IF FOUND THEN
    IF prior<>p_receipt THEN RAISE EXCEPTION 'OPERATIONAL_RECEIPT_CONFLICT'; END IF;
    RETURN 'IDEMPOTENT';
  END IF;
  INSERT INTO quant_operational_receipts.receipts(kind,run_id,instrument,fence,request_text,receipt_text)
    VALUES(p_kind,p_run,p_instrument,p_fence,p_request,p_receipt);
  INSERT INTO quant_operational_receipts.current_operations VALUES(p_kind,p_run,p_instrument,p_fence,p_request)
    ON CONFLICT(kind,run_id,instrument) DO UPDATE SET fence=EXCLUDED.fence,request_text=EXCLUDED.request_text;
  RETURN 'NEW';
END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA quant_operational_receipts FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA quant_operational_receipts FROM PUBLIC;
ALTER TABLE quant_operational_receipts.control ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_operational_receipts.leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_operational_receipts.receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_operational_receipts.current_operations ENABLE ROW LEVEL SECURITY;
-- Owner-only control; restricted caller reads original receipts but cannot edit them.
CREATE POLICY runtime_read_receipts ON quant_operational_receipts.receipts
  FOR SELECT TO quant_app_runtime USING(true);
CREATE POLICY runtime_read_operations ON quant_operational_receipts.current_operations
  FOR SELECT TO quant_app_runtime USING(true);
GRANT USAGE ON SCHEMA quant_operational_receipts TO quant_app_runtime;
GRANT SELECT ON quant_operational_receipts.receipts,quant_operational_receipts.current_operations TO quant_app_runtime;
GRANT EXECUTE ON FUNCTION quant_operational_receipts.claim(text,text,bigint,integer),
  quant_operational_receipts.apply(text,text,text,text,bigint,text,text) TO quant_app_runtime;
COMMIT;
