"""The views that look across every job at once (UI refresh).

Until now every list belonged to one job, so finding a candidate meant remembering which job
they applied for. These endpoints answer the questions a hiring team actually asks:
who is in the pipeline, what needs doing today, and which interviews are coming up.

Everything here is read-only, and it is built from the tables the other modules already fill.
Each list is loaded with a handful of grouped queries instead of one query per candidate,
so a long list stays fast.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_interviewer
from app.models import (
    Candidate,
    CandidateScore,
    InterviewSession,
    JobProfile,
    RequirementVerdict,
    TranscriptSegment,
)

router = APIRouter(prefix="/api/workspace", tags=["workspace"], dependencies=[Depends(current_interviewer)])

# Where a candidate stands. One word per candidate, so a whole pipeline can be read down a column.
STAGES = ("new", "screened", "excluded", "interview", "interviewed", "problem")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- What the API sends back ----------


class PersonRow(BaseModel):
    """One candidate, with everything the list and its filters need."""

    id: int
    name: str
    email: str
    cv_filename: str
    source: str
    status: str
    stage: str
    created_at: datetime
    job_id: int
    job_title: str
    met: int = 0
    partially_met: int = 0
    unmet: int = 0
    overall: float | None = None
    rank: int | None = None  # place inside their own job's shortlist
    interview_id: int | None = None
    interview_status: str = ""  # scheduled | live | ended
    interview_at: datetime | None = None
    transcript_lines: int = 0


class InterviewRow(BaseModel):
    id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    scheduled_at: datetime
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None
    transcript_lines: int = 0
    overdue: bool = False  # the start time has passed and nobody ever joined


class JobRow(BaseModel):
    id: int
    title: str
    status: str
    created_at: datetime
    blog_url: str | None = None
    required_skills: list[str] = []
    candidates: int = 0
    screened: int = 0
    waiting: int = 0  # CVs that have not been screened yet
    interviews: int = 0
    top_score: float | None = None


class TodoItem(BaseModel):
    """One thing worth doing next, with the page that does it."""

    text: str
    action: str
    to: str
    tone: str = "normal"  # normal | warn


class FunnelStep(BaseModel):
    label: str
    value: int


class Overview(BaseModel):
    jobs_open: int
    jobs_total: int
    candidates_total: int
    waiting_to_screen: int
    passed_screening: int
    interviews_upcoming: int
    interviews_done: int
    average_score: float | None
    funnel: list[FunnelStep]
    todo: list[TodoItem]
    upcoming: list[InterviewRow]
    top_candidates: list[PersonRow]


# ---------- Loading the pieces, once each ----------


def verdict_counts(db: Session) -> dict[int, dict[str, int]]:
    rows = db.execute(
        select(RequirementVerdict.candidate_id, RequirementVerdict.verdict, func.count())
        .group_by(RequirementVerdict.candidate_id, RequirementVerdict.verdict)
    ).all()
    counts: dict[int, dict[str, int]] = {}
    for candidate_id, verdict, total in rows:
        counts.setdefault(candidate_id, {})[verdict] = total
    return counts


def scores(db: Session) -> dict[int, float]:
    rows = db.execute(select(CandidateScore.candidate_id, CandidateScore.overall)).all()
    return {candidate_id: overall for candidate_id, overall in rows}


def transcript_lines(db: Session) -> dict[int, int]:
    rows = db.execute(
        select(TranscriptSegment.session_id, func.count()).group_by(TranscriptSegment.session_id)
    ).all()
    return {session_id: total for session_id, total in rows}


def latest_interviews(db: Session) -> dict[int, InterviewSession]:
    """The newest interview of each candidate: that is the one a hiring team cares about."""
    newest: dict[int, InterviewSession] = {}
    for session in db.scalars(select(InterviewSession).order_by(InterviewSession.id)).all():
        newest[session.candidate_id] = session
    return newest


def stage_of(candidate: Candidate, session: InterviewSession | None) -> str:
    if candidate.status in ("unreadable", "failed"):
        return "problem"
    if session is not None:
        return "interviewed" if session.status == "ended" else "interview"
    if candidate.status == "excluded":
        return "excluded"
    if candidate.status == "screened":
        return "screened"
    return "new"


def seconds_between(session: InterviewSession) -> int | None:
    if session.started_at is None or session.ended_at is None:
        return None
    return int((session.ended_at - session.started_at).total_seconds())


def people_rows(db: Session) -> list[PersonRow]:
    """Every candidate of every job, ranked inside their own job."""
    pairs = db.execute(
        select(Candidate, JobProfile.title).join(JobProfile, Candidate.job_profile_id == JobProfile.id)
    ).all()
    counts = verdict_counts(db)
    overalls = scores(db)
    sessions = latest_interviews(db)
    lines = transcript_lines(db)

    rows = []
    for candidate, job_title in pairs:
        session = sessions.get(candidate.id)
        mine = counts.get(candidate.id, {})
        rows.append(
            PersonRow(
                id=candidate.id,
                name=candidate.name or candidate.cv_filename,
                email=candidate.email,
                cv_filename=candidate.cv_filename,
                source=candidate.source,
                status=candidate.status,
                stage=stage_of(candidate, session),
                created_at=candidate.created_at,
                job_id=candidate.job_profile_id,
                job_title=job_title,
                met=mine.get("met", 0),
                partially_met=mine.get("partially_met", 0),
                unmet=mine.get("unmet", 0),
                overall=overalls.get(candidate.id),
                interview_id=session.id if session else None,
                interview_status=session.status if session else "",
                interview_at=session.scheduled_at if session else None,
                transcript_lines=lines.get(session.id, 0) if session else 0,
            )
        )

    # The rank is the candidate's place in their own job's shortlist, highest score first.
    for job_id in {row.job_id for row in rows}:
        shortlist = [r for r in rows if r.job_id == job_id and r.overall is not None and r.status != "excluded"]
        shortlist.sort(key=lambda r: (-(r.overall or 0), -r.met, r.name.lower()))
        for place, row in enumerate(shortlist, start=1):
            row.rank = place
    return rows


def interview_rows(db: Session) -> list[InterviewRow]:
    triples = db.execute(
        select(InterviewSession, Candidate, JobProfile.title)
        .join(Candidate, InterviewSession.candidate_id == Candidate.id)
        .join(JobProfile, Candidate.job_profile_id == JobProfile.id)
    ).all()
    lines = transcript_lines(db)
    now = utcnow()
    return [
        InterviewRow(
            id=session.id,
            candidate_id=candidate.id,
            candidate_name=candidate.name or candidate.cv_filename,
            job_id=candidate.job_profile_id,
            job_title=job_title,
            scheduled_at=session.scheduled_at,
            status=session.status,
            started_at=session.started_at,
            ended_at=session.ended_at,
            duration_seconds=seconds_between(session),
            transcript_lines=lines.get(session.id, 0),
            overdue=session.status == "scheduled" and session.scheduled_at < now,
        )
        for session, candidate, job_title in triples
    ]


# ---------- Candidates across every job ----------


def matches(row: PersonRow, words: str) -> bool:
    haystack = f"{row.name} {row.email} {row.cv_filename} {row.job_title}".lower()
    return all(word in haystack for word in words.lower().split())


SORTS = {
    "score": lambda r: (-(r.overall if r.overall is not None else -1), r.name.lower()),
    "name": lambda r: r.name.lower(),
    "added": lambda r: (-r.created_at.timestamp(), r.name.lower()),
    "job": lambda r: (r.job_title.lower(), -(r.overall if r.overall is not None else -1)),
}


@router.get("/candidates", response_model=list[PersonRow])
def all_candidates(
    db: Session = Depends(get_db),
    q: str = Query("", max_length=120, description="name, e-mail, file or job"),
    job_id: int | None = None,
    stage: str = Query("", description="one of: " + ", ".join(STAGES)),
    source: str = Query("", description="upload or google_form"),
    min_score: float | None = Query(None, ge=0, le=100),
    sort: str = Query("score", description="score, name, added or job"),
):
    """Every candidate the company has, narrowed down however the recruiter wants."""
    rows = people_rows(db)
    if q.strip():
        rows = [r for r in rows if matches(r, q)]
    if job_id is not None:
        rows = [r for r in rows if r.job_id == job_id]
    if stage:
        rows = [r for r in rows if r.stage == stage]
    if source:
        rows = [r for r in rows if r.source == source]
    if min_score is not None:
        rows = [r for r in rows if r.overall is not None and r.overall >= min_score]
    return sorted(rows, key=SORTS.get(sort, SORTS["score"]))


# ---------- Interviews across every job ----------


@router.get("/interviews", response_model=list[InterviewRow])
def all_interviews(
    db: Session = Depends(get_db),
    state: str = Query("all", description="upcoming, live, past or all"),
    q: str = Query("", max_length=120),
):
    rows = interview_rows(db)
    if q.strip():
        words = q.lower().split()
        rows = [r for r in rows if all(w in f"{r.candidate_name} {r.job_title}".lower() for w in words)]
    if state == "upcoming":
        rows = [r for r in rows if r.status == "scheduled"]
    elif state == "live":
        rows = [r for r in rows if r.status == "live"]
    elif state == "past":
        rows = [r for r in rows if r.status == "ended"]

    # Coming up: soonest first. Already over: most recent first.
    if state == "past":
        return sorted(rows, key=lambda r: r.scheduled_at, reverse=True)
    return sorted(rows, key=lambda r: (r.status == "ended", r.scheduled_at))


# ---------- Jobs with their live numbers ----------


def job_rows(db: Session, status: str = "") -> list[JobRow]:
    """Every job with its live numbers. The dashboard uses this too, so it is a plain function:
    calling an endpoint function by hand would hand it FastAPI's Query object instead of a string."""
    jobs = db.scalars(select(JobProfile).order_by(JobProfile.created_at.desc())).all()
    rows = people_rows(db)
    from app.blogger import blog_url_for  # imported here: only this view needs the blog address

    out = []
    for job in jobs:
        if status and job.status != status:
            continue
        mine = [r for r in rows if r.job_id == job.id]
        done = [r for r in mine if r.overall is not None]
        out.append(
            JobRow(
                id=job.id,
                title=job.title,
                status=job.status,
                created_at=job.created_at,
                blog_url=blog_url_for(job.slug) if job.status == "published" else None,
                required_skills=job.required_skills,
                candidates=len(mine),
                screened=sum(1 for r in mine if r.status in ("screened", "excluded")),
                waiting=sum(1 for r in mine if r.stage == "new"),
                interviews=sum(1 for r in mine if r.interview_id is not None),
                top_score=max((r.overall for r in done), default=None),
            )
        )
    return out


