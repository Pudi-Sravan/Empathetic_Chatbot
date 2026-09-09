import asyncio
import unittest
from unittest.mock import patch

from backend.services import EmbeddingProvider, RANKED_INTERVENTIONS
from backend.settings import settings


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "data": [{"embedding": [0.1] * 1536}],
        }


class FakeClient:
    request = None

    def __init__(self, *, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, *, headers, json):
        type(self).request = {"url": url, "headers": headers, "json": json}
        return FakeResponse()


class EdenAIEmbeddingTests(unittest.TestCase):
    def test_shared_intervention_query_uses_similarity_gates(self):
        self.assertIn("WHEN net_upvotes >= $3 THEN $4", RANKED_INTERVENTIONS)
        self.assertIn("ELSE $5", RANKED_INTERVENTIONS)
        self.assertIn("LIMIT $2", RANKED_INTERVENTIONS)
        self.assertNotIn("matching_tags", RANKED_INTERVENTIONS)
        self.assertIn("cosine_similarity >= CASE", RANKED_INTERVENTIONS)
        self.assertIn("0.60 * (net_upvotes::float / (net_upvotes + 3))", RANKED_INTERVENTIONS)

    def test_uses_eden_ai_v3_request_and_response_shape(self):
        previous_url = settings.embedding_url
        previous_key = settings.embedding_api_key
        previous_model = settings.embedding_model
        settings.embedding_url = "https://api.edenai.run/v3/embeddings"
        settings.embedding_api_key = "test-key"
        settings.embedding_model = "openai/text-embedding-3-small"
        try:
            with patch("backend.services.httpx.AsyncClient", FakeClient):
                vector = asyncio.run(EmbeddingProvider().embed("hello"))
        finally:
            settings.embedding_url = previous_url
            settings.embedding_api_key = previous_key
            settings.embedding_model = previous_model

        self.assertEqual(len(vector), 1536)
        self.assertEqual(
            FakeClient.request["json"],
            {
                "model": "openai/text-embedding-3-small",
                "input": "hello",
            },
        )
        self.assertEqual(FakeClient.request["headers"]["Authorization"], "Bearer test-key")

if __name__ == "__main__":
    unittest.main()
