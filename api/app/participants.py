"""Who was in an interview and when (Module 7). Times and roles only, never audio or video (Q&A 7)."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InterviewSession, SessionParticipant


def _now() -> datetime:
    return datetime.now(timezone.utc)


def record_join(db: Session, session_id: int, role: str, identity: str) -> None:
    """Notes that someone entered the room. Joining again without leaving (a page refresh) adds nothing new."""
    # Two joins can arrive at the same moment (a double click, a fast refresh). Locking the session row
    # makes the second one wait until the first is saved, so it sees the row and does not add another.
    db.execute(select(InterviewSession.id).where(InterviewSession.id == session_id).with_for_update())
    still_in = db.scalar(
        select(SessionParticipant).where(
            SessionParticipant.session_id == session_id,
            SessionParticipant.role == role,
            SessionParticipant.left_at.is_(None),
        )
    )
    if still_in is None:
        db.add(SessionParticipant(session_id=session_id, role=role, identity=identity, joined_at=_now()))


def record_leave(db: Session, session_id: int, role: str) -> None:
    """Notes that someone left. Safe to call twice."""
    for row in db.scalars(
        select(SessionParticipant).where(
            SessionParticipant.session_id == session_id,
            SessionParticipant.role == role,
            SessionParticipant.left_at.is_(None),
        )
    ):
        row.left_at = _now()


def close_all(db: Session, session_id: int, when: datetime) -> None:
    """When the interview ends, everyone who is still inside is marked as leaving at that moment."""
    for row in db.scalars(
        select(SessionParticipant).where(SessionParticipant.session_id == session_id, SessionParticipant.left_at.is_(None))
    ):
        row.left_at = when


def history(db: Session, session_id: int) -> list[SessionParticipant]:
    return list(
        db.scalars(
            select(SessionParticipant)
            .where(SessionParticipant.session_id == session_id)
            .order_by(SessionParticipant.joined_at, SessionParticipant.id)
        )
    )


def duration_seconds(session: InterviewSession) -> int | None:
    if session.started_at is None or session.ended_at is None:
        return None
    return max(0, int((session.ended_at - session.started_at).total_seconds()))