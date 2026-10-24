"""The job page after screening: interview rounds, e-mails, the report and onboarding (hiring rounds).

Interviewers only. Every list here is read from the job's own records; who passes a round, who
reaches onboarding and who is rejected is always the hiring team's choice (hiring_rounds.py).
"""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import hiring_rounds
from app.db import get_db
from app.deps import current_interviewer
from app.models import Interviewer, JobProfile
from app.routers.invite_batches import deliver_batch

router = APIRouter(prefix="/api/jobs", tags=["hiring rounds"], dependencies=[Depends(current_interviewer)])


def find_job(db: Session, job_id: int) -> JobProfile:
    job = db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return job


# ---------- What goes in and out ----------


class RoundRow(BaseModel):
    candidate_id: int
    name: str
    email: str
    session_id: int
    interview_status: str  # scheduled | live | ended
    attended: bool
    cancelled: bool
    scheduled_at: datetime
    started_at: datetime | None
    score: float | None  # the interview score (F9), 0-100
    cv_score: float | None
    analysis_status: str  # "" | running | done | failed
    score_status: str
    quality_status: str
    decision: str  # "" | passed | rejected
    rank: int | None


class Closure(BaseModel):
    rule: str
    value: float | None
    passed: int
    rejected: int
    closed_at: datetime


class RoundOut(BaseModel):
    number: int
    name: str
    focus: str
    total: int
    is_last: bool
    state: str  # not_started | open | closed
    closure: Closure | None
    invited: int
    waiting: int
    held: int
    scored: int
    rows: list[RoundRow]


class CloseIn(BaseModel):
    passed_ids: list[int] = Field(default_factory=list, max_length=500)  # the hiring team's final choice
    rule: Literal["pass_mark", "top_n", "manual"] = "pass_mark"
    value: float | None = Field(default=None, ge=0, le=500)  # the pass mark or N, kept for the record
    start_date: date | None = None  # the first interview day of the next round


class CloseOut(BaseModel):
    passed: int
    rejected: int
    next_round: int | None
    batch_id: int | None
    booked: int
    not_placed: int


class StartedOut(BaseModel):
    started: int  # how many items the background work will go through


class ReportRow(BaseModel):
    candidate_id: int
    name: str
    email: str
    cv_score: float | None
    round_scores: list[dict]  # [{"number", "name", "score"}]
    assessment_status: str
    report_score: float | None  # the consolidated assessment's weighted total
    position: str
    claims_status: str
    claims_flagged: int
    decision: str  # "" | onboarding | rejected
    rank: int | None


class DecideIn(BaseModel):
    selected_ids: list[int] = Field(default_factory=list, max_length=500)
    onboarding_date: date | None = None


class DecideOut(BaseModel):
    selected: int
    rejected: int


class OnboardingRow(BaseModel):
    candidate_id: int
    name: str
    email: str
    job_id: int
    job_title: str
    report_score: float | None
    onboarding_date: date | None
    selected_at: datetime
    check_state: str  # waiting | in_progress | verified | not_confirmed | needs_decision
    checked_at: datetime | None
    best_score: float | None


class EmailRow(BaseModel):
    key: str
    kind: str  # invitation | rejection | onboarding
    candidate_id: int
    name: str
    email: str
    round_number: int | None
    round_name: str
    status: str  # queued | sent | failed
    error: str
    created_at: datetime
    sent_at: datetime | None


class RoundSummary(BaseModel):
    number: int
    name: str
    focus: str
    state: str
    invited: int
    waiting: int
    held: int
    scored: int
    is_last: bool
    passed: int | None
    rejected: int | None


class HiringSummary(BaseModel):
    cvs: int
    screened: int
    passed_screening: int
    emails: dict
    rounds: list[RoundSummary]
    finalists: int
    undecided: int
    selected: int
    verified: int


# ---------- Endpoints ----------


@router.get("/{job_id}/hiring", response_model=HiringSummary)
def hiring_summary(job_id: int, db: Session = Depends(get_db)):
    """The numbers on the job page's stage bar: screening, e-mails, each round, report, onboarding."""
    return hiring_rounds.summary(db, find_job(db, job_id))


