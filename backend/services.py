import json
import logging
from typing import Any
from uuid import UUID

import asyncpg
import httpx
from redis.asyncio import Redis

from .settings import settings

logger = logging.getLogger(__name__)


class GroqChatProvider:
    """Generation uses the existing Groq account; embedding is intentionally separate."""
    async def complete(self, prompt: str) -> str:
        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY must be configured")
        from groq import AsyncGroq
        client = AsyncGroq(api_key=settings.groq_api_key)
        try:
            result = await client.chat.completions.create(
                model=settings.groq_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_completion_tokens=500,
            )
            return result.choices[0].message.content or "I could not generate a response."
        finally:
            await client.close()


def vector_literal(values: list[float]) -> str:
    if len(values) != 1536:
        raise ValueError("embedding provider must return exactly 1536 dimensions")
    return "[" + ",".join(str(float(v)) for v in values) + "]"


class EmbeddingProvider:
    """Eden AI v3 OpenAI-compatible embedding client."""

    async def embed(self, text: str) -> list[float]:
        if not settings.embedding_url or not settings.embedding_api_key:
            raise RuntimeError("EMBEDDING_URL and EMBEDDING_API_KEY must be configured")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {settings.embedding_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.embedding_model,
            "input": text,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(settings.embedding_url, headers=headers, json=payload)
            response.raise_for_status()
        body = response.json()
        try:
            values = body["data"][0]["embedding"]
        except (AttributeError, IndexError, KeyError, TypeError) as error:
            detail = body.get("error", body) if isinstance(body, dict) else body
            raise RuntimeError(f"Unexpected Eden AI v3 embedding response: {detail}") from error
        vector_literal(values)
        return values


async def optional_vector(embedder: EmbeddingProvider, text: str) -> str | None:
    """Return an embedding when available without blocking memory persistence."""
    if not settings.embeddings_enabled:
        return None
    try:
        return vector_literal(await embedder.embed(text))
    except Exception as error:
        logger.warning("Embedding unavailable; continuing without vector retrieval: %s", error)
        return None


async def append_turn(redis: Redis, user_id: UUID, role: str, content: str) -> None:
    key = f"caregiving:turns:{user_id}"
    await redis.rpush(key, json.dumps({"role": role, "content": content}))
    await redis.ltrim(key, -settings.short_term_max_messages, -1)
    await redis.expire(key, settings.context_ttl_seconds)


async def recent_turns(redis: Redis, user_id: UUID) -> list[dict[str, str]]:
    raw = await redis.lrange(f"caregiving:turns:{user_id}", 0, -1)
    return [json.loads(item) for item in raw]


RANKED_INTERVENTIONS = """
WITH candidates AS (
  SELECT id, scenario_description, solution_action, upvotes, downvotes,
         1 - (scenario_embedding <=> $1::vector) AS cosine_similarity,
         upvotes - downvotes AS net_upvotes
  FROM global_interventions
  ORDER BY scenario_embedding <=> $1::vector
  LIMIT 100
)
SELECT *,
  CASE WHEN net_upvotes >= $3
       THEN 0.40 * cosine_similarity
          + 0.60 * (net_upvotes::float / (net_upvotes + 3))
       ELSE 0.70 * cosine_similarity
          + 0.30 * (GREATEST(net_upvotes, 0)::float / (upvotes + downvotes + 3))
  END AS hybrid_score,
  CASE WHEN net_upvotes >= $3 THEN 'trusted_50_percent' ELSE 'standard_70_percent' END
    AS trust_tier
FROM candidates
WHERE cosine_similarity >= CASE
  WHEN net_upvotes >= $3 THEN $4::double precision
  ELSE $5::double precision
END
ORDER BY hybrid_score DESC, upvotes DESC
LIMIT $2;
"""


async def assemble_context(
    db: asyncpg.Connection, redis: Redis, embeddings: EmbeddingProvider,
    user_id: UUID, query: str, limit: int,
) -> dict[str, Any]:
    profile = await db.fetchrow("""
        SELECT u.name, u.age, u.weight, u.gender, u.interests_hobbies,
               p.medical_conditions, p.caregiver_notes
        FROM users u LEFT JOIN patient_profiles p ON p.user_id = u.id WHERE u.id = $1
    """, user_id)
    if not profile:
        raise LookupError("user not found")
    vector = await optional_vector(embeddings, query)
    if vector is not None:
        logs = await db.fetch("""
            SELECT observation, successful_intervention, created_at,
                   1 - (embedding <=> $2::vector) AS similarity
            FROM behavioral_logs WHERE user_id = $1 AND embedding IS NOT NULL
            ORDER BY embedding <=> $2::vector LIMIT $3
        """, user_id, vector, limit)
        interventions = await db.fetch(
            RANKED_INTERVENTIONS,
            vector,
            limit,
            settings.intervention_trusted_min_upvotes,
            settings.intervention_trusted_similarity_threshold,
            settings.intervention_standard_similarity_threshold,
        )
    else:
        # The chatbot remains usable with Redis + PostgreSQL alone.  Vector
        # retrieval becomes available as soon as embedding credentials are set.
        logs = await db.fetch("""
            SELECT observation, successful_intervention, created_at
            FROM behavioral_logs WHERE user_id = $1
            ORDER BY created_at DESC LIMIT $2
        """, user_id, limit)
        interventions = []
    return {
        "history": await recent_turns(redis, user_id),
        "profile": dict(profile),
        "relevant_logs": [dict(row) for row in logs],
        "global_interventions": [dict(row) for row in interventions],
    }


def prompt_from_context(context: dict[str, Any], query: str) -> str:
    """Facts are clearly bounded, so an LLM can decline unsupported claims."""
    return (
        "You are a warm, practical caregiving support assistant. Use ONLY FACTS below for "
        "personalization. Do not invent diagnoses, preferences, outcomes, or medical advice. "
        "If facts are missing, say so.\n"
        "RESPONSE STYLE: Default to one or two short, natural paragraphs (about 80 words or fewer). "
        "Answer the user's specific question first; do not restate their whole situation or recite "
        "the memory context. Do not use a table. Use a short bullet list only when it makes a concrete "
        "multi-step plan clearer, with no more than 4 bullets. Give longer detail only when the user "
        "explicitly asks for it or the situation genuinely needs safety-critical instructions.\n"
        f"FACTS={json.dumps(context, default=str, separators=(',', ':'))}\n"
        f"USER={query}\n"
        "If a global intervention is relevant, lead with the highest ranked one and describe it "
        "as a peer-reported idea that may be worth trying, not as a guaranteed outcome or medical "
        "advice. Respond with empathy and only the useful next step(s)."
    )
