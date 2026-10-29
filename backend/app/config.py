from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# From the eval sweeps in evals/results/. gemini: on the first two documents answerable
# questions scored >= 0.661 and out-of-scope ones <= 0.641, so 0.65 sat in the gap. That is
# PROVISIONAL until the five-document Gemini sweep is run: the local model's gap closed on that
# larger corpus (answerable >= 0.557, out-of-scope up to 0.641). local (bge) stays at the
# conservative 0.5 (no false refusals). hash is the test embedder and has no calibration.
THRESHOLDS = {"gemini": 0.65, "local": 0.5, "hash": 0.5}


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
    # Weight of the keyword ranking in RRF (vector = 1.0). With ts_rank, equal weights scored
    # best on the 5-document local eval (MRR 0.794 vs 0.755 at 0.25). Re-check with Gemini.
    keyword_weight: float = 1.0
    # Refuse when the best cosine similarity is below this. Similarity scales differ per
    # embedding model, so the default depends on the provider (see THRESHOLDS). Set
    # MIN_SIMILARITY to override; re-run `python -m evals.run --provider <p> --sweep` to retune.
    min_similarity: float | None = None

    max_upload_mb: int = 25
    cors_origins: list[str] = ["http://localhost:3000"]

    @model_validator(mode="after")
    def _default_threshold(self):
        if self.min_similarity is None:
            self.min_similarity = THRESHOLDS[self.embedding_provider]
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
