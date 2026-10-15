"""Tests for the interview schedule on the Settings page, interview lengths, and moving an interview."""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import InterviewSession
from app.settings import settings

from tests.test_interviews import fake_video_server, make_candidate, schedule, stored_session  # noqa: F401
from tests.test_invite_mail import FakeSMTP, fake_mail_server  # noqa: F401

ZONE = timezone(timedelta(minutes=settings.interview_utc_offset_minutes))


def next_weekday_at(hour: int, minute: int = 0, weekday: int = 0) -> datetime:
    """The next given weekday (0 = Monday) at this local time, at least a day from now."""
    day = datetime.now(ZONE).date() + timedelta(days=1)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return datetime.combine(day, time(hour, minute), ZONE)


RULES = {
    "interview_minutes": 45,
    "gap_minutes": 10,
    "windows": [{"start": "09:00", "end": "12:00"}, {"start": "14:00", "end": "17:00"}],
    "work_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
}


def test_default_rules_come_from_env(client, auth_headers):
    rules = client.get("/api/schedule-rules", headers=auth_headers).json()
    assert rules["interview_minutes"] == settings.interview_minutes
    assert rules["work_days"] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    assert rules["slots_per_day"] == 4


def test_rules_can_be_changed(client, auth_headers):
    saved = client.put("/api/schedule-rules", json=RULES, headers=auth_headers).json()
    assert saved["interview_minutes"] == 45 and saved["gap_minutes"] == 10
    assert saved["slots_per_day"] == 6  # 9:00, 9:55, 10:50 and 14:00, 14:55, 15:50
    assert client.get("/api/schedule-rules", headers=auth_headers).json() == saved


def test_wrong_rules_are_refused(client, auth_headers):
    backwards = {**RULES, "windows": [{"start": "12:00", "end": "09:00"}]}
    assert client.put("/api/schedule-rules", json=backwards, headers=auth_headers).status_code == 400
    overlapping = {**RULES, "windows": [{"start": "09:00", "end": "12:00"}, {"start": "11:00", "end": "13:00"}]}
    assert client.put("/api/schedule-rules", json=overlapping, headers=auth_headers).status_code == 400
    too_long = {**RULES, "interview_minutes": 200, "windows": [{"start": "09:00", "end": "10:00"}]}
    assert "fits" in client.put("/api/schedule-rules", json=too_long, headers=auth_headers).json()["detail"]
    assert client.put("/api/schedule-rules", json={**RULES, "work_days": ["Funday"]}, headers=auth_headers).status_code == 400
    assert client.put("/api/schedule-rules", json=RULES).status_code == 401


def test_a_new_interview_gets_the_length_from_settings(client, auth_headers):
    client.put("/api/schedule-rules", json=RULES, headers=auth_headers)
    session = schedule(client, auth_headers, make_candidate(), next_weekday_at(10).isoformat()).json()
    assert session["duration_minutes"] == 45
    assert "Duration: 45 minutes" in FakeSMTP.sent[0].get_body(("plain",)).get_content()


def test_changing_the_setting_does_not_change_booked_interviews(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate(), next_weekday_at(10).isoformat()).json()
    client.put("/api/schedule-rules", json=RULES, headers=auth_headers)
    assert client.get(f"/api/interviews/{session['id']}", headers=auth_headers).json()["duration_minutes"] == settings.interview_minutes


def test_one_interview_can_have_its_own_length(client, auth_headers):
    body = {"scheduled_at": next_weekday_at(10).isoformat(), "duration_minutes": 30}
    session = client.post(f"/api/candidates/{make_candidate()}/interview", json=body, headers=auth_headers).json()
    assert session["duration_minutes"] == 30


# ---------- Moving an interview when the candidate asks ----------


def test_time_check_warns_about_rule_breaks(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate(), next_weekday_at(9).isoformat()).json()
    check = lambda at: client.get(  # noqa: E731
        f"/api/interviews/{session['id']}/time-check", params={"at": at.isoformat()}, headers=auth_headers
    ).json()["problem"]
    assert check(next_weekday_at(10, 15, weekday=1)) == ""
    assert check(next_weekday_at(10, weekday=5)) == "It is not a working day."  # Saturday
    assert check(next_weekday_at(12, 30)) == "It is outside the interview hours."
    assert check(next_weekday_at(9)) == ""  # its own current time is not a clash with itself
    other = schedule(client, auth_headers, make_candidate(name="Rafi"), next_weekday_at(14, weekday=2).isoformat()).json()
    assert other["id"] != session["id"]
    assert check(next_weekday_at(14, 30, weekday=2)) == "It clashes with another interview."


def test_time_check_knows_holidays(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate(), next_weekday_at(9).isoformat()).json()
    holiday = next_weekday_at(10, weekday=3)
    client.post("/api/holidays", json={"holidays": [{"day": holiday.date().isoformat(), "name": "Test"}]}, headers=auth_headers)
    problem = client.get(f"/api/interviews/{session['id']}/time-check", params={"at": holiday.isoformat()}, headers=auth_headers).json()["problem"]
    assert problem == "It is a holiday."


def test_free_times_follow_every_rule(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate(), next_weekday_at(9).isoformat()).json()
    blocker = schedule(client, auth_headers, make_candidate(name="Rafi"), next_weekday_at(10, 15).isoformat()).json()
    start = next_weekday_at(0)
    times = client.get(
        f"/api/interviews/{session['id']}/free-times", params={"start": start.isoformat(), "count": 4}, headers=auth_headers
    ).json()
    local = [datetime.fromisoformat(t).astimezone(ZONE) for t in times]
    assert [f"{t:%H:%M}" for t in local] == ["09:00", "14:00", "15:15", "09:00"]  # 10:15 is taken by Rafi
    assert local[0].date() == start.date() and local[3].date() == start.date() + timedelta(days=1)
    assert blocker["id"]


def test_moving_e_mails_the_new_time_and_keeps_the_link(client, auth_headers):
    session = schedule(client, auth_headers, make_candidate(), next_weekday_at(9).isoformat()).json()
    token = stored_session(session["id"]).invite_token
    new_time = next_weekday_at(14, weekday=1)
    moved = client.patch(f"/api/interviews/{session['id']}", json={"scheduled_at": new_time.isoformat()}, headers=auth_headers).json()
    assert moved["email_sent"] is True
    assert FakeSMTP.sent[-1]["Subject"].startswith("Interview rescheduled")
    with SessionLocal() as db:
        row = db.scalar(select(InterviewSession).where(InterviewSession.id == session["id"]))
        assert row.invite_token == token and row.scheduled_at == new_time
