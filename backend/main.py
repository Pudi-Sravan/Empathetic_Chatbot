from contextlib import asynccontextmanager
import json
from uuid import UUID

import asyncpg
from fastapi import FastAPI, HTTPException, Request, status
from redis.asyncio import Redis

from .intents import feedback_signal
from .schemas import (
    ChatRequest, ContextRequest, FeedbackRequest, FeedbackResponse, MessageRequest,
    UserCreateRequest, UserResponse,
)
from .services import (
    EmbeddingProvider, GroqChatProvider, append_turn, assemble_context, prompt_from_context,
    recent_turns,
)
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=20, command_timeout=10)
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.embeddings = EmbeddingProvider()
    app.state.chat = GroqChatProvider()
    yield
    await app.state.redis.aclose()
    await app.state.db.close()


app = FastAPI(title="Caregiving RAG API", version="1.0.0", lifespan=lifespan)


@app.post("/api/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreateRequest, request: Request):
    """Create the PostgreSQL record that owns one UI session's memories."""
    async with request.app.state.db.acquire() as db:
        row = await db.fetchrow(
            "INSERT INTO users (name) VALUES ($1) RETURNING id, name", payload.name
        )
    return UserResponse(**dict(row))


@app.get("/api/users/{user_id}/memory")
async def read_memory(user_id: UUID, request: Request):
    """Return Redis short-term turns and durable PostgreSQL facts for the UI."""
    async with request.app.state.db.acquire() as db:
        profile = await db.fetchrow("""
            SELECT u.id, u.name, u.age, u.weight, u.gender, u.interests_hobbies,
                   p.medical_conditions, p.caregiver_notes
            FROM users u LEFT JOIN patient_profiles p ON p.user_id = u.id
            WHERE u.id = $1
        """, user_id)
        if not profile:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        logs = await db.fetch("""
            SELECT observation, successful_intervention, created_at
            FROM behavioral_logs WHERE user_id = $1
            ORDER BY created_at DESC LIMIT 20
        """, user_id)
    return {
        "profile": dict(profile),
        "recent_turns": await recent_turns(request.app.state.redis, user_id),
        "recent_observations": [dict(row) for row in logs],
    }


@app.delete("/api/users/{user_id}/short-term-memory", status_code=status.HTTP_204_NO_CONTENT)
async def clear_short_term_memory(user_id: UUID, request: Request):
    """Clear only the per-user Redis window; PostgreSQL facts are retained."""
    async with request.app.state.db.acquire() as db:
        exists = await db.fetchval("SELECT 1 FROM users WHERE id = $1", user_id)
    if not exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    await request.app.state.redis.delete(f"caregiving:turns:{user_id}")


@app.post("/api/interventions/{intervention_id}/feedback", response_model=FeedbackResponse)
async def explicit_feedback(intervention_id: UUID, payload: FeedbackRequest, request: Request):
    column = "upvotes" if payload.action.value == "upvote" else "downvotes"
    # column is selected from a closed enum, never from untrusted input.
    query = f"UPDATE global_interventions SET {column} = {column} + 1 WHERE id = $1 RETURNING upvotes, downvotes"
    async with request.app.state.db.acquire() as db:
        row = await db.fetchrow(query, intervention_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "intervention not found")
    return FeedbackResponse(intervention_id=intervention_id, **dict(row), source="explicit")


@app.post("/api/users/{user_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def record_message(user_id: UUID, payload: MessageRequest, request: Request):
    signal = feedback_signal(payload.text)
    redis = request.app.state.redis
    await append_turn(redis, user_id, "user", payload.text)
    if payload.assistant_reply:
        await append_turn(redis, user_id, "assistant", payload.assistant_reply)
    if signal and payload.intervention_id:
        column = "upvotes" if signal > 0 else "downvotes"
        async with request.app.state.db.acquire() as db:
            row = await db.fetchrow(
                f"UPDATE global_interventions SET {column} = {column} + 1 WHERE id = $1 RETURNING id",
                payload.intervention_id,
            )
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "intervention not found")
    # A confirmation is feedback about an existing shared intervention, not a
    # new care fact. Do not accidentally promote "That worked" as its own idea.
    if signal and payload.intervention_id:
        return {"queued": False, "feedback_signal": signal}
    # A durable worker consumes facts; conversational text never directly mutates patient data.
    job = payload.model_dump(mode="json") | {"user_id": str(user_id), "signal": signal}
    await redis.lpush("caregiving:fact-jobs", json.dumps(job))
    return {"queued": True, "feedback_signal": signal}


@app.post("/api/users/{user_id}/context")
async def context(user_id: UUID, payload: ContextRequest, request: Request):
    async with request.app.state.db.acquire() as db:
        try:
            assembled = await assemble_context(db, request.app.state.redis, request.app.state.embeddings, user_id, payload.query, payload.limit)
        except LookupError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return {"context": assembled, "prompt": prompt_from_context(assembled, payload.query)}


@app.post("/api/users/{user_id}/chat")
async def chat(user_id: UUID, payload: ChatRequest, request: Request):
    """Retrieve first, then have Groq answer only from the bounded assembled facts."""
    async with request.app.state.db.acquire() as db:
        try:
            assembled = await assemble_context(
                db, request.app.state.redis, request.app.state.embeddings,
                user_id, payload.text, 5,
            )
        except LookupError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    prompt = prompt_from_context(assembled, payload.text)
    try:
        answer = await request.app.state.chat.complete(prompt)
    except RuntimeError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error))
    await append_turn(request.app.state.redis, user_id, "user", payload.text)
    await append_turn(request.app.state.redis, user_id, "assistant", answer)
    await request.app.state.redis.lpush("caregiving:fact-jobs", json.dumps({
        "user_id": str(user_id), "text": payload.text, "assistant_reply": answer,
        "signal": 0, "share_successful_intervention": payload.share_successful_intervention,
    }))
    return {"reply": answer, "interventions": assembled["global_interventions"]}
