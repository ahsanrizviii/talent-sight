"""The interview schedule the hiring team chose on the Settings page: length, gap, hours, days.

Stored in the schedule_rules table (one row). Until someone saves it, the values in .env apply.
Every interview also keeps its own length (interview_sessions.duration_minutes), so changing the
setting later never moves an interview that is already booked.
"""

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import InterviewSession, ScheduleRules
from app.planner import Rules, make_rules, rules_from_settings


def current(db: Session | None = None) -> Rules:
    """The rules in force now. Raises planner.PlanError if what is stored cannot be used."""
    if db is None:
        with SessionLocal() as own:
            return current(own)
    row = db.get(ScheduleRules, 1)
    if row is None:
        return rules_from_settings()
    return make_rules(row.interview_minutes, row.gap_minutes, row.windows, row.work_days)


def save(db: Session, minutes: int, gap: int, windows: str, days: str) -> Rules:
    """Checks and stores new rules. Raises planner.PlanError with a readable message."""
    rules = make_rules(minutes, gap, windows, days)  # check first: nothing wrong is ever stored
    row = db.get(ScheduleRules, 1) or ScheduleRules(id=1)
    row.interview_minutes = minutes
    row.gap_minutes = gap
    row.windows = rules.windows_text()
    row.work_days = rules.days_text()
    db.add(row)
    db.commit()
    return rules


def default_minutes(db: Session | None = None) -> int:
    return int(current(db).length.total_seconds() // 60)


def minutes_of(session: InterviewSession, default: int | None = None) -> int:
    """How long this interview is booked for. Older interviews without a length use the setting."""
    if session.duration_minutes:
        return session.duration_minutes
    return default if default is not None else default_minutes()
