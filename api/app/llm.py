"""The LLM Client Wrapper: the only place in the code that talks to the language model.

Every agent calls ask_llm(). If the model is down, slow or answers in the wrong
shape, ask_llm() raises LLMUnavailable, and the agent turns that into a clear
error state instead of crashing (N6).

measure_usage() (F11) counts the AI calls, tokens and cost of everything asked inside it, so a
piece of work can report what it cost. Outside measure_usage() nothing is counted or changed.
"""
import logging
import re
import threading
from contextlib import contextmanager
from contextvars import ContextVar

from langchain_core.callbacks import BaseCallbackHandler
from langchain_groq import ChatGroq
from pydantic import BaseModel

from app.settings import settings

log = logging.getLogger("talentsight.llm")


class LLMUnavailable(Exception):
    """The language model could not give a usable answer."""


# What the screen says, by the reason the AI call failed. The default stays the general message.
NOT_AVAILABLE = "The AI service is not available right now. Please try again."
MINUTE_LIMIT = "The AI is busy right now. Please wait a minute and try again."
DAILY_LIMIT = "The AI has used up its free allowance for now. Please try again later. Nothing has been lost."
TOO_LARGE = "This is too long for the AI to handle in one go. Please try again with less content."
TIMED_OUT = "The AI took too long to answer. Please try again."


def wait_in_words(text: str) -> str:
    """"3h2m10.5s" -> "about 4 hours"; "14m19.2s" -> "about 15 minutes". Empty when the text has no wait."""
    found = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)?s?", text)
    if not found or not any(found.groups()):
        return ""
    hours, minutes, seconds = int(found.group(1) or 0), int(found.group(2) or 0), float(found.group(3) or 0)
    total = hours * 60 + minutes + (1 if seconds > 0 else 0)
    if total >= 90:
        count = round(total / 60)
        return f"about {count} hours"
    total = max(total, 1)
    return f"about {total} minute{'s' if total != 1 else ''}"


def reason_for(error: Exception) -> tuple[str, str]:
    """(short code for the log, message for the screen) for a failed AI call. Plain code.

    Groq answers 429 when a free limit is reached (per minute or per day) and 413 when one request
    is larger than the per-minute token limit, so waiting would not help."""
    status_code = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
    name = type(error).__name__
    text = str(error).lower()
    if status_code == 413 or "request too large" in text or "context_length" in text:
        return "too_large", TOO_LARGE
    if status_code == 429 or name == "RateLimitError" or "rate limit" in text:
        if "per day" in text or "(tpd)" in text or "(rpd)" in text:
            wait = wait_in_words(text)
            if wait:
                return "daily_limit", DAILY_LIMIT.replace("try again later", f"try again in {wait}")
            return "daily_limit", DAILY_LIMIT
        return "minute_limit", MINUTE_LIMIT
    if "timeout" in name.lower() or "timed out" in text:
        return "timeout", TIMED_OUT
    return "other", NOT_AVAILABLE


class UsageMeter(BaseCallbackHandler):
    """Adds up the calls and tokens of every AI answer it is told about."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._lock = threading.Lock()  # agent steps can run in worker threads

    def on_llm_end(self, response, **kwargs) -> None:
        used_in, used_out = 0, 0
        for generations in response.generations:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None) or {}
                used_in += usage.get("input_tokens", 0)
                used_out += usage.get("output_tokens", 0)
        if not (used_in or used_out):  # some versions only report it here
            token_usage = (response.llm_output or {}).get("token_usage") or {}
            used_in = token_usage.get("prompt_tokens", 0)
            used_out = token_usage.get("completion_tokens", 0)
        with self._lock:
            self.calls += 1
            self.input_tokens += used_in
            self.output_tokens += used_out

    def cost_usd(self) -> float:
        """The cost at the list prices in the settings (US dollars per million tokens)."""
        cost = (
            self.input_tokens * settings.llm_price_input_per_million
            + self.output_tokens * settings.llm_price_output_per_million
        ) / 1_000_000
        return round(cost, 6)


current_meter: ContextVar[UsageMeter | None] = ContextVar("llm_usage_meter", default=None)


@contextmanager
def measure_usage():
    """with measure_usage() as meter: ... -> meter.calls, meter.input_tokens, meter.cost_usd()"""
    meter = UsageMeter()
    token = current_meter.set(meter)
    try:
        yield meter
    finally:
        current_meter.reset(token)


def ask_llm(
    system_prompt: str,
    user_prompt: str,
    answer_shape: type[BaseModel],
    model: str = "",
    max_retries: int = 3,
) -> BaseModel:
    """Asks the model one question and returns its answer as an object of type answer_shape.

    model: another Groq model for this call (empty = LLM_MODEL).
    max_retries: how often to retry when Groq is busy or the free per-minute limit is reached.
    """
    name = model or settings.llm_model
    meter = current_meter.get()
    # Only inside measure_usage(): the meter is told about the answer. Otherwise nothing changes.
    config = {"callbacks": [meter]} if meter is not None else None
    try:
        chat = ChatGroq(
            model=name,
            api_key=settings.groq_api_key,
            temperature=0,  # always the most likely answer, so results are repeatable
            timeout=60,     # seconds; a hung call cannot freeze the app
            max_retries=max_retries,  # retries with growing waits when Groq is busy or rate-limited
            # gpt-oss models "think" before answering; low keeps that short, which saves tokens
            reasoning_effort="low" if name.startswith("openai/gpt-oss") else None,
            model_kwargs={"seed": 42},  # same seed every call, so repeated questions get the same answer more often (B2)
        )
        structured_model = chat.with_structured_output(answer_shape, method="json_schema")
        answer = structured_model.invoke(
            [("system", system_prompt), ("human", user_prompt)], config=config
        )
    except Exception as error:
        why, message = reason_for(error)
        log.warning(
            "llm call failed",
            extra={"event": "llm_error", "error_type": type(error).__name__, "why": why, "model": name},
        )
        log.warning("llm call failed: %s (%s) %s", name, why, str(error)[:300])
        raise LLMUnavailable(message) from error

    if answer is None:
        raise LLMUnavailable(
            "The AI service returned an empty answer. Please try again."
        )
    return answer
