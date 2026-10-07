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
) -> BaseModel:
    
    try:
        model = ChatGroq(
            model=settings.llm_model,
            api_key=settings.groq_api_key,
            temperature=0,   
            timeout=60,      
            max_retries=3,   
        )
        structured_model = model.with_structured_output(answer_shape, method="json_schema")
        answer = structured_model.invoke(
            [("system", system_prompt), ("human", user_prompt)]
        )
    except Exception as error:
        log.warning(
            "llm call failed",
            extra={"event": "llm_error", "error_type": type(error).__name__},
        )
        raise LLMUnavailable("The AI service is not available right now. Please try again.") from error

    if answer is None:
        raise LLMUnavailable("The AI service returned an empty answer. Please try again.")

    return answer