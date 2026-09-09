import asyncio
import json
import unittest
from uuid import uuid4

from backend.services import append_turn, recent_turns
from backend.worker import extract_explicit


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.ttls = {}

    async def rpush(self, key, value):
        self.data.setdefault(key, []).append(value)

    async def ltrim(self, key, start, end):
        self.data[key] = self.data.get(key, [])[start : end + 1 if end != -1 else None]

    async def expire(self, key, seconds):
        self.ttls[key] = seconds

    async def lrange(self, key, start, end):
        return self.data.get(key, [])[start : end + 1 if end != -1 else None]


class MemoryTests(unittest.TestCase):
    def test_short_term_turns_are_redis_backed_and_bounded(self):
        redis = FakeRedis()
        user_id = uuid4()

        async def run():
            for number in range(10):
                await append_turn(redis, user_id, "user", str(number))
            return await recent_turns(redis, user_id)

        turns = asyncio.run(run())
        self.assertEqual([turn["content"] for turn in turns], [str(i) for i in range(2, 10)])
        self.assertEqual(redis.ttls[f"caregiving:turns:{user_id}"], 86_400)

    def test_only_durable_explicit_statement_is_extracted(self):
        facts = extract_explicit("He gets anxious around loud noises and headphones help him.")
        self.assertIn("observation", facts)
        self.assertIn("successful_intervention", facts)
        self.assertEqual(extract_explicit("What should I do when he is anxious?"), {})

    def test_user_behavior_tags_are_not_an_extracted_fact(self):
        facts = extract_explicit("Tag this behavior as sensory-sensitive.")
        self.assertNotIn("behavior_tag", facts)
        self.assertNotIn("matching_tags", facts)


if __name__ == "__main__":
    unittest.main()
