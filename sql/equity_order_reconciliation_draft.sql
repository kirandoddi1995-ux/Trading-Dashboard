-- DRAFT ONLY. Review before running. Requires the existing equity_operations
-- migration and roles. No research/schema/readiness/model tables are modified.
-- Private operational records are NOT validated execution evidence.
BEGIN;

CREATE TABLE equity_operations.order_intents (
    intent_id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    review_id uuid NOT NULL UNIQUE REFERENCES equity_operations.manual_quote_reviews(review_id),
    created_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    CHECK ((payload->>'purpose'='USER_REPORTED_ORDER_INTENT') IS TRUE),
    CHECK ((payload->'production_evidence_eligible'='false'::jsonb) IS TRUE),
    CHECK ((payload->>'intent_id'=intent_id::text) IS TRUE),
    CHECK ((payload->>'owner_id'=owner_id) IS TRUE),
    CHECK ((payload->>'review_id'=review_id::text) IS TRUE),
    CHECK (((payload->>'quantity')::numeric > 0) IS TRUE),
    CHECK (((payload->>'quantity')::numeric=trunc((payload->>'quantity')::numeric)) IS TRUE),
    CHECK (((payload->>'limit_price')::numeric > 0) IS TRUE),
    UNIQUE(intent_id,owner_id)
);
CREATE INDEX equity_order_intent_owner_idx ON equity_operations.order_intents(owner_id,created_at);

CREATE TABLE equity_operations.order_results (
    result_id uuid PRIMARY KEY,
    intent_id uuid NOT NULL UNIQUE,
    owner_id text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    payload jsonb NOT NULL,
    FOREIGN KEY(intent_id,owner_id) REFERENCES equity_operations.order_intents(intent_id,owner_id),
    CHECK ((payload->>'purpose'='USER_REPORTED_BROKER_RESULT') IS TRUE),
    CHECK ((payload->'production_evidence_eligible'='false'::jsonb) IS TRUE),
    CHECK ((payload->>'intent_id'=intent_id::text) IS TRUE),
    CHECK ((payload->>'owner_id'=owner_id) IS TRUE),
    CHECK ((payload->>'result_id'=result_id::text) IS TRUE),
    CHECK ((payload->'confirmed'='true'::jsonb) IS TRUE),
    CHECK ((payload->>'status' IN ('FILLED','PARTIAL_FINAL','CANCELLED','REJECTED','NOT_PLACED')) IS TRUE),
    CHECK (((payload->>'filled_quantity')::numeric >= 0) IS TRUE),
    CHECK (((payload->>'filled_quantity')::numeric=trunc((payload->>'filled_quantity')::numeric)) IS TRUE),
    CHECK (((payload->>'filled_quantity')::numeric=0 AND payload->'average_fill_price'='null'::jsonb
            OR (payload->>'filled_quantity')::numeric>0 AND (payload->>'average_fill_price')::numeric>0) IS TRUE)
);

CREATE FUNCTION equity_operations.guard_order_intent() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,equity_operations AS $$
DECLARE review jsonb;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.owner_id,0));
    IF EXISTS (SELECT 1 FROM equity_operations.order_intents i
               WHERE i.owner_id=NEW.owner_id AND NOT EXISTS
                 (SELECT 1 FROM equity_operations.order_results r WHERE r.intent_id=i.intent_id)) THEN
        RAISE EXCEPTION 'Previous order is unresolved';
    END IF;
    SELECT payload INTO STRICT review FROM equity_operations.manual_quote_reviews
      WHERE review_id=NEW.review_id;
    IF (review->>'reviewer'=NEW.owner_id AND review->>'status'='CONFIRMED'
        AND review->'system_allow_trade'='true'::jsonb
        AND review->>'decision_id'=NEW.payload->>'decision_id'
        AND review->>'decision_digest'=NEW.payload->>'decision_digest'
        AND review->'execution_plan'->>'order_type'='LIMIT'
        AND (review->'execution_plan'->>'quantity')::numeric=(NEW.payload->>'quantity')::numeric
        AND (review->'execution_plan'->>'limit_price')::numeric=(NEW.payload->>'limit_price')::numeric) IS NOT TRUE THEN
        RAISE EXCEPTION 'Order intent does not match its confirmed review';
    END IF;
    IF NEW.created_at > clock_timestamp()
       OR clock_timestamp()-NEW.created_at > interval '5 seconds'
       OR (review->>'attested_at')::timestamptz > clock_timestamp()
       OR clock_timestamp()-(review->>'attested_at')::timestamptz > interval '5 seconds' THEN
        RAISE EXCEPTION 'Order review is no longer current';
    END IF;
    IF ((review->>'primary_quote_observed_at')::timestamptz <= clock_timestamp()
        AND clock_timestamp()-(review->>'primary_quote_observed_at')::timestamptz <= interval '5 seconds'
        AND (review->>'governance_decision_at')::timestamptz <= clock_timestamp()
        AND clock_timestamp()-(review->>'governance_decision_at')::timestamptz <= interval '5 seconds') IS NOT TRUE THEN
        RAISE EXCEPTION 'Original quote/governance approval is no longer current';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER check_equity_order_intent BEFORE INSERT ON equity_operations.order_intents
