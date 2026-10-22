"""The identity check (Module 13, F7).

candidate_router: the candidate's consent and camera frames, through their private invite link.
router: the interviewer's photo-ID check and the identity state (interviewers only, N9).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from typing import Literal
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



# ---------- the onboarding-day check (Task 13.5.3) ----------
class OnboardingStartIn(BaseModel):
    original_id_checked: bool


class OnboardingStartOut(BaseModel):
    direction: str  # left | right: which way the new hire turns their head
    seconds: int


class OnboardingFinishIn(BaseModel):
    front: str = Field(max_length=MAX_IMAGE_CHARS)   # read in memory, never stored
    turned: str = Field(max_length=MAX_IMAGE_CHARS)


class DecisionIn(BaseModel):
    decision: Literal["confirmed", "not_confirmed"]
    note: str = Field(default="", max_length=500)


class OnboardingCheckOut(BaseModel):
    status: str  # waiting | done
    original_id_checked: bool
    outcome: str  # match | low_confidence | no_templates
    best_score: float | None
    needs_review: bool
    decision: str
    decision_note: str
    decided_by: str
    decided_at: datetime | None
    checked_by: str
    checked_at: datetime | None


class OnboardingOut(BaseModel):
    templates_on_file: int
    templates_taken_at: datetime | None = None    # when the newest face template was made
    templates_expire_at: datetime | None = None   # when the first one is deleted (BIOMETRIC_RETENTION_DAYS)
    templates_interview_at: datetime | None = None  # the interview they come from
    interview_held: bool = False                  # an interview really took place
    consent: bool | None = None                   # the candidate's answer to face matching, None = never asked
    retention_days: int
    check: OnboardingCheckOut | None


def find_candidate(db: Session, candidate_id: int) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found.")
    return candidate


@router.get("/candidates/{candidate_id}/onboarding-check", response_model=OnboardingOut)
def get_onboarding_check(candidate_id: int, db: Session = Depends(get_db)):
    return identity.onboarding_state(db, find_candidate(db, candidate_id))


@router.post("/candidates/{candidate_id}/onboarding-check/start", response_model=OnboardingStartOut)
def start_onboarding_check(
    candidate_id: int,
    body: OnboardingStartIn,
    db: Session = Depends(get_db),
    interviewer: Interviewer = Depends(current_interviewer),
):
    row = identity.start_check(db, find_candidate(db, candidate_id), interviewer, body.original_id_checked)
    return OnboardingStartOut(direction=row.direction, seconds=identity.CHALLENGE_SECONDS)


@router.post("/candidates/{candidate_id}/onboarding-check/finish", response_model=OnboardingOut)
def finish_onboarding_check(candidate_id: int, body: OnboardingFinishIn, db: Session = Depends(get_db)):
    candidate = find_candidate(db, candidate_id)
    identity.finish_check(db, candidate, body.front, body.turned)
    return identity.onboarding_state(db, candidate)


@router.post("/candidates/{candidate_id}/onboarding-check/decision", response_model=OnboardingOut)
def decide_onboarding_check(
    candidate_id: int,
    body: DecisionIn,
    db: Session = Depends(get_db),
    interviewer: Interviewer = Depends(current_interviewer),
):
    candidate = find_candidate(db, candidate_id)
    identity.decide(db, candidate, interviewer, body.decision, body.note)
    return identity.onboarding_state(db, candidate)