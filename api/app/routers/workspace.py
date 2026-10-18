"""The views that look across every job at once (UI refresh).

Until now every list belonged to one job, so finding a candidate meant remembering which job
they applied for. These endpoints answer the questions a hiring team actually asks:
who is in the pipeline, what needs doing today, and which interviews are coming up.

Everything here is read-only, and it is built from the tables the other modules already fill.
Each list is loaded with a handful of grouped queries instead of one query per candidate,
so a long list stays fast.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schedule_rules
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
SHORTLISTED = ("interview", "interviewed")  # sent an interview invitation (booked), or already interviewed

LATE_MINUTES = 15  # a few minutes late is normal; after this, a scheduled interview "did not start"
FORGOTTEN_MINUTES = 60  # a live interview this long past its planned end was most likely never ended
RECENT_DAYS = 14  # interviews held in this many days are listed for review on the dashboard


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
    overall: float | None = None  # the candidate's score, so interviews can be sorted by it
    duration_minutes: int = 0  # how long it is booked for
    overdue: bool = False  # the start time has passed and nobody ever joined
    forgotten: bool = False  # still live long after it should have finished: nobody pressed End


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


class JobProgress(BaseModel):
    """One open job on the dashboard: how far its hiring has got, and the next thing to do for it."""

    id: int
    title: str
    days_open: int  # days since the job was created
    candidates: int
    waiting: int  # CVs not screened yet
    passed: int  # passed screening
    invited: int  # an interview is booked or was held
    interviewed: int  # the interview really took place
    leader_id: int | None = None  # the best candidate of this job
    leader_name: str = ""
    leader_score: float | None = None
    next_step: str
    next_link: str


class Overview(BaseModel):
    jobs_open: int
    jobs_total: int
    candidates_total: int
    waiting_to_screen: int
    passed_screening: int
    ready_total: int  # passed screening, no interview booked or held yet
    interviews_upcoming: int
    interviews_week: int  # booked in the next 7 days
    interviews_done: int  # really held (a cancelled interview does not count)
    funnel: list[FunnelStep]
    todo: list[TodoItem]
    next_interview: InterviewRow | None
    upcoming: list[InterviewRow]
    jobs: list[JobProgress]
    ready_to_invite: list[PersonRow]
    recent_interviews: list[InterviewRow]


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


def held(session: InterviewSession) -> bool:
    """True if the interview really took place. A cancelled interview ends without ever starting."""
    return session.status == "ended" and session.started_at is not None


def stage_of(candidate: Candidate, session: InterviewSession | None) -> str:
    if candidate.status in ("unreadable", "failed"):
        return "problem"
    if session is not None and session.status in ("scheduled", "live"):
        return "interview"
    if session is not None and held(session):
        return "interviewed"
    # No interview, or only a cancelled one: the candidate is back where screening left them.
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
    totals = scores(db)
    now = utcnow()
    late = timedelta(minutes=LATE_MINUTES)
    default = schedule_rules.default_minutes(db)
    planned_end = lambda session: timedelta(minutes=schedule_rules.minutes_of(session, default) + FORGOTTEN_MINUTES)  # noqa: E731
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
            overall=totals.get(candidate.id),
            duration_minutes=schedule_rules.minutes_of(session, default),
            overdue=session.status == "scheduled" and session.scheduled_at + late < now,
            forgotten=session.status == "live" and (session.started_at or session.scheduled_at) + planned_end(session) < now,
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
    stage: Literal["", "interview", "interviewed"] = Query(""),
    source: Literal["", "upload", "google_form"] = Query(""),
    min_score: float | None = Query(None, ge=0, le=100),
    sort: Literal["score", "name", "added", "job"] = Query("score"),
):
    """The shortlist: every candidate who was sent an interview invitation (and those already
    interviewed), across every job, narrowed down however the recruiter wants. Everyone else is
    seen on the job's own ranking page."""
    rows = [r for r in people_rows(db) if r.stage in SHORTLISTED]
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


