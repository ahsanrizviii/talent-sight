"""Tests for Google Calendar (interviews are put on the company calendar). A fake Google replaces the real one."""

import httpx
import pytest

from app import calendar_events
from app.db import SessionLocal
from app.models import CalendarEvent
from app.settings import settings

from tests.test_interviews import fake_video_server, in_hours, make_candidate, schedule, stored_session  # noqa: F401


class FakeGoogle:
    """Remembers every Calendar request and answers like Google does."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.entries: dict[str, dict] = {}
        self.status_override: dict[str, int] = {}  # method -> status to answer with instead
        self.next_id = 1

    def request(self, method, url, headers=None, timeout=None, json=None, **kwargs):
        self.calls.append((method, url, json))
        if method in self.status_override:
            return httpx.Response(self.status_override[method], json={"error": "x"})
        if method == "POST":
            entry_id = f"event{self.next_id}"
            self.next_id += 1
            self.entries[entry_id] = json
            return httpx.Response(200, json={"id": entry_id})
        entry_id = url.rsplit("/", 1)[-1]
        if method == "PATCH":
            if entry_id not in self.entries:
                return httpx.Response(404, json={})
            self.entries[entry_id] = json
            return httpx.Response(200, json={"id": entry_id})
        if method == "DELETE":
            self.entries.pop(entry_id, None)
            return httpx.Response(204)
        return httpx.Response(200, json={"summary": "BJIT Hiring"})  # GET: the calendar itself


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(settings, "google_calendar_id", "primary")
    monkeypatch.setattr(settings, "google_refresh_token", "token")
    monkeypatch.setattr(calendar_events, "auth_header", lambda: {"Authorization": "Bearer test"})
    monkeypatch.setattr(httpx, "request", fake.request)
    return fake


def stored_event(session_id: int):
    with SessionLocal() as db:
        return db.get(CalendarEvent, session_id)


def test_scheduling_puts_the_interview_on_the_calendar(client, auth_headers, google):
    body = schedule(client, auth_headers, make_candidate()).json()
    assert body["calendar_added"] is True
    assert [call[0] for call in google.calls] == ["POST"]
    entry = google.entries["event1"]
    assert entry["summary"] == "Interview: Maya Rahman for Backend Developer"
    assert stored_event(body["id"]).event_id == "event1"


def test_the_entry_holds_the_interviewers_link_never_the_candidates(client, auth_headers, google):
    body = schedule(client, auth_headers, make_candidate()).json()
    entry = google.entries["event1"]
    token = stored_session(body["id"]).invite_token
    assert f"/interview/{body['id']}" in entry["description"]
    assert token not in str(entry)  # the candidate's private link must not sit on a shared calendar


def test_the_entry_lasts_as_long_as_the_settings_say(client, auth_headers, google, monkeypatch):
    monkeypatch.setattr(settings, "interview_minutes", 45)
    schedule(client, auth_headers, make_candidate())
    entry = google.entries["event1"]
    assert entry["start"]["dateTime"] < entry["end"]["dateTime"]
    start_minutes = int(entry["start"]["dateTime"][14:16])
    end_minutes = int(entry["end"]["dateTime"][14:16])
    assert (end_minutes - start_minutes) % 60 == 45


def test_rescheduling_moves_the_same_entry(client, auth_headers, google):
    session = schedule(client, auth_headers, make_candidate()).json()
    moved = client.patch(f"/api/interviews/{session['id']}", json={"scheduled_at": in_hours(6)}, headers=auth_headers).json()
    assert moved["calendar_added"] is True
    assert [call[0] for call in google.calls] == ["POST", "PATCH"]
    assert len(google.entries) == 1  # one entry, moved, not a second one


def test_cancelling_removes_the_entry(client, auth_headers, google):
    session = schedule(client, auth_headers, make_candidate()).json()
    client.post(f"/api/interviews/{session['id']}/end", headers=auth_headers)
    assert google.entries == {}
    assert stored_event(session["id"]) is None


def test_an_entry_deleted_by_hand_is_made_again(client, auth_headers, google):
    session = schedule(client, auth_headers, make_candidate()).json()
    google.entries.clear()  # somebody removed it in Google Calendar
    moved = client.patch(f"/api/interviews/{session['id']}", json={"scheduled_at": in_hours(6)}, headers=auth_headers).json()
    assert moved["calendar_added"] is True
    assert [call[0] for call in google.calls] == ["POST", "PATCH", "POST"]
    assert stored_event(session["id"]).event_id == "event2"


def test_a_calendar_failure_never_blocks_the_interview(client, auth_headers, google):
    google.status_override["POST"] = 403
    response = schedule(client, auth_headers, make_candidate())
    assert response.status_code == 201
    body = response.json()
    assert body["calendar_added"] is False
    assert "calendar.events" in body["calendar_error"]
    assert body["invite_url"]
    assert stored_event(body["id"]) is None


def test_google_being_unreachable_never_blocks_the_interview(client, auth_headers, google, monkeypatch):
    def down(*args, **kwargs):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "request", down)
    body = schedule(client, auth_headers, make_candidate()).json()
    assert body["calendar_added"] is False
    assert "could not be reached" in body["calendar_error"]


def test_with_calendar_off_nothing_is_called_and_nothing_is_reported(client, auth_headers, google, monkeypatch):
    monkeypatch.setattr(settings, "google_calendar_id", "")
    body = schedule(client, auth_headers, make_candidate()).json()
    assert body["calendar_added"] is None
    assert google.calls == []


def test_deleting_a_candidate_clears_the_stored_entry(client, auth_headers, google):
    candidate_id = make_candidate()
    session = schedule(client, auth_headers, candidate_id).json()
    assert client.delete(f"/api/candidates/{candidate_id}", headers=auth_headers).status_code in (200, 204)
    assert stored_event(session["id"]) is None
