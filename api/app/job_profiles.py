import re
from datetime import datetime
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.blogger import blog_url_for
from app.models import DEFAULT_WEIGHTS, JobProfile


class Weights(BaseModel):

    technical_skills: int = Field(DEFAULT_WEIGHTS["technical_skills"], ge=0, le=100)
    experience: int = Field(DEFAULT_WEIGHTS["experience"], ge=0, le=100)
    qualifications: int = Field(DEFAULT_WEIGHTS["qualifications"], ge=0, le=100)
    jd_match: int = Field(DEFAULT_WEIGHTS["jd_match"], ge=0, le=100)

    @model_validator(mode="after")
    def must_add_up_to_100(self):
        total = self.technical_skills + self.experience + self.qualifications + self.jd_match
        if total != 100:
            raise ValueError(f"The four weights must add up to 100 (now {total}).")
        return self

# One skill or qualification: not empty, and short enough to be one item, not a pasted paragraph (N8).
Item = Annotated[str, Field(min_length=1, max_length=200)]

class JobIn(BaseModel):

    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=20000)
    required_skills: list[Item] = Field(min_length=1, max_length=10)
    preferred_skills: list[Item] = Field(default_factory=list, max_length=15)
    qualifications: list[Item] = Field(default_factory=list, max_length=10)
    min_experience_years: int = Field(default=0, ge=0, le=40)
    selection_criteria: str = Field(default="", max_length=2000)
    weights: Weights = Field(default_factory=Weights)


class JobOut(JobIn):

    model_config = ConfigDict(from_attributes=True) 

    id: int
    status: str
    slug: str | None
    created_at: datetime
    policy_sources: list[str] = []  # the hiring-policy documents the AI followed; [] = all of them

    @computed_field
    @property
    def blog_url(self) -> str | None:
        return blog_url_for(self.slug) if self.status == "published" else None


def publish_job_post(job: JobProfile) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", job.title.lower()).strip("-")
    job.slug = f"{words}-{job.id}"
    job.status = "published"
    return job.slug
