from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str

    jwt_secret: str
    jwt_minutes: int = 480
    seed_interviewer_email: str
    seed_interviewer_password: str

    groq_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"

    careers_email: str = "careers@talentsight.local"

    livekit_api_key: str = ""
    livekit_api_secret: str = ""

       # Speech to text (AssemblyAI streaming)
    assemblyai_api_key: str = ""
    stt_model: str = "universal-3-6-pro"

settings = Settings()
