"""Tests for session times and participants (Task 7.1.4)."""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import SessionParticipant

from tests.test_interviews import fake_video_server, in_hours, make_candidate, schedule, stored_session  # noqa: F401


def rows(session_id: int) -> list[SessionParticipant]:
    with SessionLocal() as db:
        return list(db.scalars(select(SessionParticipant).where(SessionParticipant.session_id == session_id).order_by(SessionParticipant.id)))


def start(client, headers) -> tuple[dict, str]:
    """A scheduled interview that opens in 6 minutes, and the candidate's token."""
    session = schedule(client, headers, make_candidate(), in_hours(0.1)).json()
    return session, stored_session(session["id"]).invite_token


def test_both_people_are_recorded_with_their_roles(client, auth_headers):
    session, token = start(client, auth_headers)
    client.post(f"/api/interviews/{session['id']}/join", headers=auth_headers)
    client.post(f"/api/invite/{token}/join")
    saved = rows(session["id"])
    assert [row.role for row in saved] == ["interviewer", "candidate"]
    assert all(row.joined_at is not None and row.left_at is None for row in saved)
    shown = client.get(f"/api/interviews/{session['id']}", headers=auth_headers).json()
    assert [p["role"] for p in shown["participants"]] == ["interviewer", "candidate"]


def test_a_page_refresh_does_not_add_a_second_row(client, auth_headers):
    session, token = start(client, auth_headers)
    for _ in range(3):
        client.post(f"/api/invite/{token}/join")
    assert len(rows(session["id"])) == 1


def test_leaving_sets_the_time_and_coming_back_adds_a_row(client, auth_headers):
    session, token = start(client, auth_headers)
    client.post(f"/api/invite/{token}/join")
    assert client.post(f"/api/invite/{token}/leave").status_code == 204
    assert rows(session["id"])[0].left_at is not None
    client.post(f"/api/invite/{token}/leave")  # twice is harmless
    client.post(f"/api/invite/{token}/join")
    assert len(rows(session["id"])) == 2


def test_the_interviewer_can_leave_without_ending_the_interview(client, auth_headers):
    session, _ = start(client, auth_headers)
    client.post(f"/api/interviews/{session['id']}/join", headers=auth_headers)
    assert client.post(f"/api/interviews/{session['id']}/leave", headers=auth_headers).status_code == 204
    assert rows(session["id"])[0].left_at is not None
    assert client.get(f"/api/interviews/{session['id']}", headers=auth_headers).json()["status"] == "live"


def test_ending_closes_everyone_and_gives_the_duration(client, auth_headers):
    session, token = start(client, auth_headers)
    client.post(f"/api/interviews/{session['id']}/join", headers=auth_headers)
    client.post(f"/api/invite/{token}/join")
    before = client.get(f"/api/interviews/{session['id']}", headers=auth_headers).json()
    assert before["duration_seconds"] is None

    ended = client.post(f"/api/interviews/{session['id']}/end", headers=auth_headers).json()
    assert ended["status"] == "ended"
    assert ended["duration_seconds"] is not None and ended["duration_seconds"] >= 0
    assert all(row.left_at is not None for row in rows(session["id"]))
    assert all(p["left_at"] is not None for p in ended["participants"])


def test_an_interview_that_never_started_has_no_duration(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    ended = client.post(f"/api/interviews/{session['id']}/end", headers=auth_headers).json()
    assert ended["duration_seconds"] is None
    assert ended["participants"] == []


def test_only_times_and_roles_are_stored_never_media():
    """Q&A 7: no raw audio or video. If someone adds a media column, this test says so."""
    assert {column.name for column in SessionParticipant.__table__.columns} == {"id", "session_id", "role", "identity", "joined_at", "left_at"}