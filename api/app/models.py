from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, func, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DEFAULT_WEIGHTS = {"technical_skills": 40, "experience": 30, "qualifications": 15, "jd_match": 15}


class Base(DeclarativeBase):
    pass


class Interviewer(Base):

    __tablename__ = "interviewers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InterviewerProfile(Base):
    """The name a hiring team member signed up with (UI refresh).

    A new table, not a new column on `interviewers`: create_all makes new tables but never
    new columns, so adding a column here would never reach an existing database.
    """

    __tablename__ = "interviewer_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    interviewer_id: Mapped[int] = mapped_column(ForeignKey("interviewers.id", ondelete="CASCADE"), unique=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobProfile(Base):

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
    status: Mapped[str] = mapped_column(String(20), default="draft")  
    slug: Mapped[str | None] = mapped_column(String(250), unique=True)  
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JdChat(Base):
    """One "Write a job with AI" conversation, kept so the team can read it back (UI refresh).

    The agent's own memory lives in LangGraph's checkpoint tables and is not meant for reading.
    This table is the human record: who asked for what, what the AI asked back, and which job
    came out of it.
    """

    __tablename__ = "jd_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    brief: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="waiting")  # waiting | done | failed
    job_id: Mapped[int | None] = mapped_column(ForeignKey("job_profiles.id", ondelete="SET NULL"))
    messages: Mapped[list] = mapped_column(JSON, default=list)  # [{"role": ..., "text": ..., "at": ...}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PolicyChunk(Base):

    __tablename__ = "policy_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(384))


class Candidate(Base):
    """One applicant for one job: their CV file, its text, and what the screening found (Module 5)."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_profile_id: Mapped[int] = mapped_column(
        ForeignKey("job_profiles.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    source: Mapped[str] = mapped_column(String(20), default="upload")  # upload | google_form

    # For Google Form CVs: the form response and Drive file, so the same CV is never imported twice
    source_ref: Mapped[str | None] = mapped_column(String(255), unique=True)
    cv_filename: Mapped[str] = mapped_column(String(255))  # the name the file had when it arrived
    cv_path: Mapped[str] = mapped_column(String(500), default="")  # where we stored it, on the cv_uploads volume
    cv_text: Mapped[str] = mapped_column(Text, default="")
    text_method: Mapped[str] = mapped_column(String(10), default="")  # text | ocr
    profile: Mapped[dict] = mapped_column(JSON, default=dict)  # the structured CV the AI extracted

    # uploaded -> screened or excluded; unreadable = no text in the file; failed = the AI step failed
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    exclusion_reason: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RequirementVerdict(Base):
    """Met / Partially Met / Unmet for one requirement of one candidate (Module 5)."""

    __tablename__ = "requirement_verdicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
    requirement: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))  # skill | preferred | qualification | experience
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    verdict: Mapped[str] = mapped_column(String(20))  # met | partially_met | unmet
    explanation: Mapped[str] = mapped_column(Text, default="")


class ScreeningRun(Base):
    """One background screening of a job's CVs, with its progress and how long it took (Module 5)."""

    __tablename__ = "screening_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_profile_id: Mapped[int] = mapped_column(
        ForeignKey("job_profiles.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | interrupted
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seconds: Mapped[float | None] = mapped_column (Float)

class CandidateScore(Base):

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

    __tablename__ = "interview_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    invite_token: Mapped[str] = mapped_column(String(64), unique=True)
    invite_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled | live | ended
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class SessionParticipant(Base):
    """Who was in an interview and when (Module 7).

    Only the role and the times are stored. Raw audio and video are never saved (Q&A 7).
    A person who leaves and comes back gets a new row, so the history stays honest.
    """

    __tablename__ = "session_participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))  # interviewer | candidate
    identity: Mapped[str] = mapped_column(String(100))  # the name used in the video room, e.g. candidate-7
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TranscriptSegment(Base):

    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"))
    speaker: Mapped[str] = mapped_column(String(20))  # interviewer | candidate
    text: Mapped[str] = mapped_column(Text)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)


class Assessment(Base):

    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    overall_position: Mapped[str] = mapped_column(String(30))
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())