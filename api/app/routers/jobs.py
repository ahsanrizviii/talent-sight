from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import blogger, job_visits, privacy
from app.db import get_db
from app.deps import current_interviewer
from app.job_profiles import JobIn, JobOut, publish_job_post
from app.models import Candidate, Interviewer, InterviewSession, JobProfile
from app.scoring import rescore_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(current_interviewer)])

def find_job(db: Session, job_id: int) -> JobProfile:
    job = db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return job

@router.get("", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db)):
    return db.scalars(select(JobProfile).order_by(JobProfile.created_at.desc())).all()

@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(body: JobIn, db: Session = Depends(get_db)):
    job = JobProfile(**body.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)  
    return job

@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    return find_job(db, job_id)

def highest_round_used(db: Session, job_id: int) -> int:
    """The last round that already has an interview booked or held (0 = none)."""
    found = db.scalar(
        select(InterviewSession.round_number)
        .join(Candidate, InterviewSession.candidate_id == Candidate.id)
        .where(Candidate.job_profile_id == job_id)
        .order_by(InterviewSession.round_number.desc())
        .limit(1)
    )
    return found or 0


@router.put("/{job_id}", response_model=JobOut)
def update_job(job_id: int, body: JobIn, db: Session = Depends(get_db)):
    job = find_job(db, job_id)
    used = highest_round_used(db, job_id)
    if len(body.interview_rounds) < used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Round {used} already has interviews, so the job needs at least {used} rounds.",
        )
    for field, value in body.model_dump().items():
        setattr(job, field, value)
    db.commit()
    rescore_job(db, job)  # new weights: every candidate's total and the ranking follow at once
    db.refresh(job)
    return job

@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = find_job(db, job_id)
    blogger.remove_job(job.slug) 
    privacy.delete_job_candidates(db, job)  # their CV files and calendar entries go too (N19)
    db.delete(job)  
    db.commit()

@router.post("/{job_id}/publish", response_model=JobOut)
def publish_job(job_id: int, db: Session = Depends(get_db)):
    """Publishes the job and posts it on the blog. Publishing a job that is already on the blog
    replaces its post with the job as it is now (the old post is removed first, by its label)."""
    job = find_job(db, job_id)
    old_slug = job.slug if job.status == "published" else None
    publish_job_post(job)
    db.commit()
    db.refresh(job)
    if old_slug:
        blogger.remove_job(old_slug)  # the title may have changed, so the old label is used
    blogger.post_job(job)
    return job


@router.post("/{job_id}/visit", response_model=job_visits.VisitOut)
def visit_job(job_id: int, db: Session = Depends(get_db), interviewer: Interviewer = Depends(current_interviewer)):
    """Called when the job page opens: how many CVs are new since this person's last visit."""
    find_job(db, job_id)
    return job_visits.record_visit(db, interviewer.id, job_id)
