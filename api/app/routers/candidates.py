"""Candidates of a job: upload CVs, import them from the Google Form, screen them, see the results."""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import google_form
from app.cv_files import CVFileError, delete_cv_file
from app.db import get_db
from app.deps import current_interviewer
from app.google_api import GoogleError
from app.intake import add_cv
from app.models import Candidate, CandidateScore, JobProfile, RequirementVerdict, ScreeningRun
from app.screening import run_screening, start_run
from app.scoring import DIMENSIONS
from app.settings import settings

router = APIRouter(prefix="/api", tags=["candidates"], dependencies=[Depends(current_interviewer)])

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


# ---------- What the API sends back ----------


class UploadResult(BaseModel):
    filename: str
    ok: bool
    candidate_id: int | None = None
    error: str = ""


class VerdictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    requirement: str
    kind: str
    mandatory: bool
    verdict: str
    explanation: str


class CandidateRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    cv_filename: str
    source: str
    status: str
    text_method: str
    exclusion_reason: str
    error: str
    created_at: datetime
    met: int = 0
    partially_met: int = 0
    unmet: int = 0
    overall: float | None = None  # Module 6: the weighted total, 0-100
    rank: int | None = None  # Module 6: place in the shortlist (screened candidates only)


class DimensionOut(BaseModel):
    dimension: str
    label: str
    score: float
    weight: int
    contribution: float  # how many points of the total this dimension gives
    justification: str


class ScoreOut(BaseModel):
    overall: float
    dimensions: list[DimensionOut]


class CandidateDetail(CandidateRow):
    job_profile_id: int
    phone: str
    profile: dict
    cv_text: str  # the text read from the CV, shown next to the extracted profile
    verdicts: list[VerdictOut]
    score: ScoreOut | None = None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    total: int
    done: int
    failed: int
    started_at: datetime
    finished_at: datetime | None
    seconds: float | None


class ImportResult(BaseModel):
    imported: int
    skipped: int
    failed: list[dict]


# ---------- Helpers ----------


def find_job(db: Session, job_id: int) -> JobProfile:
    job = db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return job


def find_candidate(db: Session, candidate_id: int) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found.")
    return candidate


def verdicts_of(db: Session, candidate_id: int) -> list[RequirementVerdict]:
    return db.scalars(
        select(RequirementVerdict).where(RequirementVerdict.candidate_id == candidate_id).order_by(RequirementVerdict.id)
    ).all()


def counts(verdicts: list[RequirementVerdict]) -> dict:
    return {name: sum(1 for v in verdicts if v.verdict == name) for name in ("met", "partially_met", "unmet")}


def score_of(db: Session, candidate_id: int) -> CandidateScore | None:
    return db.scalar(select(CandidateScore).where(CandidateScore.candidate_id == candidate_id))


def to_row(db: Session, candidate: Candidate) -> CandidateRow:
    base = CandidateRow.model_validate(candidate).model_dump()
    score = score_of(db, candidate.id)
    overall = {"overall": score.overall} if score else {}
    return CandidateRow(**{**base, **counts(verdicts_of(db, candidate.id)), **overall})


def breakdown(score: CandidateScore, weights: dict) -> ScoreOut:
    """The score breakdown panel: each dimension, its weight and what it adds to the total (WBS 6.5)."""
    dimensions = [
        DimensionOut(
            dimension=d,
            label=label,
            score=getattr(score, d),
            weight=weights[d],
            contribution=round(getattr(score, d) * weights[d] / 100, 1),
            justification=(score.justification or {}).get(d, ""),
        )
        for d, label in DIMENSIONS.items()
    ]
    return ScoreOut(overall=score.overall, dimensions=dimensions)


def to_detail(db: Session, candidate: Candidate) -> CandidateDetail:
    verdicts = verdicts_of(db, candidate.id)
    base = to_row(db, candidate).model_dump()
    score = score_of(db, candidate.id)
    job = db.get(JobProfile, candidate.job_profile_id)
    return CandidateDetail(
        **base,
        job_profile_id=candidate.job_profile_id,
        phone=candidate.phone,
        profile=candidate.profile,
        cv_text=candidate.cv_text or "",
        verdicts=[VerdictOut.model_validate(v) for v in verdicts],
        score=breakdown(score, job.weights) if score else None,
    )


