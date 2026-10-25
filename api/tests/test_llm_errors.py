"""The screen says why an AI call failed (N6): a free limit, a request too large, or something else."""

from app import llm


class FakeGroqError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RateLimitError(Exception):
    """Named like the Groq SDK's error, without a status code."""


def test_per_minute_limit():
    error = FakeGroqError("Rate limit reached for model in organization on tokens per minute (TPM)", 429)
    assert llm.reason_for(error) == ("minute_limit", llm.MINUTE_LIMIT)


def test_daily_limit():
    error = FakeGroqError("Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 199000", 429)
    assert llm.reason_for(error) == ("daily_limit", llm.DAILY_LIMIT)


def test_rate_limit_known_by_its_name():
    assert llm.reason_for(RateLimitError("slow down"))[0] == "minute_limit"


def test_request_too_large():
    error = FakeGroqError("Request too large for model on tokens per minute (TPM): Limit 8000, Requested 9500", 413)
    assert llm.reason_for(error) == ("too_large", llm.TOO_LARGE)


def test_timeout():
    class APITimeoutError(Exception):
        pass

    assert llm.reason_for(APITimeoutError("Request timed out."))[0] == "timeout"


def test_anything_else_keeps_the_general_message():
    assert llm.reason_for(ValueError("bad json")) == ("other", llm.NOT_AVAILABLE)
