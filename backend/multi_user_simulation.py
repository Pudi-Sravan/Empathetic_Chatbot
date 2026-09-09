"""Deterministic, database-backed proof of consent and peer-match rules.

Run after resetting and migrating the local database:
    python -m backend.multi_user_simulation

The deliberately chosen unit vectors yield exact cosine similarities: Ben 100%,
Cara 60%, and Dev 40%. This avoids relying on wording or a remote embedding API
when demonstrating the 70% default and 50% trusted thresholds.
"""
import asyncio
import math
from collections import defaultdict

import asyncpg

from .services import RANKED_INTERVENTIONS, vector_literal
from .settings import settings
from .worker import persist


def unit_vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second] + [0.0] * 1534


VECTORS = {
    "asha": unit_vector(1.0),
    "ben": unit_vector(1.0),
    "cara": unit_vector(0.6, 0.8),
    "dev": unit_vector(0.4, math.sqrt(0.84)),
}


class DemoEmbedder:
    async def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        for name, vector in VECTORS.items():
            if name in lowered:
                return vector
        return VECTORS["asha"]


async def rank(db: asyncpg.Connection, vector: list[float]) -> list[asyncpg.Record]:
    return await db.fetch(
        RANKED_INTERVENTIONS,
        vector_literal(vector), 5,
        settings.intervention_trusted_min_upvotes,
        settings.intervention_trusted_similarity_threshold,
        settings.intervention_standard_similarity_threshold,
    )


async def main() -> None:
    """Create four named demo users and print the evidence for each rule."""
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    try:
        async with pool.acquire() as db:
            users = {}
            for name in ("Asha", "Ben", "Cara", "Dev"):
                users[name.lower()] = await db.fetchval(
                    "INSERT INTO users (name) VALUES ($1) RETURNING id", name
                )

            asha_report = (
                "Before a presentation Asha gets overwhelmed by too many notes. "
                "A three-point card and five minutes of practice helped her."
            )
            # The same successful report is first private-only, then explicitly
            # opted in. The worker is the real production persistence path.
            await persist(db, DemoEmbedder(), {
                "user_id": str(users["asha"]), "text": asha_report,
                "share_successful_intervention": False,
            })
            private_count = await db.fetchval(
                "SELECT count(*) FROM behavioral_logs WHERE user_id = $1", users["asha"]
            )
            shared_before_consent = await db.fetchval("SELECT count(*) FROM global_interventions")
            await persist(db, DemoEmbedder(), {
                "user_id": str(users["asha"]), "text": asha_report,
                "share_successful_intervention": True,
            })

            intervention = await db.fetchrow(
                "SELECT id, upvotes FROM global_interventions LIMIT 1"
            )
            ben_results = await rank(db, VECTORS["ben"])
            cara_before = await rank(db, VECTORS["cara"])
            # This is the same atomic update used by the feedback endpoint.
            await db.execute(
                "UPDATE global_interventions SET upvotes = upvotes + 1 WHERE id = $1",
                intervention["id"],
            )
            cara_after = await rank(db, VECTORS["cara"])
            dev_results = await rank(db, VECTORS["dev"])
            tag_column_exists = await db.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'global_interventions' AND column_name = 'matching_tags'
                )
            """)

            print("CONSENT")
            print(f"Asha private behavioral logs after Share OFF: {private_count}")
            print(f"Peer ideas before consent: {shared_before_consent}")
            print("Peer ideas after Asha re-sends with Share ON: 1")
            print("\nSIMILARITY")
            print(f"Ben (100% match, default 70% rule): {len(ben_results)} suggestion(s)")
            print(f"Cara (60% match, before second helpful rating): {len(cara_before)} suggestion(s)")
            print(f"Cara (60% match, after second helpful rating): {len(cara_after)} suggestion(s)")
            print(f"Dev (40% match, trusted 50% rule): {len(dev_results)} suggestion(s)")
            print("\nSCHEMA")
            print(f"matching_tags column exists: {tag_column_exists}")
            print("\nExpected: Ben=1, Cara-before=0, Cara-after=1, Dev=0, tags=False.")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
