"""Running the Evaluation Agent for one interview, in the background (Module 9, Task 9.2.2).

The interviewer asks for the analysis after the interview has ended (Q&A 42). The request is
answered at once and the agent works afterwards, because one interview means a dozen or more AI
calls. While it works, the row's "step" says what it is doing, so the screen can show progress.
"""

import logging
import time
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import round_info
from app.agents.evaluation_agent import build_turns, get_evaluation_agent
from app.agents.screening_agent import job_for_agent
from app.db import SessionLocal
from app.models import Candidate, InterviewEvaluation, InterviewSession, JobProfile, TranscriptSegment

log = logging.getLogger("talentsight.evaluation")

FIRST_STEP = "Splitting the transcript into questions and answers"
# What the agent does after each step, shown on the screen while it works.
NEXT_STEP = {
    "segment_pairs": "Sorting job questions from small talk",
    "classify_pairs": "Linking the answers to the job requirements",
    "map_requirements": "Scoring the answers",
    "score_answers": "Checking which requirements were explored",
}
CRASHED = "Something went wrong while analysing the answers. Please try again."
INTERRUPTED = "The analysis was cut off by a restart. Please run it again."


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def transcript_of(db: Session, session_id: int) -> list[dict]:
    """The saved transcript lines in time order (Module 8)."""
    rows = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.session_id == session_id)
        .order_by(TranscriptSegment.start_ms, TranscriptSegment.id)
    )
    return [{"speaker": r.speaker, "text": r.text, "start_ms": r.start_ms, "end_ms": r.end_ms} for r in rows]


def start_evaluation(db: Session, session: InterviewSession) -> InterviewEvaluation:
    """Checks the interview can be analysed and marks its analysis "running". The work is run_evaluation()."""
    if session.status != "ended":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Analyse the answers after the interview has ended.")
    has_transcript = db.scalar(select(TranscriptSegment.id).where(TranscriptSegment.session_id == session.id).limit(1))
    if not has_transcript:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This interview has no transcript to analyse.")

    row = db.scalar(select(InterviewEvaluation).where(InterviewEvaluation.session_id == session.id))
    if row is not None and row.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "The answers are already being analysed.")
    if row is None:
        row = InterviewEvaluation(session_id=session.id)
        db.add(row)
    # Running it again starts from a clean slate: the old result is replaced, never mixed in.
    row.status, row.step, row.error, row.result = "running", FIRST_STEP, "", {}
    row.started_at, row.finished_at, row.seconds = utcnow(), None, None
    db.commit()
    db.refresh(row)
    return row


def summarise(pairs: list[dict], coverage: list[dict]) -> dict:
    """The numbers at the top of the analysis screen."""
    job_related = [p for p in pairs if p["kind"] == "job_related"]
    scored = [p["overall"] for p in job_related if p["overall"] is not None]
    return {
        "pairs": len(pairs),
        "job_related": len(job_related),
        "small_talk": len(pairs) - len(job_related),
        "scored": len(scored),
        "average": round(sum(scored) / len(scored)) if scored else None,
        "not_explored": sum(1 for c in coverage if c["status"] == "not_explored"),
        "weak": sum(1 for c in coverage if c["status"] == "weak"),
    }


def job_for_round(job: JobProfile, round_number: int | None) -> dict:
    """What the answers are judged against: the job's requirements in a technical round, the round's HR
    topics (its focus text, or the default HR topics) in an HR round."""
    found = round_info.round_of(job, round_number or 1)
    if found["type"] != "hr":
        return job_for_agent(job)
    topics = round_info.hr_topics(found["focus"])
    return {
        "title": job.title,
        "description": job.description,
        "requirements": [{"requirement": topic, "kind": "hr_topic", "mandatory": False} for topic in topics],
    }


def set_step(evaluation_id: int, step: str) -> None:
    with SessionLocal() as db:
        db.execute(update(InterviewEvaluation).where(InterviewEvaluation.id == evaluation_id).values(step=step))
        db.commit()


def run_evaluation(evaluation_id: int) -> None:
    """Runs the agent and stores what it found. Runs after the request has been answered."""
    started = time.monotonic()
    with SessionLocal() as db:
        row = db.get(InterviewEvaluation, evaluation_id)
        if row is None:
            return
        session = db.get(InterviewSession, row.session_id)
        candidate = db.get(Candidate, session.candidate_id)
        job = db.get(JobProfile, candidate.job_profile_id)
        session_id = session.id
        state = {
            "turns": build_turns(transcript_of(db, session.id)),
            "job": job_for_round(job, session.round_number),
            "round_type": round_info.round_of(job, session.round_number or 1)["type"],
        }
    # The database connection is closed while the AI works: one analysis can take a few minutes.

    final: dict = {}
    try:
        for mode, chunk in get_evaluation_agent().stream(state, stream_mode=["updates", "values"]):
            if mode == "values":
                final = chunk  # the whole state after the latest step
            else:
                for node in chunk:  # the step that just finished
                    if node in NEXT_STEP:
                        set_step(evaluation_id, NEXT_STEP[node])
        error = final.get("error", "")
    except Exception as crash:  # an unexpected bug must not leave the analysis "running" for ever
        log.error("evaluation crashed", exc_info=crash, extra={"event": "evaluation_crash", "session_id": session_id})
        error = CRASHED

    with SessionLocal() as db:
        row = db.get(InterviewEvaluation, evaluation_id)
        if row is None:
            return  # the candidate was deleted while the agent worked (N19)
        row.status, row.step, row.error = ("failed" if error else "done"), "", error
        if not error:
            row.result = {
                "turns": state["turns"],
                "pairs": final["pairs"],
                "coverage": final["coverage"],
                "summary": summarise(final["pairs"], final["coverage"]),
                "round_type": state["round_type"],
            }
        row.finished_at = utcnow()
        row.seconds = round(time.monotonic() - started, 1)
        db.commit()

    log.info(
        "evaluation finished",
        extra={
            "event": "evaluation_failed" if error else "evaluation_done",
            "session_id": session_id,
            "count": len(final.get("pairs", [])),
            "seconds": round(time.monotonic() - started, 1),
        },
    )


def mark_interrupted_evaluations() -> None:
    """At start-up: an analysis still "running" was cut off by a restart. It can be run again."""
    with SessionLocal() as db:
        db.execute(
            update(InterviewEvaluation)
            .where(InterviewEvaluation.status == "running")
            .values(status="failed", step="", error=INTERRUPTED)
        )
        db.commit()