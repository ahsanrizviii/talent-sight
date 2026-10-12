"""Tests for the invite link and e-mail (Task 7.1.3). A fake mail server replaces Mailpit."""

import smtplib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import invite_mail
from app.db import SessionLocal
from app.models import Candidate, InterviewSession
from app.settings import settings

from tests.test_interviews import fake_video_server, in_hours, make_candidate, schedule, stored_session  # noqa: F401


class FakeSMTP:
    """Collects the messages instead of sending them."""

    sent: list = []
    fail = False

    def __init__(self, host, port, timeout=None):
        if FakeSMTP.fail:
            raise ConnectionRefusedError("mail server is down")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def send_message(self, message):
        FakeSMTP.sent.append(message)


@pytest.fixture(autouse=True)
def fake_mail_server(monkeypatch):
    FakeSMTP.sent, FakeSMTP.fail = [], False
    monkeypatch.setattr(settings, "smtp_host", "mailpit")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)


def set_email(candidate_id: int, address: str) -> None:
    with SessionLocal() as db:
        db.get(Candidate, candidate_id).email = address
        db.commit()


def test_scheduling_sends_one_email_with_the_private_link(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    assert session["email_sent"] is True
    assert len(FakeSMTP.sent) == 1
    message = FakeSMTP.sent[0]
    token = stored_session(session["id"]).invite_token
    link = f"{settings.public_base_url}/join/{token}"

    assert message["To"] == "maya@example.com"
    assert "Backend Developer" in message["Subject"]
    text = message.get_body(("plain",)).get_content()
    assert link in text
    assert "Hello Maya Rahman," in text
    assert session["invite_url"] == link


def test_the_email_contains_no_scores_or_other_candidates(client, auth_headers):
    schedule(client, auth_headers, make_candidate(name="Maya Rahman"))
    text = FakeSMTP.sent[0].as_string().lower()
    for secret in ("score", "rank", "overall", "excluded", "unmet"):
        assert secret not in text


def test_each_candidate_gets_a_different_link(client, auth_headers):
    first = schedule(client, auth_headers, make_candidate()).json()
    second = schedule(client, auth_headers, make_candidate(name="Other Person")).json()
    assert first["invite_url"] != second["invite_url"]


def test_a_candidate_without_an_email_address_still_gets_a_session(client, auth_headers):
    candidate_id = make_candidate()
    set_email(candidate_id, "")
    response = schedule(client, auth_headers, candidate_id)
    assert response.status_code == 201
    body = response.json()
    assert body["email_sent"] is False
    assert "no e-mail address" in body["email_error"]
    assert body["invite_url"]  # the link can still be copied
    assert FakeSMTP.sent == []


def test_a_wrong_looking_address_is_not_used(client, auth_headers):
    candidate_id = make_candidate()
    set_email(candidate_id, "not an address")
    body = schedule(client, auth_headers, candidate_id).json()
    assert body["email_sent"] is False
    assert "looks wrong" in body["email_error"]


def test_a_mail_server_failure_never_blocks_the_session(client, auth_headers):
    FakeSMTP.fail = True
    response = schedule(client, auth_headers, make_candidate())
    assert response.status_code == 201
    body = response.json()
    assert body["email_sent"] is False
    assert "could not be sent" in body["email_error"]
    assert "mail server is down" not in str(body)  # the technical reason stays in the log
    assert stored_session(body["id"]) is not None


def test_rescheduling_sends_an_updated_email_with_the_same_link(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    moved = client.patch(f"/api/interviews/{session['id']}", json={"scheduled_at": in_hours(6)}, headers=auth_headers).json()
    assert moved["email_sent"] is True
    assert moved["invite_url"] == session["invite_url"]
    assert FakeSMTP.sent[1]["Subject"].startswith("Interview rescheduled")


def test_the_email_can_be_sent_again_until_the_interview_starts(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    again = client.post(f"/api/interviews/{session['id']}/invite", headers=auth_headers)
    assert again.status_code == 200 and again.json()["email_sent"] is True
    assert len(FakeSMTP.sent) == 2
    client.post(f"/api/interviews/{session['id']}/end", headers=auth_headers)
    assert client.post(f"/api/interviews/{session['id']}/invite", headers=auth_headers).status_code == 409


def test_the_time_in_the_email_uses_the_configured_zone(monkeypatch):
    monkeypatch.setattr(settings, "interview_utc_offset_minutes", 360)
    moment = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)
    assert invite_mail.when_text(moment) == "Monday, 12 October 2026 at 15:30 (UTC+06:00)"


def test_expired_and_unknown_links_are_refused(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    token = stored_session(session["id"]).invite_token
    assert client.get(f"/api/invite/{token}").status_code == 200
    with SessionLocal() as db:
        row = db.scalar(select(InterviewSession).where(InterviewSession.id == session["id"]))
        row.invite_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert client.get(f"/api/invite/{token}").status_code == 404
    assert client.get("/api/invite/made-up-token").status_code == 404