import json
import re
from collections.abc import AsyncIterator

from app.llm import LLM
from app.retrieval import Hit, Retrieval

SYSTEM_PROMPT = """You are Lexio, an assistant that answers questions about legal documents.

Rules:
- Use ONLY the numbered sources provided. Never use outside knowledge.
- Cite every claim with its source number in square brackets, like [1] or [2][3].
- If the sources do not contain the answer, reply exactly:
  "I can't find this in the provided documents."
- Quote exact wording for definitions, deadlines, amounts and obligations.
- You are not a lawyer; do not give legal advice. Describe what the document says.
"""

REFUSAL = "I can't find this in the provided documents."


def build_user_prompt(question: str, hits: list[Hit]) -> str:
    sources = "\n\n".join(
        f"[{i}] ({h.filename}, page {h.page})\n{h.content}" for i, h in enumerate(hits, start=1)
    )
    return f"Sources:\n{sources}\n\nQuestion: {question}"


def cited_numbers(answer: str, n_sources: int) -> list[int]:
    found = {int(m) for m in re.findall(r"\[(\d+)\]", answer)}
    return sorted(i for i in found if 1 <= i <= n_sources)


def should_refuse(r: Retrieval, min_similarity: float) -> bool:
    """Refuse when nothing matched by keyword and the best embedding match is weak."""
    if not r.hits:
        return True
    return not r.has_keyword_match and r.top_similarity < min_similarity


def source_payload(i: int, h: Hit) -> dict:
    return {
        "n": i,
        "document_id": str(h.document_id),
        "filename": h.filename,
        "page": h.page,
        "snippet": h.content[:400],
        "score": round(h.score, 5),
    }


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def answer_stream(
    llm: LLM, question: str, retrieval: Retrieval, *, min_similarity: float
) -> AsyncIterator[str]:
    if should_refuse(retrieval, min_similarity):
        yield sse("sources", {"sources": []})
        yield sse("token", {"text": REFUSAL})
        yield sse("done", {"grounded": False, "cited": []})
        return

    hits = retrieval.hits
    yield sse("sources", {"sources": [source_payload(i, h) for i, h in enumerate(hits, 1)]})
    text = ""
    try:
        async for piece in llm.stream(SYSTEM_PROMPT, build_user_prompt(question, hits)):
            text += piece
            yield sse("token", {"text": piece})
    except Exception as exc:  # surface provider failures to the client instead of a dropped stream
        yield sse("error", {"message": f"LLM request failed: {type(exc).__name__}"})
        return
    cited = cited_numbers(text, len(hits))
    yield sse("done", {"grounded": bool(cited) and REFUSAL not in text, "cited": cited})