FOR EACH ROW EXECUTE FUNCTION equity_operations.guard_order_intent();

CREATE FUNCTION equity_operations.guard_order_result() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,equity_operations AS $$
DECLARE intended jsonb; qty numeric; requested numeric; result_status text;
BEGIN
    SELECT payload INTO STRICT intended FROM equity_operations.order_intents
      WHERE intent_id=NEW.intent_id AND owner_id=NEW.owner_id;
    qty := (NEW.payload->>'filled_quantity')::numeric;
    requested := (intended->>'quantity')::numeric;
    result_status := NEW.payload->>'status';
    IF (qty BETWEEN 0 AND requested) IS NOT TRUE
       OR (result_status='FILLED' AND qty<>requested)
       OR (result_status='PARTIAL_FINAL' AND NOT (qty>0 AND qty<requested))
       OR (result_status IN ('CANCELLED','REJECTED','NOT_PLACED') AND qty<>0) THEN
        RAISE EXCEPTION 'Actual fill quantity conflicts with final status or intended quantity';
    END IF;
    IF result_status<>'NOT_PLACED' AND
       (length(NEW.payload->>'broker_order_id')>0
        AND (NEW.payload->>'broker_event_at')::timestamptz >= (intended->>'created_at')::timestamptz
        AND (NEW.payload->>'broker_event_at')::timestamptz <= clock_timestamp()) IS NOT TRUE THEN
        RAISE EXCEPTION 'Actual broker identity and timestamp are required';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER check_equity_order_result BEFORE INSERT ON equity_operations.order_results
FOR EACH ROW EXECUTE FUNCTION equity_operations.guard_order_result();

CREATE FUNCTION equity_operations.reject_order_mutation() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
    RAISE EXCEPTION 'Equity order records are immutable';
END $$;
CREATE TRIGGER immutable_equity_order_intent BEFORE UPDATE OR DELETE ON equity_operations.order_intents
FOR EACH ROW EXECUTE FUNCTION equity_operations.reject_order_mutation();
CREATE TRIGGER immutable_equity_order_result BEFORE UPDATE OR DELETE ON equity_operations.order_results
FOR EACH ROW EXECUTE FUNCTION equity_operations.reject_order_mutation();

REVOKE ALL ON FUNCTION equity_operations.guard_order_intent(), equity_operations.guard_order_result(), equity_operations.reject_order_mutation()
FROM PUBLIC,anon,authenticated,service_role,equity_research_collector;
REVOKE ALL ON equity_operations.order_intents,equity_operations.order_results
FROM PUBLIC,anon,authenticated,service_role,equity_research_collector;
GRANT SELECT,INSERT ON equity_operations.order_intents,equity_operations.order_results TO quant_app_runtime;

ALTER TABLE equity_operations.order_intents ENABLE ROW LEVEL SECURITY;
ALTER TABLE equity_operations.order_intents FORCE ROW LEVEL SECURITY;
ALTER TABLE equity_operations.order_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE equity_operations.order_results FORCE ROW LEVEL SECURITY;
CREATE POLICY runtime_order_intents_select ON equity_operations.order_intents
FOR SELECT TO quant_app_runtime USING (true);
CREATE POLICY runtime_order_intents_insert ON equity_operations.order_intents
FOR INSERT TO quant_app_runtime WITH CHECK ((payload->'production_evidence_eligible'='false'::jsonb) IS TRUE);
CREATE POLICY runtime_order_results_select ON equity_operations.order_results
FOR SELECT TO quant_app_runtime USING (true);
CREATE POLICY runtime_order_results_insert ON equity_operations.order_results
FOR INSERT TO quant_app_runtime WITH CHECK ((payload->'production_evidence_eligible'='false'::jsonb) IS TRUE);

DO $$
BEGIN
    IF has_schema_privilege('equity_research_collector','equity_operations','USAGE')
       OR has_table_privilege('equity_research_collector','equity_operations.order_intents','SELECT,INSERT,UPDATE,DELETE')
       OR has_table_privilege('equity_research_collector','equity_operations.order_results','SELECT,INSERT,UPDATE,DELETE') THEN
        RAISE EXCEPTION 'Research role unexpectedly has operational permissions';
    END IF;
END $$;
COMMIT;
