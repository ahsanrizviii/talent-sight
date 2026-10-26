"""Running Litmus checks in the background, the human review, and the job summary (F11).

A check is started from the candidate page (one candidate) or from the job page (the top of the
shortlist, one after another). The request is answered at once; the agent works afterwards and the
row's "step" says what it is doing, so the screen can show progress.

A result that is not "steady" waits for a person: they read it and acknowledge it with a note.
Litmus never changes a score, a verdict, the ranking or a stage.
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agents.litmus_agent import get_litmus_agent
from app.agents.screening_agent import MATCH_PROMPT, SCORE_PROMPT, job_for_agent
from app.db import SessionLocal
from app.llm import measure_usage
from app.models import Candidate, CandidateScore, Interviewer, InterviewerProfile, JobProfile, LitmusCheck
from app.litmus import LABELS
from app.settings import settings

log = logging.getLogger("talentsight.litmus")

FIRST_STEP = "Making the controlled copies of the profile"
QUEUED_STEP = "Waiting in the queue"
CRASHED = "Something went wrong during the check. Please try again."
INTERRUPTED = "The check was cut off by a restart. Please run it again."
NOT_SCREENED = "Screen this candidate first, so there is a score to check."
BUSY = "A check is already running for this candidate."
NOTHING_TO_REVIEW = "This check has nothing waiting for review."
NOTE_TOO_SHORT = "Write a short note (at least 10 characters) on what you looked at."
ALL_CHECKED = "The top candidates of this shortlist are already checked and up to date."
NO_SHORTLIST = "Screen the CVs first: there is no shortlist to check yet."

# A fingerprint of the two prompts the check tests. If a prompt changes, the version changes, so an
# old check can always be traced to the exact scorer it tested.
PROMPT_VERSION = hashlib.sha256((MATCH_PROMPT + SCORE_PROMPT).encode()).hexdigest()[:12]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- Reading ----------
def input_hash(job: JobProfile, candidate: Candidate) -> str:
    """A fingerprint of what the check ran on: the profile, the job's requirements and the weights."""
    data = {"profile": candidate.profile or {}, "job": job_for_agent(job), "weights": job.weights}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def latest_of(db: Session, candidate_id: int) -> LitmusCheck | None:
    return db.scalar(
        select(LitmusCheck).where(LitmusCheck.candidate_id == candidate_id).order_by(LitmusCheck.id.desc()).limit(1)
    )


def history_of(db: Session, candidate_id: int) -> list[LitmusCheck]:
    return db.scalars(
        select(LitmusCheck).where(LitmusCheck.candidate_id == candidate_id).order_by(LitmusCheck.id.desc())
    ).all()


def is_outdated(db: Session, row: LitmusCheck) -> bool:
    """True when the candidate was screened again, or the job or its weights changed, after the check."""
    if row.status != "done":
        return False
    candidate = db.get(Candidate, row.candidate_id)
    job = db.get(JobProfile, candidate.job_profile_id)
    return row.input_hash != input_hash(job, candidate)


def reviewer_name(db: Session, interviewer_id: int | None) -> str:
    if interviewer_id is None:
        return ""
    profile = db.scalar(select(InterviewerProfile).where(InterviewerProfile.interviewer_id == interviewer_id))
    if profile and profile.full_name:
        return profile.full_name
    person = db.get(Interviewer, interviewer_id)
    return person.email if person else ""


def is_busy(db: Session, candidate_id: int) -> bool:
    return db.scalar(
        select(LitmusCheck.id).where(
            LitmusCheck.candidate_id == candidate_id,
            LitmusCheck.status.in_(("queued", "running")),
        ).limit(1)
    ) is not None


# ---------- Starting ----------
def new_row(db: Session, candidate: Candidate, job: JobProfile, queued: bool) -> LitmusCheck:
    row = LitmusCheck(
        candidate_id=candidate.id,
        status="queued" if queued else "running",
        step=QUEUED_STEP if queued else FIRST_STEP,
        input_hash=input_hash(job, candidate),
        started_at=utcnow(),
    )
    db.add(row)
    return row


def start_check(db: Session, candidate: Candidate) -> LitmusCheck:
    """Checks the candidate was screened and marks a new check "running". The work is run_check()."""
    if candidate.status not in ("screened", "excluded") or not candidate.profile:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_SCREENED)
    if is_busy(db, candidate.id):
        raise HTTPException(status.HTTP_409_CONFLICT, BUSY)
    row = new_row(db, candidate, db.get(JobProfile, candidate.job_profile_id), queued=False)
    db.commit()
    db.refresh(row)
    return row


