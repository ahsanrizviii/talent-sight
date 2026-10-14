"""Google Calendar for interviews.

Scheduling an interview puts an entry on the company's Google Calendar (the account the
GOOGLE_REFRESH_TOKEN belongs to). Moving the interview moves the entry, and cancelling it removes
the entry. The entry is for the interviewing team: it holds the TalentSight link that opens the
interviewer's room, never the candidate's private link. The candidate gets a calendar invitation
of their own, attached to the invitation e-mail (see invite_mail.py).

Nothing here may break scheduling. Every public function returns None when Calendar is switched
off, "" when it worked, or a short reason when it did not, and never raises.
"""

import logging
from datetime import timedelta, timezone
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from app.google_api import TIMEOUT, GoogleError, auth_header
from app.models import CalendarEvent, Candidate, InterviewSession, JobProfile
from app.settings import settings

log = logging.getLogger("talentsight")

CALENDAR_API = "https://www.googleapis.com/calendar/v3/calendars"


def _id(calendar_id: str) -> str:
    """A calendar id can be an e-mail address, so it must be escaped to sit inside a URL."""
    return quote(calendar_id.strip(), safe="")


def enabled() -> bool:
    return bool(settings.google_calendar_id.strip() and settings.google_refresh_token.strip())


def room_link(session_id: int) -> str:
    """The interviewer's room. It needs a login, so it is safe to put on a shared calendar."""
    return f"{settings.public_base_url.rstrip('/')}/interview/{session_id}"


def event_body(session: InterviewSession, candidate: Candidate, job: JobProfile) -> dict:
    start = session.scheduled_at.astimezone(timezone.utc)
    end = start + timedelta(minutes=settings.interview_minutes)
    name = candidate.name.strip() or candidate.cv_filename
    title = " ".join(job.title.split())
    link = room_link(session.id)
    return {
        "summary": f"Interview: {name} for {title}",
        "description": (
            f"Video interview with {name} for the {title} position.\n\n"
            f"Open the interview room: {link}\n\n"
            "This entry is for the interviewing team. The candidate has their own private link."
        ),
        "location": link,
        "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "timeZone": "UTC"},
        "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "timeZone": "UTC"},
        "source": {"title": "TalentSight", "url": link},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 15}]},
        "extendedProperties": {"private": {"talentsight_session": str(session.id)}},
    }


def _call(method: str, url: str, **kwargs) -> httpx.Response:
    try:
        return httpx.request(method, url, headers=auth_header(), timeout=TIMEOUT, **kwargs)
    except httpx.HTTPError as error:
        raise GoogleError("Google Calendar could not be reached.") from error


def _refused(response: httpx.Response) -> GoogleError:
    if response.status_code in (401, 403):
        text = response.text
        if "accessNotConfigured" in text or "has not been used" in text or "is disabled" in text:
            return GoogleError(
                "The Google Calendar API is switched off for your Google project. "
                "Enable it in the Cloud console: APIs & Services, Library, Google Calendar API."
            )
        return GoogleError(
            "Google Calendar refused the request. The Google token needs the calendar.events permission "
        )
    if response.status_code == 404:
        return GoogleError("Google Calendar was not found. Check GOOGLE_CALENDAR_ID.")
    return GoogleError(f"Google Calendar refused the request ({response.status_code}).")


def _put_on_calendar(db: Session, session: InterviewSession, candidate: Candidate, job: JobProfile) -> None:
    calendar = settings.google_calendar_id.strip()
    body = event_body(session, candidate, job)
    row = db.get(CalendarEvent, session.id)

    if row is not None:
        response = _call("PATCH", f"{CALENDAR_API}/{_id(row.calendar_id)}/events/{row.event_id}", json=body)
        if response.status_code == 200:
            return
        if response.status_code not in (404, 410):
            raise _refused(response)
        # Someone deleted the entry by hand in Google Calendar: make a fresh one below.
        db.delete(row)
        db.flush()

    response = _call("POST", f"{CALENDAR_API}/{_id(calendar)}/events", json=body)
    if response.status_code not in (200, 201):
        raise _refused(response)
    db.add(CalendarEvent(session_id=session.id, event_id=response.json()["id"], calendar_id=calendar))
    db.commit()


def add_or_move(db: Session, session: InterviewSession, candidate: Candidate, job: JobProfile) -> str | None:
    """Creates the entry, or moves the one that exists. None = Calendar is off, "" = done."""
    if not enabled():
        return None
    try:
        _put_on_calendar(db, session, candidate, job)
    except GoogleError as error:
        db.rollback()
        log.warning("calendar entry failed", extra={"event": "calendar_failed", "session_id": session.id, "reason": str(error)})
        return str(error)
    except Exception as error:  # a surprise must never stop an interview being scheduled
        db.rollback()
        log.warning("calendar entry failed", exc_info=error, extra={"event": "calendar_failed", "session_id": session.id})
        return "The interview could not be added to Google Calendar."
    log.info("calendar entry saved", extra={"event": "calendar_saved", "session_id": session.id})
    return ""


def remove(db: Session, session: InterviewSession) -> str | None:
    """Deletes the entry of a cancelled interview. None = Calendar is off or there was no entry."""
    if not enabled():
        return None
    row = db.get(CalendarEvent, session.id)
    if row is None:
        return None
    try:
        response = _call("DELETE", f"{CALENDAR_API}/{_id(row.calendar_id)}/events/{row.event_id}")
        if response.status_code not in (200, 204, 404, 410):  # already gone counts as done
            raise _refused(response)
        db.delete(row)
        db.commit()
    except GoogleError as error:
        db.rollback()
        log.warning("calendar removal failed", extra={"event": "calendar_failed", "session_id": session.id, "reason": str(error)})
        return str(error)
    return ""


def check_access() -> tuple[bool, str]:
    """For the setup page: can the token add interviews? Returns (works, plain-words detail)."""
    if not enabled():
        return False, "Not connected."
    try:
        # The calendar.events permission cannot read calendar settings, so ask for one event instead.
        response = _call("GET", f"{CALENDAR_API}/{_id(settings.google_calendar_id)}/events", params={"maxResults": 1})
        if response.status_code != 200:
            raise _refused(response)
    except GoogleError as error:
        return False, str(error)
    return True, f"Interviews are added to the calendar “{settings.google_calendar_id}”."