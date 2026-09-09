"""Run separately: python -m backend.worker. Redis BRPOP gives at-least-once delivery."""
import asyncio
import json
import logging
import re
from uuid import UUID

import asyncpg
from redis.asyncio import Redis

from .services import EmbeddingProvider, optional_vector
from .settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

AGE = re.compile(r"\b(?:i am|(?:the )?(?:patient|child) is|(?:he|she|they) (?:is|are))\s+(\d{1,3})\s+(?:years? old|yo)\b", re.I)
HOBBIES = re.compile(r"\b(?:likes?|enjoys?|loves?)\s+([a-z][a-z ,'-]{1,100})", re.I)
MEDICAL = re.compile(r"\b(?:has|diagnosed with|has a diagnosis of)\s+([a-z][a-z ,&'-]{1,120})", re.I)
SUCCESS = re.compile(
    r"\b(?:work(?:ed|s)?|help(?:ed|s)?|calmed (?:him|her|them)|"
    r"was effective|makes? (?:him|her|them) calmer)\b", re.I,
)
TRIGGER = re.compile(
    r"\b(?:anxious|anxiety|overwhelmed|overwhelm|afraid|fear|frightened|"
    r"sensitive|struggles? with|difficulty (?:with|handling)|doesn.t handle)\b",
    re.I,
)


def extract_explicit(text: str) -> dict[str, object]:
    """Conservative regex extraction: only directly asserted text is persisted."""
    result: dict[str, object] = {}
    if match := AGE.search(text):
        age = int(match.group(1))
        if age <= 130:
            result["age"] = age
    if match := HOBBIES.search(text):
        result["hobby"] = match.group(1).strip(" .,;")
    if match := MEDICAL.search(text):
        result["condition"] = match.group(1).strip(" .,;")
    # Only durable, explicitly reported observations belong in PostgreSQL.
    # Questions, greetings, and unrelated daily events must not become history.
    if (not text.rstrip().endswith("?") and len(text.strip()) >= 8
            and (TRIGGER.search(text) or SUCCESS.search(text) or result)):
        result["observation"] = text.strip()
        if SUCCESS.search(text):
            result["successful_intervention"] = text.strip()
    return result


async def persist(db: asyncpg.Connection, embedder: EmbeddingProvider, job: dict) -> None:
    user_id = UUID(job["user_id"])
    facts = extract_explicit(job["text"])
    logger.info("Processing fact job user_id=%s extracted=%s consent_to_share=%s", user_id, sorted(facts), job.get("share_successful_intervention", False))
    if not facts:
        logger.info("No durable database record added user_id=%s reason=no_explicit_durable_fact", user_id)
        return
    if "age" in facts:
        await db.execute("UPDATE users SET age = $2 WHERE id = $1", user_id, facts["age"])
        logger.info("Stored private age user_id=%s age=%s", user_id, facts["age"])
    if "hobby" in facts:
        await db.execute("""UPDATE users SET interests_hobbies =
          CASE WHEN interests_hobbies @> jsonb_build_array($2::text) THEN interests_hobbies
               ELSE interests_hobbies || jsonb_build_array($2::text) END WHERE id = $1""", user_id, facts["hobby"])
        logger.info("Stored private hobby user_id=%s hobby=%r", user_id, facts["hobby"])
    if "condition" in facts:
        profile_text = str(facts["condition"])
        vector = await optional_vector(embedder, profile_text)
        await db.execute("""INSERT INTO patient_profiles (user_id, medical_conditions, embedding)
          VALUES ($1, $2, $3::vector)
          ON CONFLICT (user_id) DO UPDATE SET medical_conditions =
            CASE WHEN patient_profiles.medical_conditions ILIKE '%' || EXCLUDED.medical_conditions || '%'
                 THEN patient_profiles.medical_conditions
                 ELSE concat_ws(E'\\n', patient_profiles.medical_conditions, EXCLUDED.medical_conditions) END,
            embedding = COALESCE(EXCLUDED.embedding, patient_profiles.embedding)""",
            user_id, profile_text, vector)
        logger.info("Stored private medical condition user_id=%s condition=%r", user_id, profile_text)
    if "observation" in facts:
        observation = str(facts["observation"])
        vector = await optional_vector(embedder, observation)
        log_id = await db.fetchval("""INSERT INTO behavioral_logs
          (user_id, observation, successful_intervention, embedding, source_text_hash)
          VALUES ($1, $2, $3, $4::vector, md5($2))
          ON CONFLICT (user_id, source_text_hash) DO NOTHING
          RETURNING id""",
          user_id, observation, facts.get("successful_intervention"), vector)
        logger.info("%s private behavioral_log user_id=%s observation=%r successful=%s", "Stored" if log_id else "Skipped duplicate", user_id, observation, bool(facts.get("successful_intervention")))
        if job.get("share_successful_intervention") and facts.get("successful_intervention") and vector:
            # Only an opted-in, explicitly reported outcome enters the shared library.
            # The first report counts as one positive outcome; later user feedback is
            # recorded through the feedback endpoints.
            shared = await db.fetchrow("""INSERT INTO global_interventions
              (scenario_description, solution_action, scenario_embedding, upvotes, source_text_hash)
              VALUES ($1, $2, $3::vector, 1, md5($1 || $2))
              ON CONFLICT (source_text_hash) DO UPDATE
              SET upvotes = global_interventions.upvotes + 1
              RETURNING id, upvotes""",
              observation, facts["successful_intervention"], vector)
            logger.info("Stored anonymous shared intervention user_id=%s intervention_id=%s upvotes=%s scenario=%r", user_id, shared["id"], shared["upvotes"], observation)
        elif facts.get("successful_intervention"):
            logger.info("Skipped shared intervention user_id=%s reason=%s", user_id, "consent_not_given" if not job.get("share_successful_intervention") else "embedding_unavailable")


async def main() -> None:
    db = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
    # redis-py's asyncio connection defaults to a five-second socket timeout.
    # That deadline races a BRPOP with timeout=5 when the queue is empty, and
    # raises TimeoutError instead of returning None.  Keep the socket read open
    # for the server-side blocking command and let BRPOP control the poll time.
    redis = Redis.from_url(
        settings.redis_url, decode_responses=True, socket_timeout=None
    )
    embedder = EmbeddingProvider()
    try:
        while True:
            item = await redis.brpop("caregiving:fact-jobs", timeout=5)
            if not item:
                continue
            try:
                async with db.acquire() as connection:
                    async with connection.transaction():
                        await persist(connection, embedder, json.loads(item[1]))
            except Exception:
                # Preserve failed work for inspection/retry; do not lose a fact silently.
                logger.exception("Fact job failed; moved to caregiving:fact-jobs:failed")
                await redis.lpush("caregiving:fact-jobs:failed", item[1])
    finally:
        await redis.aclose()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Normal shutdown while BRPOP is waiting for the next fact job.
        pass