@router.get("/jobs", response_model=list[JobRow])
def all_jobs(db: Session = Depends(get_db), status: str = Query("", description="draft or published")):
    return job_rows(db, status)


# ---------- The dashboard ----------


def build_todo(jobs: list[JobRow], people: list[PersonRow], interviews: list[InterviewRow]) -> list[TodoItem]:
    """What is worth doing next. Each line says what to do and goes straight to the page that does it."""
    todo: list[TodoItem] = []

    for job in jobs:
        if job.waiting:
            todo.append(
                TodoItem(
                    text=f"{job.waiting} CV{'s' if job.waiting > 1 else ''} not screened for {job.title}",
                    action="Screen them",
                    to=f"/jobs/{job.id}/candidates",
                )
            )

    for interview in interviews:
        if interview.overdue:
            todo.append(
                TodoItem(
                    text=f"The interview with {interview.candidate_name} did not start",
                    action="Open it",
                    to="/interviews",
                    tone="warn",
                )
            )

    # A strong candidate nobody has invited yet is the easiest thing to lose.
    for person in people:
        if person.rank == 1 and person.stage == "screened":
            todo.append(
                TodoItem(
                    text=f"{person.name} leads {person.job_title} with no interview booked",
                    action="Schedule one",
                    to=f"/candidates/{person.id}",
                )
            )

    for job in jobs:
        if job.status == "draft":
            todo.append(
                TodoItem(text=f"{job.title} is still a draft", action="Publish it", to=f"/jobs/{job.id}")
            )

    return todo[:6]


