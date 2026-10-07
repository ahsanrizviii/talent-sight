from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import blogger
from app.db import get_db
from app.deps import current_interviewer
from app.job_profiles import JobIn, JobOut, publish_job_post
from app.models import JobProfile

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

@router.put("/{job_id}", response_model=JobOut)
def update_job(job_id: int, body: JobIn, db: Session = Depends(get_db)):
    job = find_job(db, job_id)
    for field, value in body.model_dump().items():
        setattr(job, field, value)
    db.commit()
    db.refresh(job)
    return job

@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = find_job(db, job_id)
    blogger.remove_job(job.slug) 
    db.delete(job)  
    db.commit()

@router.post("/{job_id}/publish", response_model=JobOut)
def publish_job(job_id: int, db: Session = Depends(get_db)):
    job = find_job(db, job_id)
    already_published = job.status == "published"
    publish_job_post(job)
    db.commit()
    db.refresh(job)
    if not already_published:  
        blogger.post_job(job)
    return job