def ranking_key(item: CandidateRow):
    """Screened first, highest total score first (Q&A 46); then excluded; then the rest."""
    group = {"screened": 0, "excluded": 1}.get(item.status, 2)
    overall = item.overall if item.overall is not None else -1
    return (group, -overall, -item.met, item.name.lower())


# ---------- CV intake ----------


@router.post("/jobs/{job_id}/candidates", response_model=list[UploadResult])
def upload_cvs(job_id: int, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    """Batch upload (WBS 5.1). Every file is checked on its own; a bad file never stops the others."""
    job = find_job(db, job_id)
    if len(files) > settings.cv_max_files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Upload at most {settings.cv_max_files} files at once.")
    results = []
    for upload in files:
        data = upload.file.read(settings.cv_max_mb * 1024 * 1024 + 1)  # never read more than the limit + 1 byte
        try:
            candidate = add_cv(db, job, upload.filename, data)
            db.commit()
            results.append(UploadResult(filename=candidate.cv_filename, ok=True, candidate_id=candidate.id))
        except CVFileError as error:
            db.rollback()
            results.append(UploadResult(filename=upload.filename or "", ok=False, error=str(error)))
    return results


@router.post("/jobs/{job_id}/candidates/import", response_model=ImportResult)
def import_from_google_form(job_id: int, db: Session = Depends(get_db)):
    """Fetches the CVs sent through the Google Form for this job."""
    job = find_job(db, job_id)
    if not google_form.is_enabled():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The Google Form import is not set up.")
    if job.status != "published":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Publish the job first: applicants need its link.")
    try:
        return google_form.import_applications(db, job)
    except GoogleError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error))


# ---------- Screening ----------


@router.post("/jobs/{job_id}/screening", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
def start_screening(job_id: int, background: BackgroundTasks, again: bool = False, db: Session = Depends(get_db)):
    """Starts screening in the background and answers at once (N4). again=true re-screens everyone."""
    run, candidate_ids = start_run(db, find_job(db, job_id), again)
    background.add_task(run_screening, run.id, candidate_ids)
    return run


@router.get("/jobs/{job_id}/screening", response_model=RunOut | None)
def latest_screening(job_id: int, db: Session = Depends(get_db)):
    """The progress of the job's latest screening, or null if it never ran."""
    find_job(db, job_id)
    return db.scalar(select(ScreeningRun).where(ScreeningRun.job_profile_id == job_id).order_by(ScreeningRun.id.desc()))


# ---------- Results ----------


@router.get("/jobs/{job_id}/candidates", response_model=list[CandidateRow])
def list_candidates(job_id: int, db: Session = Depends(get_db)):
    find_job(db, job_id)
    candidates = db.scalars(select(Candidate).where(Candidate.job_profile_id == job_id)).all()
    rows = sorted((to_row(db, c) for c in candidates), key=ranking_key)
    for place, item in enumerate((r for r in rows if r.status == "screened"), start=1):
        item.rank = place  # the ranked shortlist
    return rows


@router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
def get_candidate(candidate_id: int, db: Session = Depends(get_db)):
    return to_detail(db, find_candidate(db, candidate_id))


@router.get("/candidates/{candidate_id}/cv")
def get_cv(candidate_id: int, db: Session = Depends(get_db)):
    """The original CV file. PDFs open in the browser; DOCX files are downloaded."""
    candidate = find_candidate(db, candidate_id)
    path = Path(candidate.cv_path) if candidate.cv_path else None
    if path is None or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The CV file is not stored any more.")
    return FileResponse(
        path,
        media_type=MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        filename=candidate.cv_filename,
        content_disposition_type="inline",
    )


@router.delete("/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_candidate(candidate_id: int, db: Session = Depends(get_db)):
    """Removes the candidate, their results and their CV file (N19)."""
    candidate = find_candidate(db, candidate_id)
    delete_cv_file(candidate.cv_path)
    db.delete(candidate)
    db.commit()