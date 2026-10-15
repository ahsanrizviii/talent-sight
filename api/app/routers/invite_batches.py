"""Inviting the top candidates of a job in one go (after screening).

1. PLAN (nothing is saved): HR asks for the top N of the ranked shortlist, or picks people by hand
   in the order they want them interviewed. The planner gives each one a free slot (working days,
   interview hours, no holidays, no clashes). On the page HR can still move people up or down.
2. SEND: HR checks the plan, may untick people, and presses Send. Every interview is created at once;
   the e-mails and calendar entries then go out one by one in the background, and the page shows
   how far it got. A failed e-mail never undoes the interview: HR can copy the link by hand.
"""

import logging
import time
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import invite_mail, planner, schedule_rules, scheduling
from app.db import SessionLocal, get_db
from app.deps import current_interviewer
from app.models import Candidate, Interviewer, InterviewSession, InviteBatch, InviteDelivery, JobProfile
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


class PlanIn(BaseModel):
    top: int | None = Field(default=None, ge=1, le=MAX_BATCH)  # the top N of the shortlist ...
    candidate_ids: list[int] | None = Field(default=None, min_length=1, max_length=MAX_BATCH)  # ... or these people, in this order
    start_date: date | None = None  # the first day slots may be on; empty = tomorrow
    duration_minutes: int | None = Field(default=None, ge=10, le=240)  # empty = the length on the Settings page


class PlannedSlot(BaseModel):
    candidate_id: int
    rank: int
    name: str
    email: str
    overall: float | None
    scheduled_at: datetime
    email_ok: bool  # False: no address or a wrong-looking one, so the link must be sent by hand


class SkippedCandidate(BaseModel):
    candidate_id: int
    rank: int
    name: str
    reason: str


class PlanOut(BaseModel):
    ranked_total: int  # how many passed screening
    asked: int  # how many people were asked for
    slots: list[PlannedSlot]
    skipped: list[SkippedCandidate]  # already invited or interviewed
    not_placed: int  # no free slot within a year (only with very large numbers)
    rules: dict


class SendItem(BaseModel):
    candidate_id: int
    scheduled_at: datetime


class SendIn(BaseModel):
    items: list[SendItem] = Field(min_length=1, max_length=MAX_BATCH)
    duration_minutes: int | None = Field(default=None, ge=10, le=240)


class DeliveryOut(BaseModel):
    session_id: int
    candidate_id: int
    name: str
    email: str
    scheduled_at: datetime
    duration_minutes: int
    interview_status: str  # scheduled | live | ended: only a scheduled one can still be moved
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


# ---------- Helpers ----------


def find_job(db: Session, job_id: int) -> JobProfile:
    job = db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return job


def load_rules(db: Session, minutes: int | None = None) -> planner.Rules:
    """The rules from the Settings page, for this batch's interview length."""
    try:
        rules = schedule_rules.current(db)
        return planner.with_length(rules, minutes) if minutes else rules
    except planner.PlanError as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem))


def already_invited(db: Session, candidate_id: int) -> str:
    """Why this candidate gets no new invitation, or "" when they can be invited."""
    for session in db.scalars(select(InterviewSession).where(InterviewSession.candidate_id == candidate_id)):
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


# ---------- 1. Plan ----------


@router.get("/{job_id}/invite-plan/rules")
def planning_rules(job_id: int, db: Session = Depends(get_db)) -> dict:
    """The rules the planner follows, shown on the page so HR knows what to expect."""
    find_job(db, job_id)
    rules = load_rules(db)
    now = utcnow()
    upcoming = scheduling.days_off(db, now, now + timedelta(days=365), rules)
    return {**rules.describe(), "holidays_ahead": len(upcoming)}


