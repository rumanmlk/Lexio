from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql://lexio:lexio@localhost:5433/lexio"

    embedding_provider: Literal["gemini", "local", "hash"] = "gemini"
    embedding_dim: int = 768
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-2"
    local_embedding_model: str = "BAAI/bge-base-en-v1.5"

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    chunk_chars: int = 1200
    chunk_overlap_chars: int = 150
    retrieve_candidates: int = 30
    retrieve_top_k: int = 6
    # With no keyword hit and a best cosine similarity below this, we refuse instead of guessing.
    # Provisional: calibrate per embedding model with `python -m evals.run`.
    min_similarity: float = 0.5

    max_upload_mb: int = 25
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
