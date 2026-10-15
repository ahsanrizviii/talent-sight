"""Shared answers about the interview calendar, used by "invite top candidates" and by reschedule.

- booked(): every interview still to come or running, as (start, end), each with its own length.
- check_time(): why one exact time cannot be used ("It is a holiday."), or "" when it can.
- free_times(): the next free slots from a given moment.

The rules are fixed (schedule_rules.py); the days off come from the holiday list, which is read
from the calendar PDF in the knowledge folder.
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import holiday_calendar, planner, schedule_rules
from app.models import InterviewSession


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def booked(db: Session, exclude_session_id: int | None = None) -> list[tuple[datetime, datetime]]:
    """Every interview still to come or running, for every job: one hiring team, one calendar.
    exclude_session_id leaves one out, so an interview being moved does not clash with itself."""
    default = schedule_rules.default_minutes(db)
    query = select(InterviewSession).where(InterviewSession.status.in_(("scheduled", "live")))
    if exclude_session_id is not None:
        query = query.where(InterviewSession.id != exclude_session_id)
    return [
        (s.scheduled_at, s.scheduled_at + timedelta(minutes=schedule_rules.minutes_of(s, default)))
        for s in db.scalars(query)
    ]


def days_off(db: Session, first: datetime, last: datetime, rules: planner.Rules) -> set[date]:
    return holiday_calendar.days_off(db, first.astimezone(rules.zone).date(), last.astimezone(rules.zone).date())


def check_time(db: Session, start: datetime, exclude_session_id: int | None = None) -> str:
    """Why this exact time breaks the rules (weekend, holiday, outside hours, clash, past), or ""."""
    rules = schedule_rules.current(db)
    return planner.slot_problem(start, booked(db, exclude_session_id), days_off(db, start, start, rules), rules, utcnow())


def free_times(db: Session, earliest: datetime, count: int, exclude_session_id: int | None = None) -> list[datetime]:
    """The next `count` free 1-hour slots from `earliest`, following every rule."""
    rules = schedule_rules.current(db)
    earliest = max(earliest, utcnow())
    off = days_off(db, earliest, earliest + timedelta(days=planner.MAX_DAYS_AHEAD), rules)
    return planner.plan(count, earliest, booked(db, exclude_session_id), off, rules)
