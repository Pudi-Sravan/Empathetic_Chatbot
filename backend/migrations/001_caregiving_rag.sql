BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 200),
    age SMALLINT CHECK (age BETWEEN 0 AND 130),
    weight NUMERIC(5,2) CHECK (weight IS NULL OR weight > 0),
    gender TEXT CHECK (gender IS NULL OR gender IN ('female', 'male', 'nonbinary', 'other', 'prefer_not_to_say')),
    interests_hobbies JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(interests_hobbies) = 'array'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE patient_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    medical_conditions TEXT NOT NULL DEFAULT '',
    caregiver_notes TEXT NOT NULL DEFAULT '',
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE behavioral_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    observation TEXT NOT NULL CHECK (length(btrim(observation)) > 0),
    successful_intervention TEXT,
    source_text_hash TEXT NOT NULL,
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX behavioral_logs_user_source_hash_idx
    ON behavioral_logs (user_id, source_text_hash);

CREATE TABLE global_interventions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_description TEXT NOT NULL CHECK (length(btrim(scenario_description)) > 0),
    solution_action TEXT NOT NULL CHECK (length(btrim(solution_action)) > 0),
    scenario_embedding VECTOR(1536) NOT NULL,
    upvotes INTEGER NOT NULL DEFAULT 0 CHECK (upvotes >= 0),
    downvotes INTEGER NOT NULL DEFAULT 0 CHECK (downvotes >= 0),
    source_text_hash TEXT NOT NULL UNIQUE
);

CREATE INDEX users_interests_hobbies_gin ON users USING gin (interests_hobbies);
CREATE INDEX behavioral_logs_user_created_idx ON behavioral_logs (user_id, created_at DESC);
-- HNSW has stable low-latency cosine search. Tune ef_search at session level if recall needs rise.
CREATE INDEX patient_profiles_embedding_hnsw ON patient_profiles USING hnsw (embedding vector_cosine_ops);
CREATE INDEX behavioral_logs_embedding_hnsw ON behavioral_logs USING hnsw (embedding vector_cosine_ops);
CREATE INDEX global_interventions_embedding_hnsw ON global_interventions USING hnsw (scenario_embedding vector_cosine_ops);

CREATE OR REPLACE FUNCTION set_users_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;
CREATE TRIGGER users_set_updated_at BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_users_updated_at();

COMMIT;
