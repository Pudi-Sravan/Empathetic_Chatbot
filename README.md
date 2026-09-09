# Caretaker Support Companion

The application has one private-memory path and one opt-in peer-idea path:

- **Short-term conversation context** is a per-user Redis list, capped at eight messages and set to expire after 24 hours.
- **Long-term, explicitly stated care facts** are written to PostgreSQL by the background worker. They include profile facts and durable observations only; raw chat transcripts are never stored in PostgreSQL.
- **Peer-reported ideas** are written only when the user ticks **Share this reported success anonymously with other users**, the message explicitly reports a success, and an embedding is available. An unchecked box never contributes an idea for other users.

Behavior tags are not collected from users and are not used in retrieval. Peer ideas are matched only by semantic similarity of the reported situation: an idea needs a **70%** match by default, or a **50%** match after it has at least **two net helpful ratings**. The SQL retrieval query enforces this before any idea can be returned, so a match below 50% can never be suggested.

The sharing checkbox is a per-message consent choice and resets after every send. When it is unchecked, an explicitly stated durable observation can still be stored in that person's **private** memory, but it cannot create or update a peer idea. When it is checked, a peer idea is still created only if the message explicitly says an approach was helpful and a vector can be generated.

`app.py` is the Gradio interface. `backend/` contains the FastAPI API, PostgreSQL migrations, and worker. The old file-based Python implementation was removed. Any retained legacy Markdown profile is not read by the app.

## Run locally

1. Create and activate a Python virtual environment, then install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Start PostgreSQL (with pgvector) and Redis:

   ```bash
   docker compose up -d
   ```

   Skip this step when `.env` already points to an existing PostgreSQL and
   Redis installation. Do not start the Compose stack on the same ports: it
   will conflict with those services.

3. Copy the environment template and set your Groq and Eden AI keys. Embeddings
   are optional; leave `EMBEDDING_URL` and `EMBEDDING_API_KEY` empty if you only
   need Redis/PostgreSQL memory. Eden AI v3 model names use `provider/model`, such
   as `openai/text-embedding-3-small`.

   ```bash
   cp .env.example .env
   ```

4. Create the schema (run once for a new database):

   ```bash
   psql "postgresql://caregiving_app:caregiving_local_password@127.0.0.1:5432/caregiving" -v ON_ERROR_STOP=1 -f backend/migrations/001_caregiving_rag.sql
   ```

   If you already created the database with an earlier version, also run:

   ```bash
   psql "postgresql://caregiving_app:caregiving_local_password@127.0.0.1:5432/caregiving" -v ON_ERROR_STOP=1 -f backend/migrations/002_memory_storage_upgrade.sql
   psql "postgresql://caregiving_app:caregiving_local_password@127.0.0.1:5432/caregiving" -v ON_ERROR_STOP=1 -f backend/migrations/003_shared_intervention_feedback.sql
   psql "postgresql://caregiving_app:caregiving_local_password@127.0.0.1:5432/caregiving" -v ON_ERROR_STOP=1 -f backend/migrations/004_remove_user_behavior_tags.sql
   ```

5. Use three terminals (with the virtual environment activated in each):

   ```bash
   uvicorn backend.main:app --reload
   python -m backend.worker
   python app.py
   ```

Open `http://127.0.0.1:7860`.

## Start with an empty local database

This deletes the app's local Docker PostgreSQL and Redis volumes, then creates an empty schema. Stop the API and worker first so they do not hold connections.

```bash
docker compose down -v
docker compose up -d
docker compose exec -T postgres psql -U caregiving_app -d caregiving -v ON_ERROR_STOP=1 -f /workspace/backend/migrations/001_caregiving_rag.sql
```

If your Compose project does not mount the repository at `/workspace`, run the final `psql` command from the host instead:

```bash
psql "postgresql://caregiving_app:caregiving_local_password@127.0.0.1:5432/caregiving" -v ON_ERROR_STOP=1 -f backend/migrations/001_caregiving_rag.sql
```

If `.env` points at an already-migrated PostgreSQL database instead of the
Docker Compose database, this clears only this application's records while
keeping the schema and extensions:

```bash
set -a; source .env; set +a
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c 'TRUNCATE TABLE users, global_interventions RESTART IDENTITY CASCADE;'
redis-cli --scan --pattern 'caregiving:*' | xargs -r redis-cli DEL
```

Run `backend/migrations/004_remove_user_behavior_tags.sql` once for an older
database before using the app; new databases already start without that field.

## Verify memory storage

After sending a message, Redis contains the transient turns and the worker queue:

```bash
docker compose exec redis redis-cli KEYS 'caregiving:*'
```

After the worker consumes a durable statement such as “He is anxious around loud noises,” PostgreSQL contains it:

```bash
docker compose exec postgres psql -U caregiving_app -d caregiving -c 'SELECT observation, created_at FROM behavioral_logs;'
```

The worker prints an INFO log for every job it processes, including whether it stored a private observation, stored an anonymous peer idea, or skipped peer sharing because consent was absent. It also logs failures before placing the job in `caregiving:fact-jobs:failed`.

The **Clear chat** button deletes only `caregiving:turns:<user-id>` in Redis. It deliberately leaves PostgreSQL long-term memory unchanged.

## Deterministic multi-user proof

After resetting and migrating the database, run:

```bash
python -m backend.multi_user_simulation
```

It uses the real worker and real ranking SQL with fixed, documented vectors so its results do not depend on an embedding provider. It creates Asha, Ben, Cara, and Dev and proves that Asha's unchecked success is private, Asha's checked success becomes one peer idea, a 100% match is shown, a 60% match is hidden until a second helpful rating, and a 40% match remains hidden. It also checks that the removed `matching_tags` column does not exist.

## Import an old Markdown profile once

If you used the former file-based version, import a profile only after checking
its facts are correct. This creates a PostgreSQL user plus profile and durable
observations; the Markdown file is left unchanged.

```bash
python -m backend.import_legacy_markdown --name "Arjun"
```

## Backfill embeddings

After configuring the Eden AI `EMBEDDING_URL`, `EMBEDDING_API_KEY`, and
`EMBEDDING_MODEL`, create vectors for memory stored while embeddings were
unavailable:

```bash
python -m backend.backfill_embeddings
```
