import re
from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.blogger import blog_url_for
from app.round_info import type_or_guess
from app.models import DEFAULT_ROUNDS, DEFAULT_WEIGHTS, JobProfile


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

MAX_ROUNDS = 6


class InterviewRound(BaseModel):
    """One round of the hiring process, for example "HR interview" or "Technical round 1"."""

    name: str = Field(min_length=1, max_length=80)
    focus: str = Field(default="", max_length=300)  # what this round covers, in a few words
    # technical = judged on the job's requirements; hr = judged on HR topics (communication, motivation ...)
    type: Literal["technical", "hr"] = "technical"

    @model_validator(mode="before")
    @classmethod
    def type_from_name(cls, data):
        """A round sent or saved without a type (older jobs, older screens) gets one from its name."""
        if isinstance(data, dict) and str(data.get("type") or "").strip().lower() not in ("technical", "hr"):
            data = {**data, "type": type_or_guess(data)}
        return data


def default_rounds() -> list[InterviewRound]:
    return [InterviewRound(**item) for item in DEFAULT_ROUNDS]

class JobIn(BaseModel):

    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=20000)
    required_skills: list[Item] = Field(min_length=1, max_length=10)
    preferred_skills: list[Item] = Field(default_factory=list, max_length=15)
    qualifications: list[Item] = Field(default_factory=list, max_length=10)
    min_experience_years: int = Field(default=0, ge=0, le=40)
    selection_criteria: str = Field(default="", max_length=2000)
    weights: Weights = Field(default_factory=Weights)
    # The interview rounds, in order. Every job has at least one.
    interview_rounds: list[InterviewRound] = Field(default_factory=default_rounds, min_length=1, max_length=MAX_ROUNDS)


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
