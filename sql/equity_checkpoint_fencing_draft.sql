-- REVIEW DRAFT ONLY: Kiran runs manually BEFORE deploying the new Python files.
-- Never executed by application startup. No backfill, default, or grants.
BEGIN;
ALTER TABLE equity_operations.scan_candidates
    ADD COLUMN IF NOT EXISTS checkpoint_fencing_token bigint;
COMMIT;

-- OPTIONAL ROLLBACK ONLY BEFORE ANY NEW CHECKPOINT TOKEN HAS BEEN WRITTEN.
-- Stop the new sender / revert application deployment first.
-- Do NOT execute rollback after new receipts exist: it destroys their fence identity.
-- BEGIN;
-- ALTER TABLE equity_operations.scan_candidates
--     DROP COLUMN IF EXISTS checkpoint_fencing_token;
-- COMMIT;