@router.get("/overview", response_model=Overview)
def overview(db: Session = Depends(get_db)):
    """The numbers and the short to-do list on the dashboard."""
    jobs = job_rows(db)
    people = people_rows(db)
    interviews = interview_rows(db)

    marked = [p.overall for p in people if p.overall is not None]
    interviewed = sum(1 for p in people if p.stage == "interviewed")
    upcoming = [i for i in interviews if i.status in ("scheduled", "live")]
    upcoming.sort(key=lambda i: i.scheduled_at)

    top = sorted(
        (p for p in people if p.overall is not None and p.status == "screened"),
        key=lambda p: -(p.overall or 0),
    )[:5]

    return Overview(
        jobs_open=sum(1 for j in jobs if j.status == "published"),
        jobs_total=len(jobs),
        candidates_total=len(people),
        waiting_to_screen=sum(1 for p in people if p.stage == "new"),
        passed_screening=sum(1 for p in people if p.status == "screened"),
        interviews_upcoming=len(upcoming),
        interviews_done=sum(1 for i in interviews if i.status == "ended"),
        average_score=round(sum(marked) / len(marked), 1) if marked else None,
        funnel=[
            FunnelStep(label="CVs received", value=len(people)),
            FunnelStep(label="Screened", value=sum(1 for p in people if p.status in ("screened", "excluded"))),
            FunnelStep(label="Passed screening", value=sum(1 for p in people if p.status == "screened")),
            FunnelStep(label="Interviewed", value=interviewed),
        ],
        todo=build_todo(jobs, people, interviews),
        upcoming=upcoming[:5],
        top_candidates=top,
    )


@router.get("/week", response_model=list[InterviewRow])
def this_week(db: Session = Depends(get_db)):
    """Interviews in the next seven days, for the dashboard's week strip."""
    limit = utcnow() + timedelta(days=7)
    rows = [i for i in interview_rows(db) if i.status != "ended" and i.scheduled_at <= limit]
    return sorted(rows, key=lambda i: i.scheduled_at)
