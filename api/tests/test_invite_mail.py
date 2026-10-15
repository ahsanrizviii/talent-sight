"""Tests for the invite link and e-mail (Task 7.1.3). A fake mail server stands in for the real one."""

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
    """Collects the messages instead of sending them, and remembers which server they went to."""

    sent: list = []
    servers: list = []
    logins: list = []
    tls: list = []
    fail = False
    refuse_login = False

    def __init__(self, host, port, timeout=None, context=None):
        if FakeSMTP.fail:
            raise ConnectionRefusedError("mail server is down")
        FakeSMTP.servers.append((host, port))

    def starttls(self, context=None):
        FakeSMTP.tls.append("starttls")

    def login(self, user, password):
        if FakeSMTP.refuse_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad password")
        FakeSMTP.logins.append(user)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def send_message(self, message):
        FakeSMTP.sent.append(message)


@pytest.fixture(autouse=True)
def fake_mail_server(monkeypatch):
    FakeSMTP.sent, FakeSMTP.servers, FakeSMTP.logins, FakeSMTP.tls = [], [], [], []
    FakeSMTP.fail, FakeSMTP.refuse_login = False, False
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_user", "hiring@example.com")
    monkeypatch.setattr(settings, "smtp_password", "app-password")
    monkeypatch.setattr(settings, "company_name", "BJIT")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)


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
    assert "Dear Maya Rahman," in text
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


# ---------- One real mail server for every address ----------


def test_every_address_goes_to_the_company_mail_server(client, auth_headers):
    candidate_id = make_candidate()
    set_email(candidate_id, "maya.rahman@outlook.com")  # not Gmail: it must still be really sent
    assert schedule(client, auth_headers, candidate_id).json()["email_sent"] is True
    assert FakeSMTP.servers == [("smtp.example.com", 587)]
    assert FakeSMTP.tls == ["starttls"]  # encrypted before the password is sent
    assert FakeSMTP.logins == ["hiring@example.com"]


def test_the_email_comes_from_the_company(client, auth_headers):
    schedule(client, auth_headers, make_candidate())
    message = FakeSMTP.sent[0]
    assert message["From"] == "BJIT Hiring <hiring@example.com>"
    assert message["Subject"] == "Invitation for Interview at BJIT: Backend Developer"
    assert "The BJIT hiring team" in message.get_body(("plain",)).get_content()


def test_mail_from_can_be_chosen(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "mail_from", "BJIT Careers <careers@example.com>")
    schedule(client, auth_headers, make_candidate())
    assert FakeSMTP.sent[0]["From"] == "BJIT Careers <careers@example.com>"


def test_port_465_is_encrypted_from_the_start(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "smtp_port", 465)
    schedule(client, auth_headers, make_candidate())
    assert FakeSMTP.servers == [("smtp.example.com", 465)]
    assert FakeSMTP.tls == []  # SSL from the first byte: no STARTTLS step


def test_an_older_env_with_only_gmail_settings_still_sends(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "gmail_user", "talentsight.demo@gmail.com")
    monkeypatch.setattr(settings, "gmail_app_password", "test-app-password")
    assert schedule(client, auth_headers, make_candidate()).json()["email_sent"] is True
    assert FakeSMTP.servers == [("smtp.gmail.com", 587)]
    assert FakeSMTP.logins == ["talentsight.demo@gmail.com"]


