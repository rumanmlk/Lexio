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
    # Weight of the keyword ranking in RRF (vector = 1.0). 0.25 gave the best recall in evals.
    keyword_weight: float = 0.25
    # Refuse when the best cosine similarity is below this. Similarity scales differ per
    # embedding model: 0.5 is calibrated for bge-base-en-v1.5 only. Re-run
    # `python -m evals.run --provider gemini --sweep` and set MIN_SIMILARITY for Gemini.
    min_similarity: float = 0.5

    max_upload_mb: int = 25
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
