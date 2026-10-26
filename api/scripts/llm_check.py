from pydantic import BaseModel

from app.llm import LLMUnavailable, ask_llm

class Capital(BaseModel):
    country: str
    capital: str

try:
    answer = ask_llm(
        "Answer briefly.",
        "What is the capital of Bangladesh?",
        Capital,
    )
    print(f"OK: the model says the capital of {answer.country} is {answer.capital}.")
except LLMUnavailable as error:
    print(
        f"FAILED: {error} Check GROQ_API_KEY in .env, then run: docker compose up -d api"
    )