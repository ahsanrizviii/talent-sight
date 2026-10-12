from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import participants
from app.db import get_db
from app.deps import session_from_invite
from app.models import Candidate, InterviewSession, JobProfile
from app.routers.interviews import JoinOut, video_join
from app.settings import settings

router = APIRouter(prefix="/api/invite", tags=["candidate"])


class InviteInfo(BaseModel):
    """The ONLY things a candidate can see: no scores, ranking or assessment (N9)."""

    session_id: int
    scheduled_at: datetime
    opens_at: datetime  # from this moment the candidate can enter the room
    status: str
    candidate_name: str
    job_title: str


@router.get("/{invite_token}", response_model=InviteInfo)
def invite_info(session: InterviewSession = Depends(session_from_invite), db: Session = Depends(get_db)):
    candidate = db.get(Candidate, session.candidate_id)
    job = db.get(JobProfile, candidate.job_profile_id)
    return InviteInfo(
        session_id=session.id,
        scheduled_at=session.scheduled_at,
        opens_at=session.scheduled_at - timedelta(minutes=settings.join_early_minutes),
        status=session.status,
        candidate_name=candidate.name,
        job_title=job.title,
    )


@router.post("/{invite_token}/join", response_model=JoinOut)
def join_as_candidate(session: InterviewSession = Depends(session_from_invite), db: Session = Depends(get_db)):
    """The candidate enters the room with the invite link as their only key.

    The link already proved (session_from_invite) that the interview exists, has not ended
    and has not expired. Here we only check that it is not too early.
    """
    opens_at = session.scheduled_at - timedelta(minutes=settings.join_early_minutes)
    if datetime.now(timezone.utc) < opens_at:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"It is too early to join. You can join {settings.join_early_minutes} minutes before the start time.",
        )
    candidate = db.get(Candidate, session.candidate_id)
    join = video_join(session, f"candidate-{candidate.id}", candidate.name or "Candidate", "candidate")
    participants.record_join(db, session.id, "candidate", join.identity)
    db.commit()
    return join


@router.post("/{invite_token}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_as_candidate(session: InterviewSession = Depends(session_from_invite), db: Session = Depends(get_db)):
    """The candidate left the room (closed the page or pressed Leave)."""
    participants.record_leave(db, session.id, "candidate")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)