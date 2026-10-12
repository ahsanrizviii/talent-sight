"""Interview sessions: the interviewer schedules, joins and ends them (Module 7).

Candidates never use this file. They only use their private invite link (routers/invites.py).
"""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import livekit_service
from app.db import get_db
from app.deps import current_interviewer
from app.models import Candidate, Interviewer, InterviewSession, JobProfile
from app.settings import settings

router = APIRouter(prefix="/api", tags=["interviews"], dependencies=[Depends(current_interviewer)])

MAX_DAYS_AHEAD = 90


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- What the API receives and sends back ----------


class ScheduleIn(BaseModel):
    scheduled_at: datetime

    @field_validator("scheduled_at")
    @classmethod
    def must_be_a_sensible_future_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Please include the time zone.")
        if value <= utcnow():
            raise ValueError("Pick a time in the future.")
        if value > utcnow() + timedelta(days=MAX_DAYS_AHEAD):
            raise ValueError(f"Pick a time within the next {MAX_DAYS_AHEAD} days.")
        return value


class SessionOut(BaseModel):
    id: int
    candidate_id: int
    candidate_name: str
    job_title: str
    scheduled_at: datetime
    invite_expires_at: datetime
    status: str  # scheduled | live | ended
    started_at: datetime | None
    ended_at: datetime | None


class JoinOut(BaseModel):
    """Everything a browser needs to enter the video room."""

    livekit_url: str
    token: str
    room: str
    identity: str


# ---------- Helpers ----------


def new_invite_token() -> str:
    """43 random characters. Nobody can guess one, and every session gets its own."""
    return secrets.token_urlsafe(32)


def expiry_for(scheduled_at: datetime) -> datetime:
    return scheduled_at + timedelta(hours=settings.invite_hours_after)


def find_session(db: Session, session_id: int) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Interview not found.")
    return session


def to_out(db: Session, session: InterviewSession) -> SessionOut:
    candidate = db.get(Candidate, session.candidate_id)
    job = db.get(JobProfile, candidate.job_profile_id)
    return SessionOut(
        id=session.id,
        candidate_id=candidate.id,
        candidate_name=candidate.name or candidate.cv_filename,
        job_title=job.title,
        scheduled_at=session.scheduled_at,
        invite_expires_at=session.invite_expires_at,
        status=session.status,
        started_at=session.started_at,
        ended_at=session.ended_at,
    )


def video_join(session: InterviewSession, identity: str, name: str, role: str) -> JoinOut:
    """Makes sure the room exists and signs a token for one person. Used by both roles."""
    try:
        livekit_service.ensure_room(session.id)
        token = livekit_service.join_token(session.id, identity, name, role)
    except livekit_service.LiveKitError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error))
    return JoinOut(
        livekit_url=settings.livekit_url,
        token=token,
        room=livekit_service.room_name(session.id),
        identity=identity,
    )


# ---------- Endpoints ----------


@router.post("/candidates/{candidate_id}/interview", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def schedule_interview(candidate_id: int, body: ScheduleIn, db: Session = Depends(get_db)):
    """Creates the interview for a screened candidate, at a time in the future (Q&A 40)."""
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found.")
    if candidate.status != "screened":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only screened candidates can be invited to an interview.")
    already = db.scalar(
        select(InterviewSession).where(
            InterviewSession.candidate_id == candidate_id,
            InterviewSession.status.in_(("scheduled", "live")),
        )
    )
    if already is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This candidate already has an interview. Reschedule it instead.")

    session = InterviewSession(
        candidate_id=candidate_id,
        scheduled_at=body.scheduled_at,
        invite_token=new_invite_token(),
        invite_expires_at=expiry_for(body.scheduled_at),
    )
    db.add(session)
    db.commit()
    return to_out(db, session)


@router.get("/candidates/{candidate_id}/interview", response_model=SessionOut | None)
def latest_interview(candidate_id: int, db: Session = Depends(get_db)):
    """The newest interview of this candidate, or null if there is none."""
    session = db.scalar(
        select(InterviewSession)
        .where(InterviewSession.candidate_id == candidate_id)
        .order_by(InterviewSession.id.desc())
        .limit(1)
    )
    return to_out(db, session) if session else None


@router.get("/interviews/{session_id}", response_model=SessionOut)
def get_interview(session_id: int, db: Session = Depends(get_db)):
    return to_out(db, find_session(db, session_id))


@router.patch("/interviews/{session_id}", response_model=SessionOut)
def reschedule_interview(session_id: int, body: ScheduleIn, db: Session = Depends(get_db)):
    """Moves a waiting interview to a new time. The invite link stays the same."""
    session = find_session(db, session_id)
    if session.status != "scheduled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only an interview that has not started can be moved.")
    session.scheduled_at = body.scheduled_at
    session.invite_expires_at = expiry_for(body.scheduled_at)
    db.commit()
    return to_out(db, session)


@router.post("/interviews/{session_id}/join", response_model=JoinOut)
def join_interview(
    session_id: int,
    interviewer: Interviewer = Depends(current_interviewer),
    db: Session = Depends(get_db),
):
    """The interviewer enters the room. The first join starts the interview (status live)."""
    session = find_session(db, session_id)
    if session.status == "ended":
        raise HTTPException(status.HTTP_409_CONFLICT, "This interview has ended.")
    join = video_join(session, f"interviewer-{interviewer.id}", interviewer.email, "interviewer")
    if session.status == "scheduled":
        session.status = "live"
        session.started_at = utcnow()
    db.commit()
    return join


@router.post("/interviews/{session_id}/end", response_model=SessionOut)
def end_interview(session_id: int, db: Session = Depends(get_db)):
    """Ends the interview (or cancels one that never started) and closes its room."""
    session = find_session(db, session_id)
    if session.status != "ended":
        session.status = "ended"
        session.ended_at = utcnow()
        db.commit()
        livekit_service.close_room(session.id)
    return to_out(db, session)