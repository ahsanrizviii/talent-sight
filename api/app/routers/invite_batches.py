"""Inviting the top candidates of a job in one go (after screening).

HR gives two things: the first interview day and how many of the best-ranked candidates to invite.
The planner gives each one a free 1-hour slot (working days, interview hours, no holidays, no clashes),
the interviews are created at once, and the e-mails and calendar entries then go out one by one in the
background. The page shows how far it got. A failed e-mail never undoes the interview: HR can retry it
or copy the link by hand.
"""

import logging
import time
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import holiday_calendar, planner, schedule_rules, scheduling
from app.db import SessionLocal, get_db
from app.deps import current_interviewer
from app.models import Candidate, Interviewer, InterviewSession, InviteBatch, InviteDelivery, JobProfile, RoundClosure
from app.routers.candidates import list_candidates
from app.routers.interviews import calendar_for, expiry_for, new_invite_token, send_invite_for

log = logging.getLogger("talentsight")

router = APIRouter(prefix="/api/jobs", tags=["invite batches"], dependencies=[Depends(current_interviewer)])

LEAD_TIME = timedelta(hours=2)  # the first slot is at least this far away, so the e-mail arrives in time
MAX_BATCH = 500
PAUSE_SECONDS = 1.0  # between two e-mails, so the mail server does not see a burst (Gmail limits bursts)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- What goes in and out ----------


class InviteTopIn(BaseModel):
    top: int = Field(ge=1, le=MAX_BATCH)  # how many of the best-ranked candidates to invite
    start_date: date  # the first day interviews may be on


class SkippedCandidate(BaseModel):
    candidate_id: int
    rank: int
    name: str
    reason: str


class DeliveryOut(BaseModel):
    session_id: int
    round_number: int
    candidate_id: int
    name: str
    email: str
    scheduled_at: datetime
    duration_minutes: int
    interview_status: str  # scheduled | live | ended
    status: str  # queued | sent | failed
    error: str
    calendar_error: str


class BatchOut(BaseModel):
    id: int
    created_at: datetime
    total: int
    sent: int
    failed: int
    queued: int
    deliveries: list[DeliveryOut]


class InviteInfo(BaseModel):
    holidays_ahead: int  # public holidays from today on that the planner skips
    calendar_problem: str  # "" = the holiday calendar was read fine


class InviteTopOut(BaseModel):
    batch: BatchOut | None  # None when nobody could be invited
    skipped: list[SkippedCandidate]  # already invited or interviewed: not invited again
    not_placed: int  # no free slot within a year (only with very large numbers)


# ---------- Helpers ----------


def find_job(db: Session, job_id: int) -> JobProfile:
    job = db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return job


def already_invited(db: Session, candidate_id: int, round_number: int = 1) -> str:
    """Why this candidate gets no new invitation to this round, or "" when they can be invited."""
    for session in db.scalars(
        select(InterviewSession).where(InterviewSession.candidate_id == candidate_id, InterviewSession.round_number == round_number)
    ):
        if session.status in ("scheduled", "live"):
            return "Already has an interview booked."
        if session.started_at is not None:
            return "Already interviewed."
    return ""  # never invited, or only cancelled interviews


def batch_out(db: Session, batch: InviteBatch) -> BatchOut:
    rows = []
    for delivery in db.scalars(select(InviteDelivery).where(InviteDelivery.batch_id == batch.id).order_by(InviteDelivery.id)):
        session = db.get(InterviewSession, delivery.session_id)
        candidate = db.get(Candidate, session.candidate_id)
        rows.append(
            DeliveryOut(
                session_id=session.id,
                round_number=session.round_number or 1,
                candidate_id=candidate.id,
                name=candidate.name or candidate.cv_filename,
                email=candidate.email,
                scheduled_at=session.scheduled_at,
                duration_minutes=schedule_rules.minutes_of(session),
                interview_status=session.status,
                status=delivery.status,
                error=delivery.error,
                calendar_error=delivery.calendar_error,
            )
        )
    count = lambda state: sum(1 for r in rows if r.status == state)  # noqa: E731
    return BatchOut(
        id=batch.id, created_at=batch.created_at, total=len(rows), sent=count("sent"), failed=count("failed"), queued=count("queued"), deliveries=rows
    )


# ---------- Sending ----------


def deliver_batch(batch_id: int) -> None:
    """Sends the e-mails (and calendar entries) of a batch, one by one. Runs in the background.
    Each result is saved at once, so the page can show progress and a restart loses nothing."""
    with SessionLocal() as db:
        waiting = db.scalars(
            select(InviteDelivery).where(InviteDelivery.batch_id == batch_id, InviteDelivery.status != "sent").order_by(InviteDelivery.id)
        ).all()
        for index, delivery in enumerate(waiting):
            session = db.get(InterviewSession, delivery.session_id)
            if session is None or session.status != "scheduled":
                delivery.status, delivery.error = "failed", "The interview was cancelled or has started."
                db.commit()
                continue
            mail_error = send_invite_for(db, session)
            calendar_error = calendar_for(db, session)
            delivery.status = "sent" if mail_error == "" else "failed"
            delivery.error = mail_error
            delivery.calendar_error = calendar_error or ""
            delivery.sent_at = utcnow()
            db.commit()
            if index < len(waiting) - 1:
                time.sleep(PAUSE_SECONDS)
        log.info("invite batch done", extra={"event": "invite_batch_done", "batch_id": batch_id, "count": len(waiting)})


