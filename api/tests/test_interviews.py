"""Tests for the interview session API (Task 7.1.2). No real LiveKit server is used."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select

from app import livekit_service
from app.db import SessionLocal
from app.models import Candidate, InterviewSession, JobProfile, SessionParticipant
from app.settings import settings

SECRET = "test-secret-that-is-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def fake_video_server(monkeypatch):
    """Rooms are not really created; tokens are real but signed with a test key."""
    monkeypatch.setattr(settings, "livekit_api_key", "test-key")
    monkeypatch.setattr(settings, "livekit_api_secret", SECRET)
    monkeypatch.setattr(livekit_service, "ensure_room", lambda session_id: None)
    monkeypatch.setattr(livekit_service, "close_room", lambda session_id: None)


def in_hours(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def make_candidate(status: str = "screened", name: str = "Maya Rahman") -> int:
    with SessionLocal() as db:
        job = JobProfile(title="Backend Developer")
        db.add(job)
        db.flush()
        candidate = Candidate(job_profile_id=job.id, name=name, email="maya@example.com", cv_filename="cv.pdf", status=status)
        db.add(candidate)
        db.commit()
        return candidate.id


def schedule(client, headers, candidate_id: int, when: str | None = None):
    return client.post(
        f"/api/candidates/{candidate_id}/interview",
        json={"scheduled_at": when or in_hours(2)},
        headers=headers,
    )


def stored_session(session_id: int) -> InterviewSession:
    with SessionLocal() as db:
        return db.scalar(select(InterviewSession).where(InterviewSession.id == session_id))


def test_a_screened_candidate_can_be_scheduled(client, auth_headers):
    response = schedule(client, auth_headers, make_candidate())
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "scheduled"
    assert body["candidate_name"] == "Maya Rahman"
    assert body["job_title"] == "Backend Developer"
    assert "invite_token" not in body  # the secret never travels in this answer
    assert len(stored_session(body["id"]).invite_token) >= 40


def test_only_screened_candidates_can_be_scheduled(client, auth_headers):
    for state in ("uploaded", "excluded", "failed"):
        assert schedule(client, auth_headers, make_candidate(state)).status_code == 409


def test_the_time_must_be_in_the_future_and_have_a_time_zone(client, auth_headers):
    candidate_id = make_candidate()
    assert schedule(client, auth_headers, candidate_id, in_hours(-1)).status_code == 422
    assert schedule(client, auth_headers, candidate_id, "2099-01-01T10:00:00").status_code == 422  # no time zone
    assert schedule(client, auth_headers, candidate_id, in_hours(24 * 200)).status_code == 422  # too far away


def test_one_open_interview_per_candidate(client, auth_headers):
    candidate_id = make_candidate()
    first = schedule(client, auth_headers, candidate_id).json()
    assert schedule(client, auth_headers, candidate_id).status_code == 409
    client.post(f"/api/interviews/{first['id']}/end", headers=auth_headers)
    assert schedule(client, auth_headers, candidate_id).status_code == 201  # a new one is fine after the end


def test_every_candidate_gets_a_different_token(client, auth_headers):
    first = schedule(client, auth_headers, make_candidate()).json()
    second = schedule(client, auth_headers, make_candidate(name="Other Person")).json()
    assert stored_session(first["id"]).invite_token != stored_session(second["id"]).invite_token


def test_rescheduling_moves_the_time_and_keeps_the_link(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    token_before = stored_session(session["id"]).invite_token
    later = in_hours(5)
    moved = client.patch(f"/api/interviews/{session['id']}", json={"scheduled_at": later}, headers=auth_headers)
    assert moved.status_code == 200
    assert datetime.fromisoformat(moved.json()["scheduled_at"]) == datetime.fromisoformat(later)
    assert stored_session(session["id"]).invite_token == token_before


def test_latest_interview_of_a_candidate(client, auth_headers):
    candidate_id = make_candidate()
    assert client.get(f"/api/candidates/{candidate_id}/interview", headers=auth_headers).json() is None
    session = schedule(client, auth_headers, candidate_id).json()
    assert client.get(f"/api/candidates/{candidate_id}/interview", headers=auth_headers).json()["id"] == session["id"]


def test_interviewer_join_starts_the_interview(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    joined = client.post(f"/api/interviews/{session['id']}/join", headers=auth_headers)
    assert joined.status_code == 200
    body = joined.json()
    assert body["room"] == f"interview-{session['id']}"
    assert body["livekit_url"] == settings.livekit_url
    claims = jwt.decode(body["token"], SECRET, algorithms=["HS256"])
    assert claims["video"]["room"] == body["room"]
    assert claims["sub"].startswith("interviewer-")

    after = client.get(f"/api/interviews/{session['id']}", headers=auth_headers).json()
    assert after["status"] == "live"
    assert after["started_at"] is not None


def test_ending_closes_the_interview_for_everyone(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    client.post(f"/api/interviews/{session['id']}/join", headers=auth_headers)
    ended = client.post(f"/api/interviews/{session['id']}/end", headers=auth_headers).json()
    assert ended["status"] == "ended"
    assert ended["ended_at"] is not None
    assert client.post(f"/api/interviews/{session['id']}/join", headers=auth_headers).status_code == 409
    token = stored_session(session["id"]).invite_token
    assert client.get(f"/api/invite/{token}").status_code == 404  # the candidate's link stops working
    assert client.post(f"/api/invite/{token}/join").status_code == 404


def test_candidate_cannot_join_too_early(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate(), in_hours(3)).json()
    token = stored_session(session["id"]).invite_token
    early = client.post(f"/api/invite/{token}/join")
    assert early.status_code == 403
    assert "too early" in early.json()["detail"]


def test_candidate_joins_with_the_link_only(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate(), in_hours(0.1)).json()  # starts in 6 minutes
    token = stored_session(session["id"]).invite_token
    joined = client.post(f"/api/invite/{token}/join")  # no login header
    assert joined.status_code == 200
    claims = jwt.decode(joined.json()["token"], SECRET, algorithms=["HS256"])
    assert claims["video"]["room"] == f"interview-{session['id']}"
    assert claims["sub"].startswith("candidate-")
    assert client.post("/api/invite/not-a-real-token/join").status_code == 404


def test_an_interviewer_cannot_use_the_candidate_link(client, auth_headers):
    """Whoever uses the link enters as the candidate, so a signed-in interviewer is refused."""
    session = schedule(client, auth_headers, make_candidate(), in_hours(0.1)).json()
    token = stored_session(session["id"]).invite_token
    for response in (
        client.get(f"/api/invite/{token}", headers=auth_headers),
        client.post(f"/api/invite/{token}/join", headers=auth_headers),
        client.post(f"/api/invite/{token}/leave", headers=auth_headers),
    ):
        assert response.status_code == 403
        assert "only for the candidate" in response.json()["detail"]
    with SessionLocal() as db:  # nobody was recorded as joining or leaving
        assert db.scalar(select(SessionParticipant).where(SessionParticipant.session_id == session["id"])) is None


def test_an_old_or_broken_login_does_not_block_the_candidate(client, auth_headers):
    """A candidate's browser may still hold an expired login from somewhere. That must not lock them out."""
    session = schedule(client, auth_headers, make_candidate(), in_hours(0.1)).json()
    token = stored_session(session["id"]).invite_token
    junk = {"Authorization": "Bearer not-a-real-login"}
    assert client.get(f"/api/invite/{token}", headers=junk).status_code == 200
    assert client.post(f"/api/invite/{token}/join", headers=junk).status_code == 200


