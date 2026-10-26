"""Running a review agent for one interview in the background (Module 13).

The interview quality review and the interview score work like the answer analysis (Module 9): the
request is answered at once with status "running", the agent works afterwards, and the row's "step"
says what it is doing so the screen can show progress. This file holds that shared part once.

A row model used here needs: session_id, status, step, error, result, started_at, finished_at, seconds.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Callable

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.interview_context import analysis_of
from app.models import InterviewSession

log = logging.getLogger("talentsight.agent_runs")

CRASHED = "Something went wrong while the AI worked. Please try again."
INTERRUPTED = "This was cut off by a restart. Please run it again."
NOT_ANALYSED = "Analyse the interview answers first (Results page, “Analyse answers”)."
BUSY = "This is already running for this interview."


class RunOut(BaseModel):
    session_id: int
    status: str  # running | done | failed
    step: str
    error: str
    started_at: datetime
    finished_at: datetime | None
    seconds: float | None
    outdated: bool  # the answers were analysed again after this was made
    result: dict


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def row_of(db: Session, model, session_id: int):
    return db.scalar(select(model).where(model.session_id == session_id))


def is_outdated(db: Session, row) -> bool:
    if row.status != "done":
        return False
    analysed = analysis_of(db, row.session_id)
    return bool(analysed and analysed.finished_at and row.started_at and analysed.finished_at > row.started_at)


def to_out(db: Session, row) -> RunOut:
    return RunOut(
        session_id=row.session_id,
        status=row.status,
        step=row.step,
        error=row.error,
        started_at=row.started_at,
        finished_at=row.finished_at,
        seconds=row.seconds,
        outdated=is_outdated(db, row),
        result=row.result or {},
    )


def start(db: Session, model, session: InterviewSession, first_step: str):
    """Checks the answers have been analysed and marks the row "running". The work is run()."""
    if session.status != "ended" or analysis_of(db, session.id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_ANALYSED)
    row = row_of(db, model, session.id)
    if row is not None and row.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, BUSY)
    if row is None:
        row = model(session_id=session.id)
        db.add(row)
    # Running again starts from a clean slate: the old result is replaced, never mixed in.
    row.status, row.step, row.error, row.result = "running", first_step, "", {}
    row.started_at, row.finished_at, row.seconds = utcnow(), None, None
    db.commit()
    db.refresh(row)
    return row


def set_step(model, row_id: int, step: str) -> None:
    with SessionLocal() as db:
        db.execute(update(model).where(model.id == row_id).values(step=step))
        db.commit()


def run(model, row_id: int, agent, state: dict, next_steps: dict[str, str], save: Callable[[dict], dict], name: str) -> None:
    """Runs the agent and stores save(final state) as the result. Runs after the request was answered."""
    started = time.monotonic()
    final: dict = {}
    session_id = None
    try:
        for mode, chunk in agent.stream(state, stream_mode=["updates", "values"]):
            if mode == "values":
                final = chunk  # the whole state after the latest step
            else:
                for node in chunk:  # the step that just finished
                    if node in next_steps:
                        set_step(model, row_id, next_steps[node])
        error = final.get("error", "")
    except Exception as crash:  # an unexpected bug must not leave the row "running" for ever
        log.error(f"{name} crashed", exc_info=crash, extra={"event": f"{name}_crash"})
        error = CRASHED

    with SessionLocal() as db:
        row = db.get(model, row_id)
        if row is None:
            return  # the candidate was deleted while the agent worked (N19)
        session_id = row.session_id
        row.status, row.step, row.error = ("failed" if error else "done"), "", error
        if not error:
            row.result = save(final)
        row.finished_at = utcnow()
        row.seconds = round(time.monotonic() - started, 1)
        db.commit()
    log.info(
        f"{name} finished",
        extra={"event": f"{name}_failed" if error else f"{name}_done", "session_id": session_id, "seconds": round(time.monotonic() - started, 1)},
    )


def mark_interrupted(model) -> None:
    """At start-up: a row still "running" was cut off by a restart. It can be run again."""
    with SessionLocal() as db:
        db.execute(update(model).where(model.status == "running").values(status="failed", step="", error=INTERRUPTED))
        db.commit()