INTERVIEW_SORTS = {
    "soonest": (lambda r: r.scheduled_at, False),
    "latest": (lambda r: r.scheduled_at, True),
    "candidate": (lambda r: (r.candidate_name.lower(), r.scheduled_at), False),
    "job": (lambda r: (r.job_title.lower(), r.scheduled_at), False),
    "score": (lambda r: (-(r.overall if r.overall is not None else -1), r.scheduled_at), False),
    "state": (lambda r: ({"live": 0, "scheduled": 1, "ended": 2}.get(r.status, 3), r.scheduled_at), False),
}


@router.get("/interviews", response_model=list[InterviewRow])
def all_interviews(
    db: Session = Depends(get_db),
    state: Literal["upcoming", "live", "past", "all"] = Query("all"),
    q: str = Query("", max_length=120),
    job_id: int | None = None,
    sort: Literal["", "soonest", "latest", "candidate", "job", "score", "state"] = Query("", description="empty = the usual order"),
):
    rows = interview_rows(db)
    if q.strip():
        words = q.lower().split()
        rows = [r for r in rows if all(w in f"{r.candidate_name} {r.job_title}".lower() for w in words)]
    if job_id is not None:
        rows = [r for r in rows if r.job_id == job_id]
    if state == "upcoming":
        rows = [r for r in rows if r.status == "scheduled"]
    elif state == "live":
        rows = [r for r in rows if r.status == "live"]
    elif state == "past":
        rows = [r for r in rows if r.status == "ended"]

    if sort in INTERVIEW_SORTS:
        key, newest_first = INTERVIEW_SORTS[sort]
        return sorted(rows, key=key, reverse=newest_first)
    # The usual order. Coming up: soonest first. Already over: most recent first.
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
def all_jobs(db: Session = Depends(get_db), status: Literal["", "draft", "published"] = Query("")):
    return job_rows(db, status)


# ---------- The dashboard ----------


def job_progress(job: JobRow, mine: list[PersonRow]) -> JobProgress:
    """One open job: how far its hiring has got, and the one step that moves it forward."""
    passed = [p for p in mine if p.status == "screened"]
    booked = [p for p in mine if p.stage == "interview"]
    interviewed = [p for p in mine if p.stage == "interviewed"]
    ready = sorted((p for p in mine if p.stage == "screened"), key=lambda p: p.rank or 999)
    leader = min(passed, key=lambda p: p.rank or 999, default=None)

    if not mine:
        step, link = "Add CVs", f"/jobs/{job.id}/candidates"
    elif job.waiting:
        step, link = f"Screen {job.waiting} CV{'s' if job.waiting > 1 else ''}", f"/jobs/{job.id}/candidates"
    elif not passed:
        step, link = "See why nobody passed", f"/jobs/{job.id}/candidates"
    elif ready and not booked and not interviewed:
        step, link = f"Invite {ready[0].name}", f"/candidates/{ready[0].id}"
    elif booked:
        step, link = "See the booked interviews", "/interviews"
    elif ready:
        step, link = f"Invite {ready[0].name}", f"/candidates/{ready[0].id}"
    else:
        step, link = "Review the interviews", "/interviews"

    return JobProgress(
        id=job.id,
        title=job.title,
        days_open=max(0, (utcnow() - job.created_at).days),
        candidates=len(mine),
        waiting=job.waiting,
        passed=len(passed),
        invited=len(booked) + len(interviewed),
        interviewed=len(interviewed),
        leader_id=leader.id if leader else None,
        leader_name=leader.name if leader else "",
        leader_score=leader.overall if leader else None,
        next_step=step,
        next_link=link,
    )


