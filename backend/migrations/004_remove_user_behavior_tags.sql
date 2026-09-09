BEGIN;

-- User-supplied behavior tags are no longer collected or used for retrieval.
DROP INDEX IF EXISTS global_interventions_tags_gin;
ALTER TABLE global_interventions DROP COLUMN IF EXISTS matching_tags;

COMMIT;
