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

# The demo-preset limits, in the order of their preset values in Settings._defaults.
LIMITS = ("question_daily_limit", "visitor_question_limit", "visitor_upload_limit",
          "max_upload_chunks")


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

    # Free-tier guards (app/budget.py). DEMO_MODE=true is the public-demo preset: the shared
    # sample documents are read-only and questions are capped per visitor and per day. Each
    # setting below can still be set on its own; a value of 0 turns that limit off.
    demo_mode: bool = False
    uploads_enabled: bool | None = None  # default: on, except in demo mode
    # Groq allows 200k tokens a day and an answer costs about 3k, so ~60 answers a day in all.
    question_daily_limit: int | None = None  # demo preset: 60
    visitor_question_limit: int | None = None  # demo preset: 10
    visitor_upload_limit: int | None = None  # demo preset: 2 (only matters if uploads are on)
    max_upload_chunks: int | None = None  # demo preset: 150 (one chunk = one Gemini request)
    # Gemini's free tier counts one request per chunk, 1000 a day. `embed_query_reserve` of them
    # are kept back so uploads can never leave the app unable to embed a question.
    embed_daily_limit: int | None = None  # default: 1000 with Gemini embeddings, else none
    embed_query_reserve: int = 200
    # Behind a proxy that sets X-Forwarded-For itself (Vercel does), identify visitors by it.
    trust_forwarded_for: bool = False
    visitor_salt: str = "lexio"  # visitors are stored as a salted hash of their IP, never the IP

    @model_validator(mode="after")
    def _defaults(self):
        if self.min_similarity is None:
            self.min_similarity = THRESHOLDS[self.embedding_provider]
        demo = self.demo_mode
        if self.uploads_enabled is None:
            self.uploads_enabled = not demo
        if self.embed_daily_limit is None and self.embedding_provider == "gemini":
            self.embed_daily_limit = 1000
        for name, preset in zip(LIMITS, (60, 10, 2, 150), strict=True):
            if getattr(self, name) is None and demo:
                setattr(self, name, preset)
        for name in LIMITS + ("embed_daily_limit",):
            if getattr(self, name) == 0:
                setattr(self, name, None)  # an explicit 0 means "off", the same as unset
        limit = self.embed_daily_limit
        if limit and limit <= self.embed_query_reserve:  # a small limit still leaves room to upload
            self.embed_query_reserve = limit // 5
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