def build_todo(jobs: list[JobRow], people: list[PersonRow], interviews: list[InterviewRow]) -> list[TodoItem]:
    """What is worth doing next, most urgent first. Each line goes straight to the page that does it."""
    todo: list[TodoItem] = []

    # An interview nobody ended keeps the candidate's link open, so it comes first.
    for interview in interviews:
        if interview.forgotten:
            todo.append(
                TodoItem(
                    text=f"The interview with {interview.candidate_name} was never ended",
                    action="End it",
                    to=f"/candidates/{interview.candidate_id}",
                    tone="warn",
                )
            )

    for interview in interviews:
        if interview.overdue:
            todo.append(
                TodoItem(
                    text=f"The interview with {interview.candidate_name} did not start",
                    action="Reschedule",
                    to=f"/candidates/{interview.candidate_id}",
                    tone="warn",
                )
            )

    for job in jobs:
        if job.waiting:
            todo.append(
                TodoItem(
                    text=f"{job.waiting} CV{'s' if job.waiting > 1 else ''} not screened for {job.title}",
                    action="Screen them",
                    to=f"/jobs/{job.id}/candidates",
                )
            )

    for job in jobs:
        problems = sum(1 for p in people if p.job_id == job.id and p.stage == "problem")
        if problems:
            todo.append(
                TodoItem(
                    text=f"{problems} CV{'s' if problems > 1 else ''} for {job.title} could not be screened",
                    action="Check them",
                    to=f"/jobs/{job.id}/candidates",
                )
            )

    # A strong candidate nobody has invited yet is the easiest thing to lose.
    for person in people:
        if person.rank == 1 and person.stage == "screened":
            todo.append(
                TodoItem(
                    text=f"{person.name} leads {person.job_title} with no interview booked",
                    action="Review",
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
    """Everything on the dashboard: what to do now, the next interviews, and how far each job has got."""
    jobs = job_rows(db)
    people = people_rows(db)
    interviews = interview_rows(db)
    now = utcnow()

    # Coming up: a live interview first (someone may be waiting in the room), then the soonest.
    # Interviews that did not start or were never ended are in the to-do list instead.
    upcoming = [
        i for i in interviews
        if (i.status == "scheduled" and not i.overdue) or (i.status == "live" and not i.forgotten)
    ]
    upcoming.sort(key=lambda i: (i.status != "live", i.scheduled_at))

    # Who to invite next: for each job, its best candidates who passed screening and have no interview.
    # Scores are only compared inside one job: a 75 for one role says nothing about a 75 for another.
    ready = sorted((p for p in people if p.stage == "screened"), key=lambda p: p.rank or 999)
    ready_to_invite: list[PersonRow] = []
    for job in jobs:
        ready_to_invite += [p for p in ready if p.job_id == job.id][:3]
    ready_to_invite = ready_to_invite[:8]

    # Interviews that really took place lately, newest first, for the team to review.
    since = now - timedelta(days=RECENT_DAYS)
    recent = sorted(
        (i for i in interviews if i.status == "ended" and i.started_at is not None and i.ended_at and i.ended_at >= since),
        key=lambda i: i.ended_at,
        reverse=True,
    )[:5]

    return Overview(
        jobs_open=sum(1 for j in jobs if j.status == "published"),
        jobs_total=len(jobs),
        candidates_total=len(people),
        waiting_to_screen=sum(1 for p in people if p.stage == "new"),
        passed_screening=sum(1 for p in people if p.status == "screened"),
        ready_total=len(ready),
        interviews_upcoming=len(upcoming),
        interviews_week=sum(1 for i in upcoming if i.scheduled_at <= now + timedelta(days=7)),
        interviews_done=sum(1 for i in interviews if i.status == "ended" and i.started_at is not None),
        funnel=[
            FunnelStep(label="CVs received", value=len(people)),
            FunnelStep(label="Screened", value=sum(1 for p in people if p.status in ("screened", "excluded"))),
            FunnelStep(label="Passed screening", value=sum(1 for p in people if p.status == "screened")),
            FunnelStep(label="Invited", value=sum(1 for p in people if p.stage in ("interview", "interviewed"))),
            FunnelStep(label="Interviewed", value=sum(1 for p in people if p.stage == "interviewed")),
        ],
        todo=build_todo(jobs, people, interviews),
        next_interview=upcoming[0] if upcoming else None,
        upcoming=upcoming[:5],
        jobs=[job_progress(job, [p for p in people if p.job_id == job.id]) for job in jobs if job.status == "published"],
        ready_to_invite=ready_to_invite,
        recent_interviews=recent,
    )


@router.get("/week", response_model=list[InterviewRow])
def this_week(db: Session = Depends(get_db)):
    """Interviews in the next seven days, for the dashboard's week strip."""
    limit = utcnow() + timedelta(days=7)
    rows = [i for i in interview_rows(db) if i.status != "ended" and i.scheduled_at <= limit]
    return sorted(rows, key=lambda i: i.scheduled_at)
