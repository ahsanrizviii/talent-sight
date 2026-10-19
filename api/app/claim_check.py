"""Running the Claim Check Agent for one candidate, in the background (Module 13, F8).

The interviewer asks for the check once the interview answers have been analysed (Module 9), because
it reads the same numbered transcript turns. The request is answered at once and the agent works
afterwards; while it works, the row's "step" says what it is doing, so the screen can show progress.
The result is advice for a person only: it never changes the score, the position or the stage.
"""

import logging
import time
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agents.claim_agent import get_claim_agent
from app.agents.screening_agent import requirements_of
from app.assessment import latest_analysis
from app.db import SessionLocal
from app.models import Candidate, ClaimCheck, JobProfile

log = logging.getLogger("talentsight.claim_check")

FIRST_STEP = "Listing the claims in the CV"
# What the agent does after each step, shown on the screen while it works.
NEXT_STEP = {
    "list_claims": "Finding where the interview talks about each claim",
    "find_mentions": "Comparing each claim with what the candidate said",
    "judge_claims": "Checking every flag against the transcript",
}
CRASHED = "Something went wrong while checking the CV claims. Please try again."
INTERRUPTED = "The claim check was cut off by a restart. Please run it again."
NOT_SCREENED = "Screen this candidate first, so their CV has been read."
NOT_ANALYSED = "Analyse the interview answers first (Interview tab)."


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def check_of(db: Session, candidate_id: int) -> ClaimCheck | None:
    return db.scalar(select(ClaimCheck).where(ClaimCheck.candidate_id == candidate_id))


def is_outdated(db: Session, row: ClaimCheck) -> bool:
    """True when the interview answers were analysed again after this check was made."""
    if row.status != "done":
        return False
    latest = latest_analysis(db, row.candidate_id)
    return bool(latest and latest[0].finished_at and row.started_at and latest[0].finished_at > row.started_at)


def start_check(db: Session, candidate: Candidate) -> ClaimCheck:
    """Checks the CV and the analysed interview exist and marks the check "running". The work is run_check()."""
    if candidate.status != "screened" or not candidate.profile:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_SCREENED)
    found = latest_analysis(db, candidate.id)
    if found is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_ANALYSED)

    row = check_of(db, candidate.id)
    if row is not None and row.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "This candidate's CV claims are already being checked.")
    if row is None:
        row = ClaimCheck(candidate_id=candidate.id)
        db.add(row)
    # Checking again starts from a clean slate: the old result is replaced, never mixed in.
    row.session_id = found[1].id
    row.status, row.step, row.error, row.result = "running", FIRST_STEP, "", {}
    row.started_at, row.finished_at, row.seconds = utcnow(), None, None
    db.commit()
    db.refresh(row)
    return row


def inputs_for(db: Session, candidate: Candidate) -> dict:
    """What the agent needs: the job's requirements, the structured CV and the interview turns."""
    job = db.get(JobProfile, candidate.job_profile_id)
    evaluation, _ = latest_analysis(db, candidate.id)
    return {
        "job": {"title": job.title, "requirements": [r["requirement"] for r in requirements_of(job)]},
        "profile": candidate.profile or {},
        "turns": (evaluation.result or {}).get("turns", []),
    }


def set_step(check_id: int, step: str) -> None:
    with SessionLocal() as db:
        db.execute(update(ClaimCheck).where(ClaimCheck.id == check_id).values(step=step))
        db.commit()


def run_check(check_id: int) -> None:
    """Runs the agent and stores what it found. Runs after the request has been answered."""
    started = time.monotonic()
    with SessionLocal() as db:
        row = db.get(ClaimCheck, check_id)
        if row is None:
            return
        candidate = db.get(Candidate, row.candidate_id)
        candidate_id = candidate.id
        state = inputs_for(db, candidate)
    # The database connection is closed while the AI works.

    final: dict = {}
    try:
        for mode, chunk in get_claim_agent().stream(state, stream_mode=["updates", "values"]):
            if mode == "values":
                final = chunk  # the whole state after the latest step
            else:
                for node in chunk:  # the step that just finished
                    if node in NEXT_STEP:
                        set_step(check_id, NEXT_STEP[node])
        error = final.get("error", "")
    except Exception as crash:  # an unexpected bug must not leave the check "running" for ever
        log.error("claim check crashed", exc_info=crash, extra={"event": "claim_check_crash", "candidate_id": candidate_id})
        error = CRASHED

    with SessionLocal() as db:
        row = db.get(ClaimCheck, check_id)
        if row is None:
            return  # the candidate was deleted while the agent worked (N19)
        row.status, row.step, row.error = ("failed" if error else "done"), "", error
        if not error:
            # Only the turns the results point to are kept, so the screen can show them in context.
            used = {n for claim in final["results"] for n in claim["turns"]}
            row.result = {
                "claims": final["results"],
                "summary": final["summary"],
                "turns": [t for t in state["turns"] if t["n"] in used],
            }
        row.finished_at = utcnow()
        row.seconds = round(time.monotonic() - started, 1)
        db.commit()

    log.info(
        "claim check finished",
        extra={
            "event": "claim_check_failed" if error else "claim_check_done",
            "candidate_id": candidate_id,
            "count": len(final.get("results", [])),
            "seconds": round(time.monotonic() - started, 1),
        },
    )


def mark_interrupted_checks() -> None:
    """At start-up: a check still "running" was cut off by a restart. It can be run again."""
    with SessionLocal() as db:
        db.execute(update(ClaimCheck).where(ClaimCheck.status == "running").values(status="failed", step="", error=INTERRUPTED))
        db.commit()