from datetime import datetime, timedelta, timezone

import jwt

from app.db import SessionLocal
from app.models import Candidate, InterviewSession, JobProfile
from app.settings import settings

def test_seeded_interviewer_can_log_in(client, auth_headers):
    response = client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == settings.seed_interviewer_email.lower()

def test_wrong_password_is_rejected(client):
    response = client.post(
        "/api/auth/login",
        json={
            "email": settings.seed_interviewer_email,
            "password": "wrong",
        },
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Wrong e-mail or password."}

def test_interviewer_pages_need_a_token(client):
    assert client.get("/api/auth/me").status_code == 401

def test_a_forged_token_is_rejected(client):
    fake = jwt.encode(
        {"sub": "1", "role": "interviewer"},
        "not-our-secret-but-longenough-1234567",
        algorithm="HS256",
    )
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {fake}"},
    )
    assert response.status_code == 401

def make_session(expires_in_hours: int) -> str:

    with SessionLocal() as db:
        job = JobProfile(title="Backend Developer")
        db.add(job)
        db.flush()  

        candidate = Candidate(
            job_profile_id=job.id,
            name="Test Candidate",
            cv_filename="cv.pdf",
        )
        db.add(candidate)
        db.flush()

        now = datetime.now(timezone.utc)
        db.add(
            InterviewSession(
                candidate_id=candidate.id,
                scheduled_at=now + timedelta(hours=1),
                invite_token="test-invite-token",
                invite_expires_at=now + timedelta(hours=expires_in_hours),
            )
        )
        db.commit()

    return "test-invite-token"

def test_candidate_invite_shows_only_safe_fields(client):
    token = make_session(expires_in_hours=24)
    response = client.get(f"/api/invite/{token}")
    assert response.status_code == 200
    assert set(response.json()) == {"session_id", "scheduled_at", "opens_at", "status", "candidate_name", "job_title"}

def test_invite_token_cannot_open_interviewer_pages(client):
    token = make_session(expires_in_hours=24)
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401

def test_expired_invite_is_rejected(client):
    token = make_session(expires_in_hours=-1)
    assert client.get(f"/api/invite/{token}").status_code == 404