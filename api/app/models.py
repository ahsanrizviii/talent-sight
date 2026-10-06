from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# How strongly each part counts in the final CV score, in percent (adds up to 100).
DEFAULT_WEIGHTS = {"technical_skills": 40, "experience": 30, "qualifications": 15, "jd_match": 15}


class Base(DeclarativeBase):
    pass


class Interviewer(Base):
    """The only kind of user account. Candidates never get an account (Q&A 18)."""

    __tablename__ = "interviewers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobProfile(Base):
    """A job: its requirements, its scoring weights and its public job post."""

    __tablename__ = "job_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    required_skills: Mapped[list] = mapped_column(JSON, default=list)
    preferred_skills: Mapped[list] = mapped_column(JSON, default=list)
    qualifications: Mapped[list] = mapped_column(JSON, default=list)
    min_experience_years: Mapped[int] = mapped_column(Integer, default=0)
    selection_criteria: Mapped[str] = mapped_column(Text, default="")
    weights: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_WEIGHTS))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | published
    slug: Mapped[str | None] = mapped_column(String(250), unique=True)  # web address part, set on publish
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PolicyChunk(Base):
    """One paragraph of a company hiring policy, with its embedding (Module 4)."""

    __tablename__ = "policy_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(384))


class Candidate(Base):
    """One applicant for one job, with the text read from their CV (Module 5)."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_profile_id: Mapped[int] = mapped_column(ForeignKey("job_profiles.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    cv_filename: Mapped[str] = mapped_column(String(255))
    cv_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RequirementVerdict(Base):
    """Met / Partially Met / Unmet for one requirement of one candidate (Module 5)."""

    __tablename__ = "requirement_verdicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    requirement: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(String(20))  # met | partially_met | unmet
    explanation: Mapped[str] = mapped_column(Text, default="")


class CandidateScore(Base):
    """The 0-100 scores of one candidate (Module 6)."""

    __tablename__ = "candidate_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), unique=True)
    technical_skills: Mapped[float] = mapped_column(Float)
    experience: Mapped[float] = mapped_column(Float)
    qualifications: Mapped[float] = mapped_column(Float)
    jd_match: Mapped[float] = mapped_column(Float)
    overall: Mapped[float] = mapped_column(Float)
    justification: Mapped[dict] = mapped_column(JSON, default=dict)


class InterviewSession(Base):
    """One scheduled interview, with the candidate's private invite token (Modules 3 and 7)."""

    __tablename__ = "interview_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    invite_token: Mapped[str] = mapped_column(String(64), unique=True)
    invite_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled | live | ended
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TranscriptSegment(Base):
    """One finished sentence of the interview: who said it and when (Module 8)."""

    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"))
    speaker: Mapped[str] = mapped_column(String(20))  # interviewer | candidate
    text: Mapped[str] = mapped_column(Text)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)


class Assessment(Base):
    """The final report for one candidate (Module 10)."""

    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    overall_position: Mapped[str] = mapped_column(String(30))
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())