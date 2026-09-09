from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql://postgres:postgres@localhost:5432/caregiving"
    redis_url: str = "redis://localhost:6379/0"
    embedding_url: str | None = None
    embedding_api_key: str | None = None
    # Eden AI v3 identifies models as "provider/model", for example
    # "openai/text-embedding-3-small".
    embedding_model: str = "openai/text-embedding-3-small"
    intervention_standard_similarity_threshold: float = 0.70
    intervention_trusted_similarity_threshold: float = 0.50
    intervention_trusted_min_upvotes: int = 2
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-20b"
    context_ttl_seconds: int = 86_400
    short_term_max_messages: int = 8

    @property
    def embeddings_enabled(self) -> bool:
        """Vector retrieval is optional; memory persistence is not."""
        return bool(self.embedding_url and self.embedding_api_key)


settings = Settings()
