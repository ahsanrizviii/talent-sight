"""How well an interview was run (Module 13, F10). Interviewers only; the candidate never sees it (N9)."""

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app import agent_runs, interview_quality
from app.agent_runs import RunOut
from app.db import get_db
from app.deps import current_interviewer
from app.models import InterviewQuality
from app.routers.interviews import find_session

router = APIRouter(prefix="/api", tags=["interview quality"], dependencies=[Depends(current_interviewer)])


@router.post("/interviews/{session_id}/quality", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
def review_interview(session_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Starts the review in the background and answers at once with status "running"."""
    row = agent_runs.start(db, InterviewQuality, find_session(db, session_id), interview_quality.FIRST_STEP)
    background.add_task(interview_quality.run_review, row.id)
    return agent_runs.to_out(db, row)


@router.get("/interviews/{session_id}/quality", response_model=RunOut | None)
def get_interview_quality(session_id: int, db: Session = Depends(get_db)):
    """The latest review, or null when nobody has asked for one yet. The screen polls this while it runs."""
    find_session(db, session_id)
    row = agent_runs.row_of(db, InterviewQuality, session_id)
    return agent_runs.to_out(db, row) if row else None