def queue_shortlist(db: Session, job: JobProfile, limit: int) -> list[int]:
    """Queues a check for each of the job's top candidates that has no up-to-date check yet.

    Candidates already checked against the same profile, job and weights are skipped, so pressing
    the button twice never pays for the same check twice.
    """
    top = db.scalars(
        select(Candidate)
        .join(CandidateScore, CandidateScore.candidate_id == Candidate.id)
        .where(Candidate.job_profile_id == job.id, Candidate.status == "screened")
        .order_by(CandidateScore.overall.desc(), Candidate.id)
        .limit(limit)
    ).all()
    if not top:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NO_SHORTLIST)

    queued = []
    for candidate in top:
        if is_busy(db, candidate.id):
            continue
        latest = latest_of(db, candidate.id)
        if latest and latest.status == "done" and latest.input_hash == input_hash(job, candidate):
            continue
        queued.append(new_row(db, candidate, job, queued=True))
    if not queued:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, ALL_CHECKED)
    db.commit()
    return [row.id for row in queued]


# ---------- Running ----------
def set_step(check_id: int, step: str) -> None:
    with SessionLocal() as db:
        db.execute(update(LitmusCheck).where(LitmusCheck.id == check_id).values(step=step))
        db.commit()


class Progress:
    """Turns "this step just finished" into the sentence the screen shows next."""

    def __init__(self) -> None:
        self.variants: list[dict] = []

    def after(self, node: str, changes: dict) -> str:
        if changes.get("error"):
            return ""
        if node == "prepare":
            self.variants = changes.get("variants", [])
            return "Scoring the unchanged profile"
        if node == "reference":
            return "Scoring the unchanged profile again, to measure chance"
        if node in ("repeat", "variant"):
            position = changes.get("position", 0) if node == "variant" else 0
            to_run = [v for v in self.variants if v["applicable"]]
            left = [v for v in self.variants[position:] if v["applicable"]]
            if not left:
                return "Comparing the results"
            number = len(to_run) - len(left) + 1
            return f"Scoring copy {number} of {len(to_run)}: {left[0]['label'].lower()}"
        return ""


def run_check(check_id: int) -> None:
    """Runs the agent and stores the report with what it cost. Runs after the request was answered."""
    started = time.monotonic()
    with SessionLocal() as db:
        row = db.get(LitmusCheck, check_id)
        if row is None:
            return
        candidate = db.get(Candidate, row.candidate_id)
        job = db.get(JobProfile, candidate.job_profile_id)
        candidate_id = candidate.id
        state = {"job": job_for_agent(job), "weights": dict(job.weights), "profile": candidate.profile or {}}
        if row.status == "queued":  # its turn has come
            row.status, row.step, row.started_at = "running", FIRST_STEP, utcnow()
            db.commit()
    # The database connection is closed while the AI works.

    final: dict = {}
    progress = Progress()
    with measure_usage() as meter:
        try:
            for mode, chunk in get_litmus_agent().stream(state, stream_mode=["updates", "values"]):
                if mode == "values":
                    final = chunk  # the whole state after the latest step
                else:
                    for node, changes in chunk.items():  # the step that just finished
                        step = progress.after(node, changes or {})
                        if step:
                            set_step(check_id, step)
            error = final.get("error", "")
        except Exception as crash:  # an unexpected bug must not leave the check "running" for ever
            log.error("litmus crashed", exc_info=crash, extra={"event": "litmus_crash", "candidate_id": candidate_id})
            error = CRASHED

    with SessionLocal() as db:
        row = db.get(LitmusCheck, check_id)
        if row is None:
            return  # the candidate was deleted while the agent worked (N19)
        row.status, row.step, row.error = ("failed" if error else "done"), "", error
        if not error:
            report = final["report"]
            report["audit"] = {
                "model": settings.screening_model or settings.llm_model,
                "prompt_version": PROMPT_VERSION,
                "temperature": 0,
                "seed": 42,
            }
            row.result = report
            row.review_status = "" if report["outcome"] == "steady" else "pending"
        row.llm_calls, row.input_tokens, row.output_tokens = meter.calls, meter.input_tokens, meter.output_tokens
        row.cost_usd = meter.cost_usd()
        row.finished_at = utcnow()
        row.seconds = round(time.monotonic() - started, 1)
        db.commit()

    log.info(
        "litmus finished",
        extra={
            "event": "litmus_failed" if error else "litmus_done",
            "candidate_id": candidate_id,
            "count": meter.calls,
            "seconds": round(time.monotonic() - started, 1),
        },
    )