def test_video_server_down_gives_a_clear_message(client, auth_headers, monkeypatch):
    def broken(session_id):
        raise livekit_service.LiveKitError("The video server is not reachable right now. Please try again in a moment.")

    monkeypatch.setattr(livekit_service, "ensure_room", broken)
    session = schedule(client, auth_headers, make_candidate()).json()
    response = client.post(f"/api/interviews/{session['id']}/join", headers=auth_headers)
    assert response.status_code == 503
    assert client.get(f"/api/interviews/{session['id']}", headers=auth_headers).json()["status"] == "scheduled"


def test_interviewer_endpoints_need_login(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    assert client.post(f"/api/candidates/1/interview", json={"scheduled_at": in_hours(2)}).status_code == 401
    assert client.get(f"/api/interviews/{session['id']}").status_code == 401
    assert client.post(f"/api/interviews/{session['id']}/join").status_code == 401
    assert client.post(f"/api/interviews/{session['id']}/end").status_code == 401



def test_invite_info_tells_the_candidate_only_what_they_need(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate(), in_hours(3)).json()
    token = stored_session(session["id"]).invite_token
    info = client.get(f"/api/invite/{token}").json()
    assert info["candidate_name"] == "Maya Rahman"
    assert info["job_title"] == "Backend Developer"
    opens = datetime.fromisoformat(info["opens_at"])
    starts = datetime.fromisoformat(info["scheduled_at"])
    assert starts - opens == timedelta(minutes=settings.join_early_minutes)
    for hidden in ("score", "overall", "rank", "email", "invite_token", "verdicts"):
        assert hidden not in str(info).lower()



def test_the_candidate_profile_is_for_interviewers_only(client, auth_headers):
    """The side panel reads this endpoint (Task 7.3.2). A candidate has no login, so it must refuse them."""
    candidate_id = make_candidate()
    session = schedule(client, auth_headers, candidate_id, in_hours(0.1)).json()
    token = stored_session(session["id"]).invite_token
    assert client.get(f"/api/candidates/{candidate_id}").status_code == 401  # no login
    assert client.get(f"/api/candidates/{candidate_id}", headers={"Authorization": f"Bearer {token}"}).status_code == 401  # invite token is not a login
    assert client.get(f"/api/candidates/{candidate_id}", headers=auth_headers).status_code == 200




def test_every_interview_of_a_candidate_stays_listed(client, auth_headers):
    """Booking a new interview keeps the earlier one on record (oldest first)."""
    candidate_id = make_candidate()
    assert client.get(f"/api/candidates/{candidate_id}/interviews", headers=auth_headers).json() == []
    first = schedule(client, auth_headers, candidate_id).json()
    client.post(f"/api/interviews/{first['id']}/end", headers=auth_headers)
    second = schedule(client, auth_headers, candidate_id).json()

    listed = client.get(f"/api/candidates/{candidate_id}/interviews", headers=auth_headers).json()
    assert [item["id"] for item in listed] == [first["id"], second["id"]]
    assert [item["status"] for item in listed] == ["ended", "scheduled"]
    assert client.get(f"/api/candidates/{candidate_id}/interviews").status_code == 401  # interviewers only