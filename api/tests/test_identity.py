"""Tests for consent, face templates and the photo-ID check (Module 13, F7).

The face models are replaced by a fake that maps a picture name to a template, so no model file is needed.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import face, identity
from app.db import SessionLocal
from app.face import Face, FaceError
from app.models import Candidate, FaceTemplate, InterviewSession, JobProfile
from app.settings import settings

FACES = {
    "maya": Face(template=[1.0, 0.0, 0.0], turn=0.0),
    "maya-left": Face(template=[0.97, 0.2, 0.0], turn=0.4),
    "maya-right": Face(template=[0.97, 0.2, 0.0], turn=-0.4),
    "other": Face(template=[0.0, 1.0, 0.0], turn=0.0),
}


def fake_read_face(image: str) -> Face:
    if image in FACES:
        return FACES[image]
    raise FaceError("No face was found. Look at the camera in good light.")


@pytest.fixture(autouse=True)
def fake_faces(monkeypatch):
    monkeypatch.setattr(face, "read_face", fake_read_face)


def live_interview() -> tuple[int, str, int]:
    """A live interview with an open invite link. Returns (interview id, invite token, candidate id)."""
    with SessionLocal() as db:
        job = JobProfile(title="Backend Developer", required_skills=["Python"])
        db.add(job)
        db.flush()
        person = Candidate(job_profile_id=job.id, name="Maya Rahman", cv_filename="cv.pdf", status="screened", profile={})
        db.add(person)
        db.flush()
        now = datetime.now(timezone.utc)
        session = InterviewSession(
            candidate_id=person.id, scheduled_at=now, invite_token=f"token-{person.id}",
            invite_expires_at=now + timedelta(hours=1), status="live", started_at=now,
        )
        db.add(session)
        db.commit()
        return session.id, session.invite_token, person.id


def consent(client, token: str, answer: bool = True):
    return client.post(f"/api/invite/{token}/identity/consent", json={"consent": answer})


def frame(client, token: str, image: str = "maya"):
    return client.post(f"/api/invite/{token}/identity/frame", json={"image": image})


def stored(candidate_id: int) -> list[FaceTemplate]:
    with SessionLocal() as db:
        return list(db.scalars(select(FaceTemplate).where(FaceTemplate.candidate_id == candidate_id).order_by(FaceTemplate.slot)))


def test_with_consent_three_templates_are_kept_as_numbers_only(client):
    _, token, candidate_id = live_interview()
    assert consent(client, token).json() == {"consent": True, "templates": 0, "retention_days": settings.biometric_retention_days}
    for _ in range(4):
        frame(client, token)
    rows = stored(candidate_id)
    assert [row.slot for row in rows] == [1, 2, 3]  # a fourth frame is ignored
    assert rows[0].vector == [1.0, 0.0, 0.0]
    days_kept = (rows[0].expires_at - datetime.now(timezone.utc)).days
    assert settings.biometric_retention_days - 1 <= days_kept <= settings.biometric_retention_days


def test_without_consent_nothing_is_captured(client):
    _, token, candidate_id = live_interview()
    assert frame(client, token).status_code == 403
    consent(client, token, answer=False)
    assert frame(client, token).status_code == 403
    assert stored(candidate_id) == []


def test_saying_no_later_deletes_what_was_made(client):
    _, token, candidate_id = live_interview()
    consent(client, token)
    frame(client, token)
    consent(client, token, answer=False)
    assert stored(candidate_id) == []


def test_a_frame_without_a_face_gets_a_clear_message(client):
    _, token, _ = live_interview()
    consent(client, token)
    response = frame(client, token, image="blank")
    assert response.status_code == 422 and "No face was found" in response.json()["detail"]


def test_the_interviewer_records_the_photo_id_check(client, auth_headers):
    session_id, _, _ = live_interview()
    before = client.get(f"/api/interviews/{session_id}/identity", headers=auth_headers).json()
    assert before["state"] == "not_checked" and before["consent"] is None
    body = {"id_checked": True, "name_matches": True}
    after = client.post(f"/api/interviews/{session_id}/identity/id-check", headers=auth_headers, json=body).json()
    assert after["state"] == "confirmed" and after["checked_by"] == settings.seed_interviewer_email
    body = {"id_checked": True, "name_matches": False}
    mismatch = client.post(f"/api/interviews/{session_id}/identity/id-check", headers=auth_headers, json=body).json()
    assert mismatch["state"] == "name_mismatch"


def test_the_name_cannot_match_when_no_id_was_seen(client, auth_headers):
    session_id, _, _ = live_interview()
    body = {"id_checked": False, "name_matches": True}
    state = client.post(f"/api/interviews/{session_id}/identity/id-check", headers=auth_headers, json=body).json()
    assert state["state"] == "not_checked" and state["name_matches"] is False


def test_the_candidate_cannot_read_the_interviewer_view(client):
    session_id, token, _ = live_interview()
    assert client.get(f"/api/interviews/{session_id}/identity").status_code == 401
    assert client.get(f"/api/interviews/{session_id}/identity", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_an_interviewer_cannot_use_the_candidate_link(client, auth_headers):
    _, token, _ = live_interview()
    assert client.post(f"/api/invite/{token}/identity/consent", headers=auth_headers, json={"consent": True}).status_code == 403


def test_templates_past_the_retention_period_are_deleted(client):
    _, token, candidate_id = live_interview()
    consent(client, token)
    frame(client, token)
    with SessionLocal() as db:
        row = db.scalar(select(FaceTemplate).where(FaceTemplate.candidate_id == candidate_id))
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        assert identity.purge_expired(db) == 1
    assert stored(candidate_id) == []


def test_face_data_can_be_deleted_on_request(client, auth_headers):
    _, token, candidate_id = live_interview()
    consent(client, token)
    frame(client, token)
    assert client.delete(f"/api/candidates/{candidate_id}/face-templates", headers=auth_headers).status_code == 204
    assert stored(candidate_id) == []
    assert client.delete("/api/candidates/9999/face-templates", headers=auth_headers).status_code == 404


def test_similarity_and_head_turn_are_plain_maths():
    assert face.similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert face.similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    # eyes at x 100 and 140, nose at 130: a quarter of an eye width off the middle
    landmarks = [0, 0, 0, 0, 100, 50, 140, 50, 130, 70, 0, 0, 0, 0, 0.9]
    assert face.turn_of(landmarks) == pytest.approx(0.25 * face.LEFT_SIGN)