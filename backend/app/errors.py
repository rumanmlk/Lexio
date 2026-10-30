from dataclasses import dataclass

import httpx

RETRYABLE = (429, 500, 502, 503, 504)
QUOTA_WAIT = 120.0  # a wait longer than this means a daily quota, not a per-minute burst


class ProviderError(Exception):
    """An upstream service (embeddings, LLM) failed. `status` is what our API should answer
    with: 502 when the provider rejected us, 503 when it is busy or unreachable. `quota` marks
    a used-up daily limit, which retrying cannot fix."""

    def __init__(self, status: int, message: str, quota: bool = False):
        super().__init__(message)
        self.status, self.message, self.quota = status, message, quota


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 4
    backoff: float = 1.0  # seconds; doubles per attempt
    max_wait: float = 30.0  # longest pause honoured when the provider sends Retry-After


def retry_after_seconds(resp: httpx.Response) -> float | None:
    """How long the provider says to wait: a Retry-After header, or Google's RetryInfo detail."""
    try:
        return float(resp.headers["retry-after"])
    except (KeyError, ValueError):
        pass
    try:
        for detail in resp.json()["error"]["details"]:
            if str(detail.get("@type", "")).endswith("RetryInfo"):
                return float(str(detail["retryDelay"]).rstrip("s"))
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


def retry_delay(exc: Exception, attempt: int, policy: RetryPolicy) -> float | None:
    """Seconds to wait before the next try, or None when retrying cannot help (a rejected key,
    a bad request, a used-up daily quota)."""
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code not in RETRYABLE:
            return None
        advised = retry_after_seconds(exc.response)
        if advised is None:
            return policy.backoff * 2**attempt
        return None if advised > QUOTA_WAIT else min(advised, policy.max_wait)
    return policy.backoff * 2**attempt if isinstance(exc, httpx.TransportError) else None


def duration(seconds: float) -> str:
    if seconds >= 5400:
        return f"{round(seconds / 3600)} hours"
    return f"{max(1, round(seconds / 60))} minutes"


def from_exception(provider: str, exc: Exception) -> ProviderError:
    """Translate an httpx failure into a message that is safe to show a client:
    never the response body or request headers, which could echo credentials."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return ProviderError(502, f"{provider} rejected the API key. Check it in .env.")
        if code == 429:
            advised = retry_after_seconds(exc.response)
            if advised and advised > QUOTA_WAIT:
                return ProviderError(
                    503,
                    f"{provider} quota is used up; it resets in about {duration(advised)}.",
                    quota=True,
                )
            return ProviderError(503, f"{provider} rate limit reached. Try again shortly.")
        if code >= 500:
            return ProviderError(502, f"{provider} is having problems (HTTP {code}).")
        return ProviderError(502, f"{provider} rejected the request (HTTP {code}).")
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError(503, f"{provider} timed out. Try again.")
    return ProviderError(503, f"{provider} could not be reached.")
