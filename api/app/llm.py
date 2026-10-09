"""The LLM Client Wrapper: the only place in the code that talks to the language model.

Every agent calls ask_llm(). If the model is down, slow or answers in the wrong
shape, ask_llm() raises LLMUnavailable, and the agent turns that into a clear
error state instead of crashing (N6).
"""
import logging

from langchain_groq import ChatGroq
from pydantic import BaseModel

from app.settings import settings

log = logging.getLogger("talentsight.llm")


class LLMUnavailable(Exception):
    """The language model could not give a usable answer."""


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
            [("system", system_prompt), ("human", user_prompt)]
        )
    except Exception as error:
        log.warning(
            "llm call failed",
            extra={"event": "llm_error", "error_type": type(error).__name__},
        )
        raise LLMUnavailable(
            "The AI service is not available right now. Please try again."
        ) from error

    if answer is None:
        raise LLMUnavailable(
            "The AI service returned an empty answer. Please try again."
        )
    return answer