def test_without_a_mail_server_the_link_is_copied_by_hand(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    body = schedule(client, auth_headers, make_candidate()).json()
    assert body["email_sent"] is False
    assert "not set up" in body["email_error"]
    assert body["invite_url"]
    assert FakeSMTP.sent == []


def test_a_wrong_password_says_so(client, auth_headers):
    FakeSMTP.refuse_login = True
    body = schedule(client, auth_headers, make_candidate()).json()
    assert body["email_sent"] is False
    assert "refused the login" in body["email_error"]
    assert "bad password" not in str(body)


# ---------- The candidate's own calendar invitation ----------


def calendar_parts(message):
    return [part for part in message.walk() if part.get_content_type() == "text/calendar"]


def invite_text(message) -> str:
    return calendar_parts(message)[0].get_content()


def unfolded(text: str) -> list[str]:
    """The calendar's lines with continuation lines joined back on, the way a calendar app reads them."""
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith(" ") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def test_the_email_carries_a_calendar_invitation_for_the_candidate(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    message = FakeSMTP.sent[0]
    parts = calendar_parts(message)
    assert len(parts) == 1  # the body Gmail and Outlook read to show their own "add to calendar" card
    assert parts[0].get_param("method") == "REQUEST"
    assert [part.get_filename() for part in message.iter_attachments()] == ["invite.ics"]  # for apps that read attachments

    text = invite_text(message)
    token = stored_session(session["id"]).invite_token
    assert text.startswith("BEGIN:VCALENDAR")
    assert "METHOD:REQUEST" in text and "STATUS:CONFIRMED" in text
    assert f"{settings.public_base_url}/join/{token}" in "".join(unfolded(text))  # their own private link
    flat = "".join(unfolded(text))
    assert "ATTENDEE;CN=Maya Rahman" in flat and "mailto:maya@example.com" in flat
    assert "DTSTART:" in text and "DTEND:" in text and "BEGIN:VALARM" in text


def test_calendar_lines_never_run_past_75_bytes(client, auth_headers):
    schedule(client, auth_headers, make_candidate())
    text = invite_text(FakeSMTP.sent[0])
    assert all(len(line.encode("utf-8")) <= 75 for line in text.splitlines())
    assert any(line.startswith("DESCRIPTION:") and "Join:" in line for line in unfolded(text))  # nothing lost by folding


def test_a_moved_interview_replaces_the_earlier_calendar_entry(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    client.patch(f"/api/interviews/{session['id']}", json={"scheduled_at": in_hours(6)}, headers=auth_headers)
    first, second = (unfolded(invite_text(FakeSMTP.sent[i])) for i in (0, 1))
    field = lambda lines, name: next(line for line in lines if line.startswith(name + ":"))  # noqa: E731
    assert field(first, "UID") == field(second, "UID")  # the same entry...
    assert int(field(second, "SEQUENCE")[9:]) >= int(field(first, "SEQUENCE")[9:])  # ...marked as the newer version
    assert field(first, "DTSTART") != field(second, "DTSTART")  # at its new time


def test_cancelling_tells_the_candidate_and_removes_their_calendar_entry(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    body = client.post(f"/api/interviews/{session['id']}/end", headers=auth_headers).json()
    assert body["email_sent"] is True
    cancel = FakeSMTP.sent[1]
    assert cancel["Subject"].startswith("Interview cancelled")
    assert calendar_parts(cancel)[0].get_param("method") == "CANCEL"
    text = invite_text(cancel)
    assert "METHOD:CANCEL" in text and "STATUS:CANCELLED" in text
    assert "BEGIN:VALARM" not in text


def test_ending_an_interview_that_ran_sends_no_cancellation(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    client.post(f"/api/interviews/{session['id']}/join", headers=auth_headers)  # it starts: status live
    client.post(f"/api/interviews/{session['id']}/end", headers=auth_headers)
    assert len(FakeSMTP.sent) == 1  # only the original invitation


def test_the_calendar_invitation_holds_no_scores_either(client, auth_headers):
    schedule(client, auth_headers, make_candidate())
    text = invite_text(FakeSMTP.sent[0]).lower()
    for secret in ("score", "rank", "overall", "excluded", "unmet"):
        assert secret not in text


# ---------- The company on the Settings page (name, sender, contact) ----------


def save_company(client, headers, **fields):
    body = {"company_name": "WellDev", "sender_name": "", "contact_name": "", "contact_email": "", **fields}
    return client.put("/api/company", json=body, headers=headers)


def test_the_company_from_settings_is_used_in_the_email(client, auth_headers):
    assert save_company(client, auth_headers, sender_name="WellDev Talent Team").status_code == 200
    schedule(client, auth_headers, make_candidate())
    message = FakeSMTP.sent[0]
    assert message["Subject"] == "Invitation for Interview at WellDev: Backend Developer"
    assert message["From"] == "WellDev Talent Team <hiring@example.com>"  # the name changes, the mailbox does not
    assert "The WellDev hiring team" in message.get_body(("plain",)).get_content()


def test_replies_go_to_the_contact_person(client, auth_headers):
    save_company(client, auth_headers, contact_name="Nadia Islam", contact_email="nadia@welldev.com")
    schedule(client, auth_headers, make_candidate())
    message = FakeSMTP.sent[0]
    assert message["Reply-To"] == "Nadia Islam <nadia@welldev.com>"
    assert "contact Nadia Islam at nadia@welldev.com" in message.get_body(("plain",)).get_content()


def test_without_a_contact_there_is_no_reply_to(client, auth_headers):
    schedule(client, auth_headers, make_candidate())
    assert FakeSMTP.sent[0]["Reply-To"] is None


def test_the_email_has_the_interview_details_and_a_button(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate()).json()
    message = FakeSMTP.sent[0]
    text = message.get_body(("plain",)).get_content()
    for part in ("INTERVIEW DETAILS", "Position: Backend Developer", "Date: ", "Time: ", f"Duration: {settings.interview_minutes} minutes"):
        assert part in text
    html = message.get_body(("html",)).get_content()
    assert "Join your interview" in html and session["invite_url"] in html
    assert "not meant for you" in html


def test_names_cannot_inject_html(client, auth_headers):
    candidate_id = make_candidate(name="<b>Maya</b>")
    save_company(client, auth_headers, company_name="Acme <script>")
    schedule(client, auth_headers, candidate_id)
    html = FakeSMTP.sent[0].get_body(("html",)).get_content()
    assert "<script>" not in html and "<b>Maya</b>" not in html
    assert "&lt;b&gt;Maya&lt;/b&gt;" in html


def test_company_settings_are_checked(client, auth_headers):
    assert save_company(client, auth_headers, company_name="  ").status_code == 400
    assert save_company(client, auth_headers, contact_email="not-an-address").status_code == 400
    assert client.put("/api/company", json={"company_name": "X"}).status_code == 401  # needs a login


def test_settings_show_the_real_from_line(client, auth_headers):
    body = save_company(client, auth_headers).json()
    assert body["sending_address"] == "hiring@example.com"
    assert body["from_line"] == "WellDev Hiring <hiring@example.com>"  # the default sender name


def test_the_preview_sends_nothing(client, auth_headers):
    save_company(client, auth_headers)
    preview = client.get("/api/company/email-preview", headers=auth_headers).json()
    assert preview["subject"].startswith("Invitation for Interview at WellDev")
    assert "Join your interview" in preview["html"]
    assert client.get("/api/company/email-preview?kind=cancel", headers=auth_headers).json()["subject"].startswith("Interview cancelled")
    assert FakeSMTP.sent == []
