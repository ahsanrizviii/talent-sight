"""Interview sessions: the interviewer schedules, joins and ends them (Module 7).

Candidates never use this file. They only use their private invite link (routers/invites.py).
"""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import calendar_events, invite_mail, livekit_service, participants, planner, schedule_rules, scheduling, transcription
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
    scheduled_at: datetime  # every interview lasts 1 hour (schedule_rules.py)

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


class ParticipantOut(BaseModel):
    role: str
    joined_at: datetime
    left_at: datetime | None


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
    duration_seconds: int | None  # from the first join to the end; None until the interview has ended
    duration_minutes: int  # how long it is booked for
    participants: list[ParticipantOut]
    invite_url: str  # the candidate's private link; only the logged-in interviewer ever sees it
    email_sent: bool | None = None  # None = no e-mail was tried in this answer
    email_error: str = ""
    calendar_added: bool | None = None  # None = Google Calendar is off or was not tried in this answer
    calendar_error: str = ""


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


def to_out(
    db: Session, session: InterviewSession, mail_error: str | None = None, calendar_error: str | None = None
) -> SessionOut:
    """mail_error: None = no e-mail was tried, "" = it was sent, anything else = why it was not.
    calendar_error: the same three states for the Google Calendar entry."""
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
        duration_seconds=participants.duration_seconds(session),
        duration_minutes=schedule_rules.minutes_of(session),
        participants=[
            ParticipantOut(role=row.role, joined_at=row.joined_at, left_at=row.left_at)
            for row in participants.history(db, session.id)
        ],
        invite_url=invite_mail.invite_link(session.invite_token),
        email_sent=None if mail_error is None else mail_error == "",
        email_error=mail_error or "",
        calendar_added=None if calendar_error is None else calendar_error == "",
        calendar_error=calendar_error or "",
    )


def send_invite_for(db: Session, session: InterviewSession, rescheduled: bool = False) -> str:
    """Sends the invitation. Returns "" when sent, otherwise the reason. Never raises."""
    candidate = db.get(Candidate, session.candidate_id)
    job = db.get(JobProfile, candidate.job_profile_id)
    return invite_mail.send_invite(session, candidate, job, rescheduled)


def calendar_for(db: Session, session: InterviewSession) -> str | None:
    """Puts the interview on Google Calendar, or moves its entry. None = Calendar is off. Never raises."""
    candidate = db.get(Candidate, session.candidate_id)
    job = db.get(JobProfile, candidate.job_profile_id)
    return calendar_events.add_or_move(db, session, candidate, job)


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
        duration_minutes=schedule_rules.default_minutes(db),
    )
    db.add(session)
    db.commit()
    # A failed e-mail or calendar entry never blocks the interview: the answer says why, and the link can be copied.
    return to_out(db, session, send_invite_for(db, session), calendar_for(db, session))


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
    return to_out(db, session, send_invite_for(db, session, rescheduled=True), calendar_for(db, session))


@router.post("/interviews/{session_id}/invite", response_model=SessionOut)
def send_invite_again(session_id: int, db: Session = Depends(get_db)):
    """Sends the invitation e-mail again, with the same link."""
    session = find_session(db, session_id)
    if session.status != "scheduled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only an interview that has not started can be sent again.")
    return to_out(db, session, send_invite_for(db, session))


class TimeCheckOut(BaseModel):
    problem: str  # "" = the time follows every rule; otherwise why not (HR may still choose it)


@router.get("/interviews/{session_id}/time-check", response_model=TimeCheckOut)
def check_new_time(session_id: int, at: datetime, db: Session = Depends(get_db)):
    """Before moving an interview: does the new time break a rule? A candidate may ask for a time
    outside the normal hours, so this only warns; the page asks HR to confirm."""
    session = find_session(db, session_id)
    if at.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Please include the time zone.")
    return TimeCheckOut(problem=scheduling.check_time(db, at, exclude_session_id=session.id))


@router.get("/interviews/{session_id}/free-times", response_model=list[datetime])
def suggest_free_times(
    session_id: int,
    start: datetime | None = None,
    count: int = Query(6, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """The next free slots for this interview (working days, interview hours, no holidays, no clash)."""
    session = find_session(db, session_id)
    if start is not None and start.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Please include the time zone.")
    try:
        return scheduling.free_times(db, start or utcnow(), count, exclude_session_id=session.id)
    except planner.PlanError as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem))


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
    participants.record_join(db, session.id, "interviewer", join.identity)
    db.commit()
    return join


@router.post("/interviews/{session_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_interview(session_id: int, db: Session = Depends(get_db)):
    """The interviewer left the room but the interview goes on (they can come back)."""
    participants.record_leave(db, find_session(db, session_id).id, "interviewer")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/interviews/{session_id}/end", response_model=SessionOut)
def end_interview(session_id: int, db: Session = Depends(get_db)):
    """Ends the interview (or cancels one that never started) and closes its room."""
    session = find_session(db, session_id)
    if session.status != "ended":
        cancelled_before_start = session.status == "scheduled"
        session.status = "ended"
        session.ended_at = utcnow()
        participants.close_all(db, session.id, session.ended_at)
        db.commit()
        livekit_service.close_room(session.id)
        transcription.end_interview(session.id)  # stop live speech to text for both speakers (Module 8)
        if cancelled_before_start:
            # The candidate was told about this interview, so tell them it is off, and clear both calendars.
            candidate = db.get(Candidate, session.candidate_id)
            job = db.get(JobProfile, candidate.job_profile_id)
            mail_error = invite_mail.send_cancellation(session, candidate, job)
            return to_out(db, session, mail_error, calendar_events.remove(db, session))
    return to_out(db, session)