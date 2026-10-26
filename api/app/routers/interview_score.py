"""The interview's own score in six parts (Module 13, F9). Interviewers only (N9).

It is kept apart from the CV score (Module 6) and never changes it, the assessment or the stage.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app import agent_runs, interview_scoring
from app.agent_runs import RunOut
from app.db import get_db
from app.deps import current_interviewer
from app.models import InterviewScore
from app.routers.interviews import find_session

router = APIRouter(prefix="/api", tags=["interview score"], dependencies=[Depends(current_interviewer)])


@router.post("/interviews/{session_id}/interview-score", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
def score_interview(session_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    row = agent_runs.start(db, InterviewScore, find_session(db, session_id), interview_scoring.FIRST_STEP)
    background.add_task(interview_scoring.run_scoring, row.id)
    return agent_runs.to_out(db, row)


@router.get("/interviews/{session_id}/interview-score", response_model=RunOut | None)
def get_interview_score(session_id: int, db: Session = Depends(get_db)):
    find_session(db, session_id)
    row = agent_runs.row_of(db, InterviewScore, session_id)
    return agent_runs.to_out(db, row) if row else None