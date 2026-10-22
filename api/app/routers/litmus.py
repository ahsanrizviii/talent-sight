"""Litmus (F11): checks that a CV score rests on the CV, not on who the candidate is.

Interviewers only. The candidate never sees it (N9). A check never changes a score, a verdict,
the ranking or a stage; a flagged result only asks a person to look and acknowledge it.
"""

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import litmus_run
from app.db import get_db
from app.deps import current_interviewer
from app.models import Candidate, Interviewer, JobProfile, LitmusCheck
from app.settings import settings

router = APIRouter(prefix="/api", tags=["litmus"], dependencies=[Depends(current_interviewer)])


class LitmusOut(BaseModel):
    id: int
    candidate_id: int
    status: str  # queued | running | done | failed
    step: str    # what the agent is doing now, while it runs
    error: str
    started_at: datetime
    finished_at: datetime | None
    seconds: float | None
    outdated: bool  # the candidate was screened again, or the job or its weights changed, after this check
    result: dict    # {"outcome", "flag_count", "reference", "repeat", "noise", "variants", "audit"}
    review_status: str  # "" | pending | acknowledged
    review_note: str
    reviewed_by: str
    reviewed_at: datetime | None
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class HistoryItem(BaseModel):
    id: int
    status: str
    outcome: str
    review_status: str
    started_at: datetime
    cost_usd: float


class ReviewIn(BaseModel):
    note: str


class QueuedOut(BaseModel):
    queued: int
    check_ids: list[int]


def to_out(db: Session, row: LitmusCheck) -> LitmusOut:
    return LitmusOut(
        id=row.id,
        candidate_id=row.candidate_id,
        status=row.status,
        step=row.step,
        error=row.error,
        started_at=row.started_at,
        finished_at=row.finished_at,
        seconds=row.seconds,
        outdated=litmus_run.is_outdated(db, row),
        result=row.result or {},
        review_status=row.review_status,
        review_note=row.review_note,
        reviewed_by=litmus_run.reviewer_name(db, row.reviewed_by),
        reviewed_at=row.reviewed_at,
        llm_calls=row.llm_calls,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_usd=row.cost_usd,
    )


def find_candidate(db: Session, candidate_id: int) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found.")
    return candidate


def find_job(db: Session, job_id: int) -> JobProfile:
    job = db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return job


@router.post("/candidates/{candidate_id}/litmus", response_model=LitmusOut, status_code=status.HTTP_202_ACCEPTED)
def start_check(candidate_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Starts a check in the background and answers at once with status "running"."""
    row = litmus_run.start_check(db, find_candidate(db, candidate_id))
    background.add_task(litmus_run.run_check, row.id)
    return to_out(db, row)


@router.get("/candidates/{candidate_id}/litmus", response_model=LitmusOut | None)
def latest_check(candidate_id: int, db: Session = Depends(get_db)):
    """The latest check, or null when there is none yet. The screen polls this while it runs."""
    find_candidate(db, candidate_id)
    row = litmus_run.latest_of(db, candidate_id)
    return to_out(db, row) if row else None


@router.get("/candidates/{candidate_id}/litmus/history", response_model=list[HistoryItem])
def check_history(candidate_id: int, db: Session = Depends(get_db)):
    """Every check of this candidate, newest first. Earlier checks are never rewritten."""
    find_candidate(db, candidate_id)
    return [
        HistoryItem(
            id=row.id,
            status=row.status,
            outcome=(row.result or {}).get("outcome", ""),
            review_status=row.review_status,
            started_at=row.started_at,
            cost_usd=row.cost_usd,
        )
        for row in litmus_run.history_of(db, candidate_id)
    ]


@router.post("/litmus/{check_id}/review", response_model=LitmusOut)
def review_check(
    check_id: int,
    body: ReviewIn,
    db: Session = Depends(get_db),
    interviewer: Interviewer = Depends(current_interviewer),
):
    """A person acknowledges a flagged or inconclusive result with a note."""
    row = db.get(LitmusCheck, check_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Check not found.")
    return to_out(db, litmus_run.acknowledge(db, row, interviewer, body.note))


@router.post("/jobs/{job_id}/litmus", response_model=QueuedOut, status_code=status.HTTP_202_ACCEPTED)
def check_shortlist(job_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Queues checks for the top of the shortlist (LITMUS_SHORTLIST_SIZE) and runs them one by one."""
    check_ids = litmus_run.queue_shortlist(db, find_job(db, job_id), settings.litmus_shortlist_size)
    background.add_task(litmus_run.run_queue, check_ids)
    return QueuedOut(queued=len(check_ids), check_ids=check_ids)


@router.get("/jobs/{job_id}/litmus")
def job_summary(job_id: int, db: Session = Depends(get_db)) -> dict:
    """The job's pass rate, which kind of change moved scores most, and each checked candidate."""
    return litmus_run.job_summary(db, find_job(db, job_id))
