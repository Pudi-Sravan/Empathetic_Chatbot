"""Create missing pgvector embeddings after valid embedding credentials are configured."""
import asyncio

import asyncpg

from .services import EmbeddingProvider, optional_vector
from .settings import settings


async def main() -> None:
    if not settings.embeddings_enabled:
        raise RuntimeError("Set EMBEDDING_URL and EMBEDDING_API_KEY first.")
    db = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=1)
    embedder = EmbeddingProvider()
    updated_profiles = updated_logs = 0
    try:
        async with db.acquire() as connection:
            profiles = await connection.fetch(
                "SELECT id, medical_conditions FROM patient_profiles WHERE embedding IS NULL AND medical_conditions <> ''"
            )
            for row in profiles:
                if vector := await optional_vector(embedder, row["medical_conditions"]):
                    await connection.execute("UPDATE patient_profiles SET embedding = $2::vector WHERE id = $1", row["id"], vector)
                    updated_profiles += 1
            logs = await connection.fetch(
                "SELECT id, observation FROM behavioral_logs WHERE embedding IS NULL"
            )
            for row in logs:
                if vector := await optional_vector(embedder, row["observation"]):
                    await connection.execute("UPDATE behavioral_logs SET embedding = $2::vector WHERE id = $1", row["id"], vector)
                    updated_logs += 1
    finally:
        await db.close()
    print(f"Embedded {updated_profiles} profiles and {updated_logs} observations.")


if __name__ == "__main__":
    asyncio.run(main())