@router.post("/{job_id}/invite-plan", response_model=PlanOut)
def make_plan(job_id: int, body: PlanIn, db: Session = Depends(get_db)):
    """Who would be invited, and when. Saves nothing."""
    find_job(db, job_id)
    if (body.top is None) == (body.candidate_ids is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose either the top N or the people to invite.")
    rules = load_rules(db, body.duration_minutes)

    ranked = [row for row in list_candidates(job_id, db) if row.status == "screened"]
    if body.top is not None:
        wanted = ranked[: body.top]
    else:
        by_id = {row.id: row for row in ranked}
        missing = [cid for cid in body.candidate_ids if cid not in by_id]
        if missing:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Only candidates of this job who passed screening can be invited.")
        if len(set(body.candidate_ids)) != len(body.candidate_ids):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A candidate is listed twice.")
        wanted = [by_id[cid] for cid in body.candidate_ids]  # HR's own order: the first gets the earliest slot

    chosen, skipped = [], []
    for row in wanted:
        reason = already_invited(db, row.id)
        if reason:
            skipped.append(SkippedCandidate(candidate_id=row.id, rank=row.rank or 0, name=row.name or row.cv_filename, reason=reason))
        else:
            chosen.append(row)

    now = utcnow()
    first_day = body.start_date or (now.astimezone(rules.zone) + timedelta(days=1)).date()
    earliest = max(datetime.combine(first_day, datetime.min.time(), rules.zone), now + LEAD_TIME)
    off = scheduling.days_off(db, earliest, earliest + timedelta(days=planner.MAX_DAYS_AHEAD), rules)
    starts = planner.plan(len(chosen), earliest, scheduling.booked(db), off, rules)

    slots = [
        PlannedSlot(
            candidate_id=row.id,
            rank=row.rank or 0,
            name=row.name or row.cv_filename,
            email=row.email,
            overall=row.overall,
            scheduled_at=start,
            email_ok=bool(invite_mail.EMAIL_SHAPE.match(row.email.strip())),
        )
        for row, start in zip(chosen, starts)
    ]
    return PlanOut(
        ranked_total=len(ranked),
        asked=len(wanted),
        slots=slots,
        skipped=skipped,
        not_placed=len(chosen) - len(slots),
        rules=rules.describe(),
    )


# ---------- 2. Send ----------


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


@router.post("/{job_id}/invite-batches", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
def send_invitations(
    job_id: int,
    body: SendIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    interviewer: Interviewer = Depends(current_interviewer),
):
    """Books every interview of the checked plan, then e-mails them in the background.
    Every time is checked again first: the plan may be a few minutes old."""
    find_job(db, job_id)
    rules = load_rules(db, body.duration_minutes)
    minutes = int(rules.length.total_seconds() // 60)
    now = utcnow()
    busy = scheduling.booked(db)
    seen: set[int] = set()
    problems: list[str] = []
    times = [item.scheduled_at for item in body.items if item.scheduled_at.tzinfo is not None] or [now]
    days_off = scheduling.days_off(db, min(times), max(times), rules)

    for item in body.items:
        candidate = db.get(Candidate, item.candidate_id)
        label = (candidate.name or candidate.cv_filename) if candidate else f"Candidate {item.candidate_id}"
        if item.scheduled_at.tzinfo is None:
            problems.append(f"{label}: the time has no time zone.")
            continue
        if candidate is None or candidate.job_profile_id != job_id or candidate.status != "screened":
            problems.append(f"{label}: not a screened candidate of this job.")
            continue
        if item.candidate_id in seen:
            problems.append(f"{label}: listed twice.")
            continue
        seen.add(item.candidate_id)
        reason = already_invited(db, candidate.id) or planner.slot_problem(item.scheduled_at, busy, days_off, rules, now)
        if reason:
            problems.append(f"{label}: {reason}")
            continue
        busy.append((item.scheduled_at, item.scheduled_at + rules.length))  # the next one must not clash with this one

    if problems:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Nothing was sent, because the plan is out of date. Please make the plan again. " + " ".join(problems[:5]),
        )

    batch = InviteBatch(job_profile_id=job_id, created_by=interviewer.id, total=len(body.items))
    db.add(batch)
    db.flush()
    for item in body.items:
        session = InterviewSession(
            candidate_id=item.candidate_id,
            scheduled_at=item.scheduled_at,
            invite_token=new_invite_token(),
            invite_expires_at=expiry_for(item.scheduled_at),
            duration_minutes=minutes,
        )
        db.add(session)
        db.flush()
        db.add(InviteDelivery(batch_id=batch.id, session_id=session.id))
    db.commit()  # every interview exists before a single e-mail goes out

    log.info("invite batch created", extra={"event": "invite_batch_created", "batch_id": batch.id, "count": len(body.items)})
    background.add_task(deliver_batch, batch.id)
    return batch_out(db, batch)


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
