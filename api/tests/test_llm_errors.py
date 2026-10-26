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


def test_daily_limit_says_how_long_to_wait_in_plain_words():
    error = FakeGroqError("Rate limit reached ... on tokens per day (TPD). Please try again in 14m19.248s. Need 5000", 429)
    code, message = llm.reason_for(error)
    assert code == "daily_limit"
    assert "about 15 minutes" in message


def test_wait_in_words():
    assert llm.wait_in_words("try again in 45s") == "about 1 minute"
    assert llm.wait_in_words("try again in 3h2m10.5s") == "about 3 hours"
    assert llm.wait_in_words("nothing here") == ""


def test_messages_do_not_mention_settings_or_vendors():
    for message in (llm.MINUTE_LIMIT, llm.DAILY_LIMIT, llm.TOO_LARGE, llm.TIMED_OUT, llm.NOT_AVAILABLE):
        for word in (".env", "Groq", "model", "README"):
            assert word not in message
