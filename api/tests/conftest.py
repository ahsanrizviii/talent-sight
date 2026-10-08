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
def no_real_google_form(monkeypatch):
    """autouse = applied to every test. Tests must never call the real Google Form or Drive."""
    monkeypatch.setattr(settings, "google_form_id", "")
    monkeypatch.setattr(settings, "google_form_url", "")
    monkeypatch.setattr(settings, "google_form_job_field", "")


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
