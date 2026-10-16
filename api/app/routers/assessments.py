"""The consolidated assessment of a candidate (Module 10).

Interviewers only. The candidate never sees their own assessment (N9).
"""

import re
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import assessment
from app.db import get_db
from app.deps import current_interviewer
from app.models import Assessment, Candidate
from app.report_pdf import build_pdf

router = APIRouter(prefix="/api", tags=["assessment"], dependencies=[Depends(current_interviewer)])


class AssessmentOut(BaseModel):
    candidate_id: int
    status: str  # running | done | failed
    step: str    # what the agent is doing now, while it runs
    error: str
    started_at: datetime
    finished_at: datetime | None
    seconds: float | None
    outdated: bool  # the interview answers were analysed again after this report was made
    report: dict    # position, components, requirements, gaps, findings and the numbered evidence


def to_out(db: Session, row: Assessment) -> AssessmentOut:
    return AssessmentOut(
        candidate_id=row.candidate_id,
        status=row.status,
        step=row.step,
        error=row.error,
        started_at=row.created_at,
        finished_at=row.finished_at,
        seconds=row.seconds,
        outdated=assessment.is_outdated(db, row),
        report=row.report or {},
    )


def find_candidate(db: Session, candidate_id: int) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found.")
    return candidate


@router.post("/candidates/{candidate_id}/assessment", response_model=AssessmentOut, status_code=status.HTTP_202_ACCEPTED)
def assess(candidate_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Starts the assessment in the background and answers at once with status "running"."""
    row = assessment.start_assessment(db, find_candidate(db, candidate_id))
    background.add_task(assessment.run_assessment, row.id)
    return to_out(db, row)


@router.get("/candidates/{candidate_id}/assessment", response_model=AssessmentOut | None)
def get_assessment(candidate_id: int, db: Session = Depends(get_db)):
    """The latest assessment, or null when nobody has asked for one yet. The screen polls this while it runs."""
    find_candidate(db, candidate_id)
    row = assessment.assessment_of(db, candidate_id)
    return to_out(db, row) if row else None




@router.get("/candidates/{candidate_id}/assessment/pdf")
def assessment_pdf(candidate_id: int, db: Session = Depends(get_db)):
    """The finished report as a PDF file to save, print or attach (Task 10.2.1)."""
    find_candidate(db, candidate_id)
    row = assessment.assessment_of(db, candidate_id)
    if row is None or row.status != "done":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "There is no finished assessment to export yet.")
    # A plain file name: letters and digits only, e.g. assessment-maya-rahman.pdf
    name = re.sub(r"[^a-z0-9]+", "-", row.report["candidate"]["name"].lower()).strip("-") or str(candidate_id)
    return Response(
        build_pdf(row.report, row.finished_at),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="assessment-{name}.pdf"'},
    )