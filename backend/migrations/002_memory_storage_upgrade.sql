BEGIN;

-- Safe upgrade for databases created before short/long-term memory was split.
ALTER TABLE behavioral_logs
    ADD COLUMN IF NOT EXISTS source_text_hash TEXT;
UPDATE behavioral_logs
SET source_text_hash = md5(observation)
WHERE source_text_hash IS NULL;
DELETE FROM behavioral_logs older
USING behavioral_logs newer
WHERE older.user_id = newer.user_id
  AND older.source_text_hash = newer.source_text_hash
  AND older.created_at < newer.created_at;
ALTER TABLE behavioral_logs
    ALTER COLUMN source_text_hash SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS behavioral_logs_user_source_hash_idx
    ON behavioral_logs (user_id, source_text_hash);

COMMIT;
