"""The interview schedule. It is fixed, not chosen in the app:
- every interview lasts 1 hour (INTERVIEW_MINUTES, 60);
- interviews are booked 09:00-12:00 and 14:00-17:00 (INTERVIEW_WINDOWS), with 15 minutes between them
  (INTERVIEW_GAP_MINUTES);
- Monday to Friday only: Saturday and Sunday are the weekend (WORK_DAYS).
These live in settings.py (and can be changed in .env by whoever runs the server).
Every interview also keeps its own length (interview_sessions.duration_minutes), so an interview booked
earlier with another length keeps it.
"""

from sqlalchemy.orm import Session

from app.models import InterviewSession
from app.planner import Rules, rules_from_settings
from app.settings import settings


def current(db: Session | None = None) -> Rules:
    """The rules in force. db is not needed any more; it is accepted so callers stay simple."""
    return rules_from_settings()


def default_minutes(db: Session | None = None) -> int:
    return settings.interview_minutes


def minutes_of(session: InterviewSession, default: int | None = None) -> int:
    """How long this interview is booked for. Older interviews without a length use the default."""
    if session.duration_minutes:
        return session.duration_minutes
    return default if default is not None else default_minutes()
