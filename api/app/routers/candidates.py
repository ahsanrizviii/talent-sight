from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import google_form
from app.cv_files import CVFileError, delete_cv_file
from app.db import get_db
from app.deps import current_interviewer
from app.google_api import GoogleError
from app.intake import add_cv
from app.models import Candidate, JobProfile, RequirementVerdict
from app.settings import settings

router = APIRouter(
    prefix="/api",
    tags=["candidates"],
    dependencies=[Depends(current_interviewer)],
)


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


class CandidateDetail(CandidateRow):
    job_profile_id: int
    phone: str
    profile: dict
    verdicts: list[VerdictOut]
    
class ImportResult(BaseModel):
    imported: int
    skipped: int
    failed: list[dict]

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
        select(RequirementVerdict)
        .where(RequirementVerdict.candidate_id == candidate_id)
        .order_by(RequirementVerdict.id)
    ).all()


def counts(verdicts: list[RequirementVerdict]) -> dict:
    return {
        name: sum(1 for v in verdicts if v.verdict == name)
        for name in ("met", "partially_met", "unmet")
    }


def to_row(db: Session, candidate: Candidate) -> CandidateRow:
    base = CandidateRow.model_validate(candidate).model_dump()
    return CandidateRow(**{**base, **counts(verdicts_of(db, candidate.id))})


def to_detail(db: Session, candidate: Candidate) -> CandidateDetail:
    verdicts = verdicts_of(db, candidate.id)
    base = to_row(db, candidate).model_dump()
    return CandidateDetail(
        **base,
        job_profile_id=candidate.job_profile_id,
        phone=candidate.phone,
        profile=candidate.profile,
        verdicts=[VerdictOut.model_validate(v) for v in verdicts],
    )


def ranking_key(item: CandidateRow):
    """Screened first, best match first; then excluded; then the rest."""
    group = {"screened": 0, "excluded": 1}.get(item.status, 2)
    return (group, -item.met, -item.partially_met, item.name.lower())



@router.post("/jobs/{job_id}/candidates", response_model=list[UploadResult])
def upload_cvs(
    job_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    
    job = find_job(db, job_id)
    if len(files) > settings.cv_max_files:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Upload at most {settings.cv_max_files} files at once.",
        )

    results = []
    for upload in files:
        
        data = upload.file.read(settings.cv_max_mb * 1024 * 1024 + 1)
        try:
            candidate = add_cv(db, job, upload.filename, data)
            db.commit()
            results.append(
                UploadResult(
                    filename=candidate.cv_filename,
                    ok=True,
                    candidate_id=candidate.id,
                )
            )
        except CVFileError as error:
            db.rollback()
            results.append(
                UploadResult(
                    filename=upload.filename or "",
                    ok=False,
                    error=str(error),
                )
            )
    return results

@router.post("/jobs/{job_id}/candidates/import", response_model=ImportResult)
def import_from_google_form(job_id: int, db: Session = Depends(get_db)):
    """Fetches the CVs sent through the Google Form for this job."""
    job = find_job(db, job_id)

    if not google_form.is_enabled():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The Google Form import is not set up.",
        )
    if job.status != "published":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Publish the job first: applicants need its link.",
        )

    try:
        return google_form.import_applications(db, job)
    except GoogleError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error))


@router.get("/jobs/{job_id}/candidates", response_model=list[CandidateRow])
def list_candidates(job_id: int, db: Session = Depends(get_db)):
    find_job(db, job_id)
    candidates = db.scalars(
        select(Candidate).where(Candidate.job_profile_id == job_id)
    ).all()
    return sorted((to_row(db, c) for c in candidates), key=ranking_key)


@router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
def get_candidate(candidate_id: int, db: Session = Depends(get_db)):
    return to_detail(db, find_candidate(db, candidate_id))


@router.delete("/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_candidate(candidate_id: int, db: Session = Depends(get_db)):

    candidate = find_candidate(db, candidate_id)
    delete_cv_file(candidate.cv_path)
    db.delete(candidate)
    db.commit()