from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
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

class ReferenceChunk(Base):
    """One section of the skills reference documents in api/knowledge/skills/ (Module 9).

    The Evaluation Agent compares interview answers with these sections, so an accuracy score
    rests on written documentation and not only on the language model's memory (Q&A 10).
    """

    __tablename__ = "reference_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(200))   # the file name, e.g. python.md
    skill: Mapped[str] = mapped_column(String(200))    # the document title, e.g. Python
    heading: Mapped[str] = mapped_column(String(300))  # the section heading
    url: Mapped[str] = mapped_column(Text, default="")  # the "Sources:" line of the document
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
    # How long this interview is booked for (1 hour for every new interview). Empty for interviews
    # made before this column existed: those use INTERVIEW_MINUTES. (Added to old databases by init_db.)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
    """The consolidated assessment of one candidate (Module 10).

    One row per candidate; assessing again replaces it. The report is kept as JSON: the position,
    the component scores, the requirement lines, the gaps, the findings and the numbered evidence.
    The columns from status down were added in Module 10; init_db adds them to older databases.
    """

    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    overall_position: Mapped[str] = mapped_column(String(30), default="")  # strong_fit | possible_fit | weak_fit
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())  # when it started
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | failed
    step: Mapped[str] = mapped_column(String(200), default="")  # what the agent is doing now, for the screen
    error: Mapped[str] = mapped_column(Text, default="")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seconds: Mapped[float | None] = mapped_column(Float)

class ClaimCheck(Base):
    """CV claims checked against what the candidate said in the interview (Module 13, F8).

    One row per candidate; checking again replaces it. A new table, so create_all makes it in an
    existing database. It is only advice for a person: it never changes the score or the position.
    """

    __tablename__ = "claim_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), unique=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("interview_sessions.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | failed
    step: Mapped[str] = mapped_column(String(200), default="")  # what the agent is doing now, for the screen
    error: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)  # {"claims", "summary", "turns"}
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seconds: Mapped[float | None] = mapped_column(Float)

class InterviewChatMessage(Base):
    """One message in the interviewer's question chat for an interview (Module 13).

    Interviewer only: the candidate never sees it (N9). It is deleted with the interview, and so with
    the candidate (N19). A new table, so create_all makes it in an existing database.
    """

    __tablename__ = "interview_chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # interviewer | assistant
    text: Mapped[str] = mapped_column(Text)
    # The assistant's suggested questions: [{"question", "why", "source": {...}}]
    suggestions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class InterviewQuality(Base):
    """How well one interview was run (Module 13, F10): talk time, questions, coverage and advice.

    One row per interview; reviewing again replaces it. Advice for the hiring team only: it never
    changes the candidate's score, assessment or stage. A new table, so create_all makes it.
    """

    __tablename__ = "interview_quality"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | failed
    step: Mapped[str] = mapped_column(String(200), default="")  # what the agent is doing now, for the screen
    error: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seconds: Mapped[float | None] = mapped_column(Float)


class InterviewScore(Base):
    """The interview's own score in six parts (Module 13, F9), kept apart from the CV score (Module 6).

    One row per interview; scoring again replaces it. A new table, so create_all makes it.
    """

    __tablename__ = "interview_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | failed
    step: Mapped[str] = mapped_column(String(200), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)  # {"dimensions", "overall", "answers"}
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seconds: Mapped[float | None] = mapped_column(Float)

