import os
import zlib

import psycopg
import pytest
from sqlalchemy.engine import make_url

real_url = make_url(os.environ["DATABASE_URL"])
test_url = real_url.set(database=f"{real_url.database}_test")

with psycopg.connect(real_url.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True) as conn:
    found = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_url.database,)).fetchone()
    if not found:
        conn.execute(f'CREATE DATABASE "{test_url.database}"')

os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)

from fastapi.testclient import TestClient  

from app import knowledge  
from app.db import engine  
from app.main import app
from app.models import Base  
from app.settings import settings  


def fake_embedding(text: str) -> list[float]:
    vector = [0.0] * 384
    vector[0] = 1.0  
    for word in text.lower().split():
        vector[zlib.crc32(word.encode()) % 384] += 1.0
    return vector


@pytest.fixture(autouse=True)
def no_real_embedding_model(monkeypatch):
    monkeypatch.setattr(knowledge, "embed_texts", lambda texts: [fake_embedding(t) for t in texts])
    monkeypatch.setattr(knowledge, "embed_question", fake_embedding)


@pytest.fixture(autouse=True)
def no_real_blog_posts(monkeypatch):
    monkeypatch.setattr(settings, "blogger_blog_id", "")

@pytest.fixture(autouse=True)
def cv_files_in_temp_folder(monkeypatch, tmp_path):
    
    monkeypatch.setattr(settings, "cv_upload_dir", str(tmp_path / "cv_uploads"))


@pytest.fixture(autouse=True)
def library_in_temp_folder(monkeypatch, tmp_path):
    """autouse = applied to every test. Tests never write to the real Library volume: each test gets an
    empty library folder. Until the API start-up sets it up, the documents that ship with the code are read."""
    monkeypatch.setattr(settings, "library_dir", str(tmp_path / "library"))

@pytest.fixture(autouse=True)
def no_real_google_form(monkeypatch):
    """autouse = applied to every test. Tests must never call the real Google Form or Drive."""
    monkeypatch.setattr(settings, "google_form_id", "")
    monkeypatch.setattr(settings, "google_form_url", "")
    monkeypatch.setattr(settings, "google_form_job_field", "")

@pytest.fixture(autouse=True)
def no_real_mail(monkeypatch):
    """autouse = applied to every test. Tests must never send a real e-mail."""
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_password", "")
    monkeypatch.setattr(settings, "mail_from", "")
    monkeypatch.setattr(settings, "google_calendar_id", "")  # tests must never touch a real calendar
    monkeypatch.setattr(settings, "gmail_user", "")
    monkeypatch.setattr(settings, "gmail_app_password", "")


@pytest.fixture(autouse=True)
def no_real_holiday_calendar(monkeypatch, tmp_path):
    """autouse = applied to every test. Tests must never read the real calendar PDF at start-up
    (that would run OCR and call the AI): the holiday folder is an empty folder."""
    from app import holiday_calendar, main

    folder = tmp_path / "holidays"
    folder.mkdir()
    monkeypatch.setattr(holiday_calendar, "HOLIDAY_FOLDER", folder)
    # The start-up reading runs in a background thread; in tests it is switched off, so it can never
    # race a test that reads the folder itself. Tests call load_holiday_calendars() directly.
    monkeypatch.setattr(main, "load_holiday_calendars", lambda force=False: [])


@pytest.fixture(autouse=True)
def no_real_mail_writer(monkeypatch):
    """autouse = applied to every test. Tests must never call the real AI to write an e-mail:
    the AI is "down", so e-mails use the fixed wording. Tests of the AI wording fake it themselves."""
    from app import mail_writer
    from app.llm import LLMUnavailable

    def down(*args, **kwargs):
        raise LLMUnavailable("The AI service is not available right now. Please try again.")

    monkeypatch.setattr(mail_writer, "ask_llm", down)
    monkeypatch.setattr(settings, "groq_api_key", "test-key")


@pytest.fixture(autouse=True)
def no_real_speech_service(monkeypatch):
    """autouse = applied to every test. Tests must never call the real speech service (AssemblyAI)."""
    monkeypatch.setattr(settings, "assemblyai_api_key", "")


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as test_client:  
        yield test_client


@pytest.fixture
def auth_headers(client):
    response = client.post(
        "/api/auth/login",
        json={"email": settings.seed_interviewer_email, "password": settings.seed_interviewer_password},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