@router.get("/{job_id}/invite-info", response_model=InviteInfo)
def invite_info(job_id: int, db: Session = Depends(get_db)):
    """Shown in the invite pop-up: the holidays the planner will skip, or a warning when the holiday
    calendar was not read, so HR never books a holiday without knowing."""
    find_job(db, job_id)
    today = utcnow().astimezone(schedule_rules.current(db).zone).date()
    ahead, problem = holiday_calendar.calendar_status(db, today)
    return InviteInfo(holidays_ahead=ahead, calendar_problem=problem)


def book_round(
    db: Session, job_id: int, candidate_ids: list[int], start_date: date, round_number: int, interviewer_id: int | None
) -> tuple[InviteBatch | None, int]:
    """Books a free 1-hour slot for each candidate, in the order given (the first gets the earliest),
    creates their interviews for this round and one invitation batch. Commits. Sending is deliver_batch().
    Returns the batch (None when nobody could be placed) and how many got no slot."""
    rules = schedule_rules.current(db)
    now = utcnow()
    earliest = max(datetime.combine(start_date, datetime.min.time(), rules.zone), now + LEAD_TIME)
    off = scheduling.days_off(db, earliest, earliest + timedelta(days=planner.MAX_DAYS_AHEAD), rules)
    starts = planner.plan(len(candidate_ids), earliest, scheduling.booked(db), off, rules)
    if not starts:
        return None, len(candidate_ids)

    minutes = int(rules.length.total_seconds() // 60)
    batch = InviteBatch(job_profile_id=job_id, created_by=interviewer_id, total=len(starts), round_number=round_number)
    db.add(batch)
    db.flush()
    for candidate_id, start in zip(candidate_ids, starts):
        session = InterviewSession(
            candidate_id=candidate_id,
            scheduled_at=start,
            invite_token=new_invite_token(),
            invite_expires_at=expiry_for(start),
            duration_minutes=minutes,
            round_number=round_number,
        )
        db.add(session)
        db.flush()
        db.add(InviteDelivery(batch_id=batch.id, session_id=session.id))
    db.commit()  # every interview exists before a single e-mail goes out
    log.info("invite batch created", extra={"event": "invite_batch_created", "batch_id": batch.id, "count": len(starts)})
    return batch, len(candidate_ids) - len(starts)


@router.post("/{job_id}/invite-top", response_model=InviteTopOut, status_code=status.HTTP_201_CREATED)
def invite_top(
    job_id: int,
    body: InviteTopIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    interviewer: Interviewer = Depends(current_interviewer),
):
    """Invites the top N candidates of the ranking to the first interview round, starting on start_date.
    Everyone gets a free 1-hour slot in ranking order (the best-ranked gets the earliest), then the
    e-mails go out. Later rounds are booked when the hiring team closes a round (hiring_rounds.py)."""
    find_job(db, job_id)
    rules = schedule_rules.current(db)
    now = utcnow()
    if body.start_date < now.astimezone(rules.zone).date():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The first interview day cannot be in the past.")
    closed = db.scalar(select(RoundClosure).where(RoundClosure.job_profile_id == job_id, RoundClosure.round_number == 1))
    if closed is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Round 1 of this job is closed, so nobody new can be invited to it.")

    ranked = [row for row in list_candidates(job_id, db) if row.status == "screened"]
    if not ranked:
        raise HTTPException(status.HTTP_409_CONFLICT, "No candidate of this job has passed screening yet.")

    chosen, skipped = [], []
    for row in ranked[: body.top]:
        reason = already_invited(db, row.id, 1)
        if reason:
            skipped.append(SkippedCandidate(candidate_id=row.id, rank=row.rank or 0, name=row.name or row.cv_filename, reason=reason))
        else:
            chosen.append(row)

    batch, not_placed = book_round(db, job_id, [row.id for row in chosen], body.start_date, 1, interviewer.id)
    if batch is None:
        return InviteTopOut(batch=None, skipped=skipped, not_placed=not_placed)
    background.add_task(deliver_batch, batch.id)
    return InviteTopOut(batch=batch_out(db, batch), skipped=skipped, not_placed=not_placed)


@router.get("/{job_id}/invite-batches/latest", response_model=BatchOut | None)
def latest_batch(job_id: int, db: Session = Depends(get_db)):
    """The most recent batch of this job, with how many e-mails have gone out. The page polls this."""
    find_job(db, job_id)
    batch = db.scalar(select(InviteBatch).where(InviteBatch.job_profile_id == job_id).order_by(InviteBatch.id.desc()).limit(1))
    return batch_out(db, batch) if batch else None


@router.post("/{job_id}/invite-batches/{batch_id}/retry", response_model=BatchOut)
def retry_batch(job_id: int, batch_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Tries again for every e-mail of the batch that has not gone out (failed, or cut off by a restart)."""
    batch = db.get(InviteBatch, batch_id)
    if batch is None or batch.job_profile_id != job_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Batch not found.")
    for delivery in db.scalars(select(InviteDelivery).where(InviteDelivery.batch_id == batch_id, InviteDelivery.status == "failed")):
        delivery.status, delivery.error = "queued", ""
    db.commit()
    background.add_task(deliver_batch, batch_id)
    return batch_out(db, batch)
