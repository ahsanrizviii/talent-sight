from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import JobProfile
from app.settings import settings

router = APIRouter(prefix="/api/public", tags=["public"])


class PublicJobSummary(BaseModel):
    slug: str
    title: str
    min_experience_years: int


class PublicJob(BaseModel):

    title: str
    description: str
    required_skills: list[str]
    preferred_skills: list[str]
    qualifications: list[str]
    min_experience_years: int
    apply_email: str


@router.get("/jobs", response_model=list[PublicJobSummary])
def list_published_jobs(db: Session = Depends(get_db)):
    jobs = db.scalars(
        select(JobProfile)
        .where(JobProfile.status == "published")
        .order_by(JobProfile.title)
    )
    return [
        PublicJobSummary(
            slug=j.slug,
            title=j.title,
            min_experience_years=j.min_experience_years,
        )
        for j in jobs
    ]


@router.get("/jobs/{slug}", response_model=PublicJob)
def read_published_job(slug: str, db: Session = Depends(get_db)):
    job = db.scalar(
        select(JobProfile).where(
            JobProfile.slug == slug,
            JobProfile.status == "published",
        )
    )
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This job post does not exist.")

    return PublicJob(
        title=job.title,
        description=job.description,
        required_skills=job.required_skills,
        preferred_skills=job.preferred_skills,
        qualifications=job.qualifications,
        min_experience_years=job.min_experience_years,
        apply_email=settings.careers_email,
    )