@router.get("/{job_id}/rounds/{number}", response_model=RoundOut)
def get_round(job_id: int, number: int, db: Session = Depends(get_db)):
    """Everyone in one interview round, ranked by their interview score."""
    return hiring_rounds.round_view(db, find_job(db, job_id), number)


@router.post("/{job_id}/rounds/{number}/analyse", response_model=StartedOut, status_code=status.HTTP_202_ACCEPTED)
def analyse_round(job_id: int, number: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Analyses, scores and reviews every finished interview of the round that is missing them,
    one after the other in the background. The round's list shows each one as it finishes."""
    job = find_job(db, job_id)
    hiring_rounds.find_round(job, number)
    sessions = hiring_rounds.sessions_to_analyse(db, job, number)
    if sessions:
        background.add_task(hiring_rounds.analyse_sessions, sessions)
    return StartedOut(started=len(sessions))


@router.post("/{job_id}/rounds/{number}/close", response_model=CloseOut)
def close_round(
    job_id: int,
    number: int,
    body: CloseIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    interviewer: Interviewer = Depends(current_interviewer),
):
    """Closes the round: the chosen candidates pass (and are invited to the next round), the others
    get a rejection e-mail. The e-mails go out in the background."""
    job = find_job(db, job_id)
    result = hiring_rounds.close_round(db, job, number, body.passed_ids, body.rule, body.value, body.start_date, interviewer.id)
    if result["batch_id"] is not None:
        background.add_task(deliver_batch, result["batch_id"])
    background.add_task(hiring_rounds.deliver_emails, job.id)
    return result


@router.get("/{job_id}/report", response_model=list[ReportRow])
def get_report(job_id: int, db: Session = Depends(get_db)):
    """The candidates who passed every round, ranked by their consolidated assessment."""
    return hiring_rounds.report_rows(db, find_job(db, job_id))


@router.post("/{job_id}/report/assess", response_model=StartedOut, status_code=status.HTTP_202_ACCEPTED)
def assess_finalists(job_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Builds the consolidated assessment and the CV claim check of every finalist that misses them."""
    job = find_job(db, job_id)
    waiting = [
        r["candidate_id"]
        for r in hiring_rounds.report_rows(db, job)
        if not r["decision"] and (r["assessment_status"] != "done" or r["claims_status"] != "done")
        and "running" not in (r["assessment_status"], r["claims_status"])
    ]
    if waiting:
        background.add_task(hiring_rounds.assess_candidates, waiting)
    return StartedOut(started=len(waiting))


@router.post("/{job_id}/report/decide", response_model=DecideOut)
def decide(
    job_id: int,
    body: DecideIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    interviewer: Interviewer = Depends(current_interviewer),
):
    """The chosen finalists are selected for onboarding and get the onboarding e-mail; every other
    finalist still waiting for a decision gets a rejection e-mail."""
    job = find_job(db, job_id)
    result = hiring_rounds.decide_report(db, job, body.selected_ids, body.onboarding_date, interviewer.id)
    background.add_task(hiring_rounds.deliver_emails, job.id)
    return result


@router.get("/{job_id}/onboarding", response_model=list[OnboardingRow])
def get_onboarding(job_id: int, db: Session = Depends(get_db)):
    """Everyone selected for onboarding in this job, with the state of their face check."""
    find_job(db, job_id)
    return hiring_rounds.onboarding_rows(db, job_id)


@router.get("/{job_id}/emails", response_model=list[EmailRow])
def get_emails(job_id: int, db: Session = Depends(get_db)):
    """Every e-mail of this job: invitations per round, rejections and onboarding e-mails."""
    return hiring_rounds.email_rows(db, find_job(db, job_id))


@router.post("/{job_id}/emails/retry", response_model=StartedOut)
def retry_emails(job_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Tries every failed e-mail of the job again."""
    job = find_job(db, job_id)
    failed = sum(1 for row in hiring_rounds.email_rows(db, job) if row["status"] == "failed")
    for batch_id in hiring_rounds.queue_failed_again(db, job):
        background.add_task(deliver_batch, batch_id)
    background.add_task(hiring_rounds.deliver_emails, job.id)
    return StartedOut(started=failed)