class IdentityRecord(Base):
    """The identity check of one interview (Module 13, F7): the photo ID seen on camera, and consent.

    consent is None until the candidate answers. Interviewer only (N9); deleted with the candidate (N19).
    """

    __tablename__ = "identity_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    consent: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    id_checked: Mapped[bool] = mapped_column(Boolean, default=False)    # the interviewer saw a photo ID on camera
    name_matches: Mapped[bool] = mapped_column(Boolean, default=False)  # the name on it matches the CV
    checked_by: Mapped[str] = mapped_column(String(255), default="")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FaceTemplate(Base):
    """One face template: 128 numbers made from one camera frame. Never a picture (N16, N17).

    Kept only with consent, and deleted after the onboarding check, after BIOMETRIC_RETENTION_DAYS,
    on request, and with the candidate (N19).
    """

    __tablename__ = "face_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"))
    slot: Mapped[int] = mapped_column(Integer)  # 1, 2 or 3: early, middle and later in the interview
    vector: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OnboardingCheck(Base):
    """The onboarding-day check of one new hire (Module 13, F7, Task 13.5.3).

    A result other than "match" waits for a person's decision. Nothing is ever called fraud automatically.
    """

    __tablename__ = "onboarding_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="waiting")  # waiting (for the head turn) | done
    direction: Mapped[str] = mapped_column(String(10), default="")     # left | right: the head turn asked for
    challenge_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_id_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome: Mapped[str] = mapped_column(String(20), default="")       # match | low_confidence | no_templates
    best_score: Mapped[float | None] = mapped_column(Float)
    checked_by: Mapped[str] = mapped_column(String(255), default="")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision: Mapped[str] = mapped_column(String(20), default="")      # "" | confirmed | not_confirmed
    decision_note: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[str] = mapped_column(String(255), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class CalendarEvent(Base):
    """The Google Calendar entry of one interview, kept so that moving or cancelling the interview
    changes that same entry instead of leaving a stale one behind.

    A table of its own rather than a column on interview_sessions: create_all makes new tables
    but never adds columns to existing ones.
    """

    __tablename__ = "calendar_events"

    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255))
    calendar_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobVisit(Base):
    """When a hiring team member last opened a job, so the job page can say how many CVs are new.

    seen_at is the latest visit; previous_seen_at the one before it. "New" means arrived after
    previous_seen_at. Opening the page again within a minute counts as the same visit (a refresh
    must not wipe the notice).
    """

    __tablename__ = "job_visits"
    __table_args__ = (UniqueConstraint("interviewer_id", "job_profile_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    interviewer_id: Mapped[int] = mapped_column(ForeignKey("interviewers.id", ondelete="CASCADE"))
    job_profile_id: Mapped[int] = mapped_column(ForeignKey("job_profiles.id", ondelete="CASCADE"))
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    previous_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CompanyProfile(Base):
    """The company that uses this TalentSight: its name and who candidates can contact.

    One row (id 1), filled in once in the sign-up form of the first person who signs up.
    Empty fields fall back to .env (COMPANY_NAME), so a fresh install still works before that.
    """

    __tablename__ = "company_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_name: Mapped[str] = mapped_column(String(120), default="")
    sender_name: Mapped[str] = mapped_column(String(120), default="")  # the name shown in "From"
    contact_name: Mapped[str] = mapped_column(String(120), default="")  # who answers candidates' questions
    contact_email: Mapped[str] = mapped_column(String(255), default="")  # replies go here
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Holiday(Base):
    """A day with no interviews: a public holiday.

    Read from the government's holiday calendar PDF in the knowledge/holidays folder when the API
    starts (holiday_calendar.load_holiday_calendars). The interview planner never books a slot on
    one of these days. Weekends (Saturday and Sunday) are not stored here: they are fixed in settings.
    """

    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(10), default="manual")  # manual | pdf
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HolidaySource(Base):
    """A holiday calendar PDF that was read from the knowledge/holidays folder.

    The file's fingerprint (sha256) is kept, so the same file is not read again at every start,
    and a changed file is read again. error is set when reading failed (it is tried again next start).
    """

    __tablename__ = "holiday_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(200), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    holidays_found: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class InviteBatch(Base):
    """One "invite the top candidates" action: many interviews booked and e-mailed together."""

    __tablename__ = "invite_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_profile_id: Mapped[int] = mapped_column(ForeignKey("job_profiles.id", ondelete="CASCADE"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("interviewers.id", ondelete="SET NULL"), nullable=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InviteDelivery(Base):
    """Whether the invitation of one interview in a batch has gone out (sent in the background)."""

    __tablename__ = "invite_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("invite_batches.id", ondelete="CASCADE"))
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | sent | failed
    error: Mapped[str] = mapped_column(Text, default="")
    calendar_error: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HolidayChunk(Base):
    """One piece of a holiday calendar PDF, with its embedding (RAG, like policy_chunks).

    The most relevant pieces are given to the AI to list the holidays. The planner never reads
    these: it only uses the saved holiday list.
    """

    __tablename__ = "holiday_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(200))  # the PDF's file name
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(384))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())



class InterviewEvaluation(Base):
    """The Evaluation Agent's analysis of one interview's answers (Module 9).

    One row per interview. Running it again replaces the result. The result is kept as JSON:
    the transcript turns it used, the question-answer pairs with their scores and evidence, and
    the requirement coverage, so Module 10 can read the whole analysis in one place.
    """

    __tablename__ = "interview_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | failed
    step: Mapped[str] = mapped_column(String(200), default="")  # what the agent is doing now, for the screen
    error: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)  # {"turns", "pairs", "coverage", "summary"}
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seconds: Mapped[float | None] = mapped_column(Float)