def run_queue(check_ids: list[int]) -> None:
    """The shortlist checks, one after another, so Groq's per-minute limit is not hit all at once."""
    for check_id in check_ids:
        run_check(check_id)


def mark_interrupted() -> None:
    """At start-up: a check still queued or running was cut off by a restart. It can be run again."""
    with SessionLocal() as db:
        db.execute(
            update(LitmusCheck)
            .where(LitmusCheck.status.in_(("queued", "running")))
            .values(status="failed", step="", error=INTERRUPTED)
        )
        db.commit()


# ---------- The human review ----------
def acknowledge(db: Session, row: LitmusCheck, interviewer: Interviewer, note: str) -> LitmusCheck:
    """A person has read the flagged result. Records who, when and what they noted. Changes nothing else."""
    note = note.strip()
    if row.review_status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOTHING_TO_REVIEW)
    if len(note) < 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOTE_TOO_SHORT)
    row.review_status, row.review_note = "acknowledged", note
    row.reviewed_by, row.reviewed_at = interviewer.id, utcnow()
    db.commit()
    db.refresh(row)
    log.info("litmus reviewed", extra={"event": "litmus_reviewed", "candidate_id": row.candidate_id})
    return row


# ---------- The job summary ----------
def job_summary(db: Session, job: JobProfile) -> dict:
    """The latest finished check of each candidate, added up for the job."""
    candidates = {c.id: c for c in db.scalars(select(Candidate).where(Candidate.job_profile_id == job.id)).all()}
    rows = db.scalars(
        select(LitmusCheck)
        .where(LitmusCheck.candidate_id.in_(list(candidates)))
        .order_by(LitmusCheck.id.desc())
    ).all() if candidates else []

    latest_done: dict[int, LitmusCheck] = {}
    in_progress: set[int] = set()
    for row in rows:  # newest first
        if row.status in ("queued", "running"):
            in_progress.add(row.candidate_id)
        elif row.status == "done" and row.candidate_id not in latest_done:
            latest_done[row.candidate_id] = row

    outcomes = {"steady": 0, "needs_review": 0, "inconclusive": 0}
    by_copy = {key: {"key": key, "label": label, "runs": 0, "flags": 0, "moves": []} for key, label in LABELS.items()}
    people = []
    for candidate_id, row in latest_done.items():
        candidate = candidates[candidate_id]
        report = row.result or {}
        outcomes[report.get("outcome", "steady")] += 1
        for item in report.get("variants", []):
            if not item.get("applicable") or item["key"] not in by_copy:
                continue
            by_copy[item["key"]]["runs"] += 1
            by_copy[item["key"]]["flags"] += 1 if item.get("flagged") else 0
            if item.get("overall_change") is not None:
                by_copy[item["key"]]["moves"].append(abs(item["overall_change"]))
        people.append(
            {
                "candidate_id": candidate_id,
                "name": candidate.name or candidate.cv_filename,
                "check_id": row.id,
                "outcome": report.get("outcome", ""),
                "review_status": row.review_status,
                "outdated": row.input_hash != input_hash(job, candidate),
                "finished_at": row.finished_at,
            }
        )

    copies = []
    for item in by_copy.values():
        moves = item.pop("moves")
        item["average_move"] = round(sum(moves) / len(moves), 1) if moves else None
        copies.append(item)

    checked = len(latest_done)
    return {
        "job_id": job.id,
        "checked": checked,
        "in_progress": len(in_progress),
        "outcomes": outcomes,
        "pass_rate": round(100 * outcomes["steady"] / checked) if checked else None,
        "pending_review": sum(1 for p in people if p["review_status"] == "pending"),
        "copies": copies,
        "candidates": sorted(people, key=lambda p: (p["outcome"] == "steady", p["name"].lower())),
        "total_checks": len([r for r in rows if r.status == "done"]),
        "total_cost_usd": round(sum(r.cost_usd for r in rows), 4),
        "shortlist_size": settings.litmus_shortlist_size,
    }
