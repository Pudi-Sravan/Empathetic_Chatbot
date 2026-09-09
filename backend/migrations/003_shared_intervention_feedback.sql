BEGIN;

-- Shared entries contain only the explicitly reported scenario and outcome.
-- A hash prevents the same report from creating duplicate recommendations.
ALTER TABLE global_interventions
    ADD COLUMN IF NOT EXISTS source_text_hash TEXT;
UPDATE global_interventions
SET source_text_hash = md5(scenario_description || solution_action)
WHERE source_text_hash IS NULL;
DELETE FROM global_interventions older
USING global_interventions newer
WHERE older.source_text_hash = newer.source_text_hash
  AND older.id < newer.id;
ALTER TABLE global_interventions
    ALTER COLUMN source_text_hash SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS global_interventions_source_hash_idx
    ON global_interventions (source_text_hash);

COMMIT;
