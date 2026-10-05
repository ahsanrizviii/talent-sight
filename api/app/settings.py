from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str

    jwt_secret: str
    jwt_minutes: int = 480
    seed_interviewer_email: str
    seed_interviewer_password: str

    groq_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"

    careers_email: str = "careers@talentsight.local"

    livekit_api_key: str = ""
    livekit_api_secret: str = ""

settings = Settings()
