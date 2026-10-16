"""The consolidated assessment of a candidate (Module 10).

Interviewers only. The candidate never sees their own assessment (N9).
"""

import re
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import assessment
from app.db import get_db
from app.agents.screening_agent import requirements_of
from app.deps import current_interviewer
from app.models import Assessment, Candidate, InterviewSession, JobProfile
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




# ---------- Side-by-side comparison (Task 10.2.2) ----------


class ComparedCandidate(BaseModel):
    candidate_id: int
    name: str
    position: dict          # {"code", "label", "overall"}
    components: list[dict]  # [{"key", "label", "score"}]
    requirements: dict      # requirement text (lower case) -> {"cv", "interview", "best_score"}
    strengths: list[str]
    weaknesses: list[str]
    gaps: int
    must_have_gaps: int
    assessed_at: datetime | None
    outdated: bool


class Comparison(BaseModel):
    job_id: int
    job_title: str
    requirements: list[dict]  # [{"key", "requirement", "mandatory"}]: the rows of the comparison
    candidates: list[ComparedCandidate]  # best position first
    waiting: int  # interviewed candidates without a finished assessment yet


def key_of(text: str) -> str:
    return " ".join(text.lower().split())


@router.get("/jobs/{job_id}/assessments", response_model=Comparison)
def compare(job_id: int, db: Session = Depends(get_db)):
    """Every finished assessment of one job's candidates, ready to be shown side by side (F6)."""
    job = db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    rows = db.scalars(
        select(Assessment).join(Candidate).where(Candidate.job_profile_id == job_id, Assessment.status == "done")
    ).all()

    # The rows: the job's requirements in their usual order, then any other requirement a report mentions.
    requirements = [{"key": key_of(r["requirement"]), "requirement": r["requirement"], "mandatory": r["mandatory"]} for r in requirements_of(job)]
    known = {r["key"] for r in requirements}
    candidates = []
    for row in rows:
        report = row.report
        lines = {}
        for line in report["requirements"]:
            key = key_of(line["requirement"])
            lines[key] = {"cv": line["cv"], "interview": line["interview"], "best_score": line["best_score"]}
            if key not in known:
                known.add(key)
                requirements.append({"key": key, "requirement": line["requirement"], "mandatory": line["mandatory"]})
        candidates.append(ComparedCandidate(
            candidate_id=row.candidate_id,
            name=report["candidate"]["name"],
            position={k: report["position"][k] for k in ("code", "label", "overall")},
            components=[{k: c[k] for k in ("key", "label", "score")} for c in report["components"]],
            requirements=lines,
            strengths=[item["text"] for item in report["strengths"][:3]],
            weaknesses=[item["text"] for item in report["weaknesses"][:3]],
            gaps=len(report["gaps"]),
            must_have_gaps=sum(1 for gap in report["gaps"] if gap["mandatory"]),
            assessed_at=row.finished_at,
            outdated=assessment.is_outdated(db, row),
        ))
    candidates.sort(key=lambda c: (-c.position["overall"], c.name.lower()))

    assessed = {c.candidate_id for c in candidates}
    interviewed = db.scalars(
        select(InterviewSession.candidate_id).join(Candidate).where(Candidate.job_profile_id == job_id, InterviewSession.status == "ended")
    ).all()
    return Comparison(
        job_id=job.id,
        job_title=job.title,
        requirements=requirements,
        candidates=candidates,
        waiting=len(set(interviewed) - assessed),
    )