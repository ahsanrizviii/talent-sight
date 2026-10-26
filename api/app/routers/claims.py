"""CV claims checked against the interview (Module 13, F8).

Interviewers only. The candidate never sees it (N9). The flags are prompts for a person to follow
up; they never change the candidate's score, position or stage.
"""

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import claim_check
from app.db import get_db
from app.deps import current_interviewer
from app.models import Candidate, ClaimCheck

router = APIRouter(prefix="/api", tags=["claim check"], dependencies=[Depends(current_interviewer)])


class ClaimCheckOut(BaseModel):
    candidate_id: int
    session_id: int | None
    status: str  # running | done | failed
    step: str    # what the agent is doing now, while it runs
    error: str
    started_at: datetime
    finished_at: datetime | None
    seconds: float | None
    outdated: bool       # the interview answers were analysed again after this check
    claims: list[dict]   # [{"id", "kind", "claim", "status", "label", "note", "evidence", "follow_up", "turns"}]
    summary: dict        # how many claims have each status
    turns: list[dict]    # the transcript turns the claims point to


def to_out(db: Session, row: ClaimCheck) -> ClaimCheckOut:
    result = row.result or {}
    return ClaimCheckOut(
        candidate_id=row.candidate_id,
        session_id=row.session_id,
        status=row.status,
        step=row.step,
        error=row.error,
        started_at=row.started_at,
        finished_at=row.finished_at,
        seconds=row.seconds,
        outdated=claim_check.is_outdated(db, row),
        claims=result.get("claims", []),
        summary=result.get("summary", {}),
        turns=result.get("turns", []),
    )


def find_candidate(db: Session, candidate_id: int) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found.")
    return candidate


@router.post("/candidates/{candidate_id}/claim-check", response_model=ClaimCheckOut, status_code=status.HTTP_202_ACCEPTED)
def check_claims(candidate_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Starts the check in the background and answers at once with status "running"."""
    row = claim_check.start_check(db, find_candidate(db, candidate_id))
    background.add_task(claim_check.run_check, row.id)
    return to_out(db, row)


@router.get("/candidates/{candidate_id}/claim-check", response_model=ClaimCheckOut | None)
def get_claim_check(candidate_id: int, db: Session = Depends(get_db)):
    """The latest check, or null when nobody has asked for one yet. The screen polls this while it runs."""
    find_candidate(db, candidate_id)
    row = claim_check.check_of(db, candidate_id)
    return to_out(db, row) if row else None