"""The identity check (Module 13, F7).

candidate_router: the candidate's consent and camera frames, through their private invite link.
router: the interviewer's photo-ID check and the identity state (interviewers only, N9).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import identity
from app.db import get_db
from app.deps import current_interviewer, not_an_interviewer, session_from_invite
from app.models import Candidate, Interviewer, InterviewSession
from app.routers.interviews import find_session
from app.settings import settings

MAX_IMAGE_CHARS = 2_800_000  # a 2 MB JPEG as a data URL

candidate_router = APIRouter(prefix="/api/invite", tags=["candidate"], dependencies=[Depends(not_an_interviewer)])
router = APIRouter(prefix="/api", tags=["identity"], dependencies=[Depends(current_interviewer)])


class ConsentIn(BaseModel):
    consent: bool


class FrameIn(BaseModel):
    image: str = Field(max_length=MAX_IMAGE_CHARS)  # a JPEG data URL; read in memory, never stored


class CandidateIdentityOut(BaseModel):
    """All a candidate sees about this: their own answer and how long templates are kept."""

    consent: bool | None
    templates: int
    retention_days: int


class IdCheckIn(BaseModel):
    id_checked: bool
    name_matches: bool


class IdentityOut(BaseModel):
    session_id: int
    consent: bool | None  # None = the candidate has not answered yet
    templates: int
    id_checked: bool
    name_matches: bool
    checked_by: str
    checked_at: datetime | None
    state: str  # confirmed | name_mismatch | not_checked
    retention_days: int


def candidate_view(db: Session, session: InterviewSession) -> CandidateIdentityOut:
    state = identity.state_of(db, session)
    return CandidateIdentityOut(consent=state["consent"], templates=state["templates"], retention_days=settings.biometric_retention_days)


# ---------- the candidate, through the invite link ----------
@candidate_router.get("/{invite_token}/identity", response_model=CandidateIdentityOut)
def candidate_identity(session: InterviewSession = Depends(session_from_invite), db: Session = Depends(get_db)):
    return candidate_view(db, session)


@candidate_router.post("/{invite_token}/identity/consent", response_model=CandidateIdentityOut)
def give_consent(body: ConsentIn, session: InterviewSession = Depends(session_from_invite), db: Session = Depends(get_db)):
    identity.set_consent(db, session, body.consent)
    return candidate_view(db, session)


@candidate_router.post("/{invite_token}/identity/frame", response_model=CandidateIdentityOut)
def send_frame(body: FrameIn, session: InterviewSession = Depends(session_from_invite), db: Session = Depends(get_db)):
    identity.add_frame(db, session, body.image)
    return candidate_view(db, session)


# ---------- the interviewer ----------
@router.get("/interviews/{session_id}/identity", response_model=IdentityOut)
def get_identity(session_id: int, db: Session = Depends(get_db)):
    return IdentityOut(**identity.state_of(db, find_session(db, session_id)))


@router.post("/interviews/{session_id}/identity/id-check", response_model=IdentityOut)
def record_id_check(
    session_id: int,
    body: IdCheckIn,
    db: Session = Depends(get_db),
    interviewer: Interviewer = Depends(current_interviewer),
):
    session = find_session(db, session_id)
    identity.set_id_check(db, session, interviewer, body.id_checked, body.name_matches)
    return IdentityOut(**identity.state_of(db, session))


@router.delete("/candidates/{candidate_id}/face-templates", status_code=status.HTTP_204_NO_CONTENT)
def delete_face_templates(candidate_id: int, db: Session = Depends(get_db)):
    """Deletes the candidate's face templates at once (for example when they are not hired)."""
    if db.get(Candidate, candidate_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found.")
    identity.delete_templates(db, candidate_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)