"""The answer analysis of an interview (Module 9, Task 9.2.2).

Interviewers only. The candidate never sees their own scores or transcript (N9).
"""

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import evaluation
from app.db import get_db
from app.deps import current_interviewer
from app.models import InterviewEvaluation, InterviewSession

router = APIRouter(prefix="/api", tags=["evaluation"], dependencies=[Depends(current_interviewer)])


class EvaluationOut(BaseModel):
    session_id: int
    status: str  # running | done | failed
    step: str    # what the agent is doing now, while it runs
    error: str
    started_at: datetime
    finished_at: datetime | None
    seconds: float | None
    turns: list[dict]     # the transcript turns the pairs point to
    pairs: list[dict]     # question-answer pairs with kind, requirements, scores and evidence
    coverage: list[dict]  # every job requirement: explored, weak or not_explored
    summary: dict


def to_out(row: InterviewEvaluation) -> EvaluationOut:
    result = row.result or {}
    return EvaluationOut(
        session_id=row.session_id,
        status=row.status,
        step=row.step,
        error=row.error,
        started_at=row.started_at,
        finished_at=row.finished_at,
        seconds=row.seconds,
        turns=result.get("turns", []),
        pairs=result.get("pairs", []),
        coverage=result.get("coverage", []),
        summary=result.get("summary", {}),
    )


def find_session(db: Session, session_id: int) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Interview not found.")
    return session


@router.post("/interviews/{session_id}/evaluation", response_model=EvaluationOut, status_code=status.HTTP_202_ACCEPTED)
def analyse_answers(session_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Starts the analysis in the background and answers at once with status "running" (Q&A 42)."""
    row = evaluation.start_evaluation(db, find_session(db, session_id))
    background.add_task(evaluation.run_evaluation, row.id)
    return to_out(row)


@router.get("/interviews/{session_id}/evaluation", response_model=EvaluationOut | None)
def get_analysis(session_id: int, db: Session = Depends(get_db)):
    """The latest analysis, or null when nobody has asked for one yet. The screen polls this while it runs."""
    find_session(db, session_id)
    row = db.scalar(select(InterviewEvaluation).where(InterviewEvaluation.session_id == session_id))
    return to_out(row) if row else None