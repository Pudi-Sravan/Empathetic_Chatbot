"""One-time import of a confirmed legacy Markdown profile into PostgreSQL.

Usage: python -m backend.import_legacy_markdown --name Arjun
"""
import argparse
import asyncio
import re
from pathlib import Path

import asyncpg

from .services import EmbeddingProvider, vector_literal
from .settings import settings

SECTION = re.compile(r"^###\s+(.+?)\s*$")


def parse_profile(path: Path, name: str) -> tuple[int | None, list[str], list[str], list[str]]:
    """Return directly written age, conditions, triggers, and helpful routines."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if match := SECTION.match(raw_line):
            current = match.group(1).strip().lower()
            sections.setdefault(current, [])
        elif current and raw_line.startswith("- "):
            sections[current].append(raw_line[2:].strip())

    general = sections.get("general info", [])
    age = None
    conditions: list[str] = []
    age_pattern = re.compile(rf"\b{re.escape(name)}\s+is\s+(\d{{1,3}})\s+years? old\b", re.I)
    condition_pattern = re.compile(rf"\b{re.escape(name)}\s+has\s+(.+?)\.?$", re.I)
    for item in general:
        if match := age_pattern.search(item):
            candidate = int(match.group(1))
            if candidate <= 130:
                age = candidate
        if match := condition_pattern.search(item):
            conditions.append(match.group(1).strip())

    triggers = sections.get("sensory & behavioral triggers", [])
    routines = sections.get("calming strategies & routines", [])
    return age, conditions, triggers, routines


async def optional_embedding(embedder: EmbeddingProvider, text: str) -> str | None:
    if not settings.embeddings_enabled:
        return None
    try:
        return vector_literal(await embedder.embed(text))
    except Exception as error:
        print(f"Warning: stored without embedding ({error}).")
        return None


async def main(path: Path, name: str) -> None:
    age, conditions, triggers, routines = parse_profile(path, name)
    if not any((age is not None, conditions, triggers, routines)):
        raise ValueError("No supported profile facts were found in the Markdown file.")

    db = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=1)
    embedder = EmbeddingProvider()
    try:
        async with db.acquire() as connection:
            async with connection.transaction():
                user = await connection.fetchrow(
                    "INSERT INTO users (name, age) VALUES ($1, $2) RETURNING id", name, age
                )
                user_id = user["id"]
                if conditions:
                    text = "\n".join(dict.fromkeys(conditions))
                    embedding = await optional_embedding(embedder, text)
                    await connection.execute(
                        """INSERT INTO patient_profiles (user_id, medical_conditions, embedding)
                           VALUES ($1, $2, $3::vector)""",
                        user_id, text, embedding,
                    )
                for observation in triggers + routines:
                    embedding = await optional_embedding(embedder, observation)
                    await connection.execute(
                        """INSERT INTO behavioral_logs
                           (user_id, observation, successful_intervention, embedding, source_text_hash)
                           VALUES ($1, $2, $3, $4::vector, md5($2))
                           ON CONFLICT (user_id, source_text_hash) DO NOTHING""",
                        user_id,
                        observation,
                        observation if observation in routines else None,
                        embedding,
                    )
        print(f"Imported legacy profile for {name} ({user_id}).")
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="Exact care recipient name in the profile")
    parser.add_argument("--file", type=Path, default=Path("long_term_memory.md"))
    args = parser.parse_args()
    asyncio.run(main(args.file, args.name))
