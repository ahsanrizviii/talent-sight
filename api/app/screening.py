import logging
import time
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.agents.screening_agent import get_screening_agent, job_for_agent
from app.db import SessionLocal
from app.models import Candidate, CandidateScore, JobProfile, RequirementVerdict, ScreeningRun
from app.scoring import save_scores

log = logging.getLogger("talentsight.screening")

READY = ("uploaded", "queued", "failed")  # can be screened
DONE = ("screened", "excluded")  # screened again only when asked


def start_run(
    db: Session, job: JobProfile, again: bool
) -> tuple[ScreeningRun, list[int]]:
    """Creates the run and marks its candidates "queued". The work itself is run_screening()."""
    if db.scalar(
        select(ScreeningRun.id).where(
            ScreeningRun.job_profile_id == job.id,
            ScreeningRun.status == "running",
        )
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A screening is already running for this job.",
        )

    wanted = READY + DONE if again else READY
    candidates = db.scalars(
        select(Candidate).where(
            Candidate.job_profile_id == job.id,
            Candidate.status.in_(wanted),
        )
    ).all()
    if not candidates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "There are no CVs to screen.")

    for candidate in candidates:
        candidate.status = "queued"

    run = ScreeningRun(job_profile_id=job.id, total=len(candidates))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run, [c.id for c in candidates]


def save_result(
    db: Session,
    candidate: Candidate,
    result: dict,
    weights: dict,
) -> None:
    """Stores what the agent found for one candidate.

    If the AI could not answer (a free limit, a timeout), the earlier result is kept: a screening
    that fails must never wipe a score the candidate already has."""
    if result.get("error"):
        had_result = bool((candidate.profile or {}).get("skills")) and db.scalar(
            select(RequirementVerdict.id).where(RequirementVerdict.candidate_id == candidate.id).limit(1)
        )
        candidate.error = result["error"]
        if had_result:  # screened before: back to where it was, with the reason shown
            candidate.status = "excluded" if candidate.exclusion_reason else "screened"
        else:
            candidate.status = "failed"
        return

    db.execute(
        delete(RequirementVerdict).where(
            RequirementVerdict.candidate_id == candidate.id
        )
    )
    db.execute(
        delete(CandidateScore).where(
            CandidateScore.candidate_id == candidate.id
        )
    )

    profile = result["profile"]
    candidate.profile = profile
    candidate.name = profile["name"] or candidate.name
    candidate.email = profile["email"] or candidate.email
    candidate.phone = profile["phone"] or candidate.phone

    for verdict in result["verdicts"]:
        db.add(RequirementVerdict(candidate_id=candidate.id, **verdict))

    if result.get("scores"):
        save_scores(db, candidate, result["scores"], weights)
    candidate.status = "excluded" if result["excluded"] else "screened"
    candidate.exclusion_reason = result["exclusion_reason"]
    candidate.error = ""


def screen_candidate(db: Session, candidate: Candidate, job: JobProfile) -> None:
    result = get_screening_agent().invoke(
        {"cv_text": candidate.cv_text, "job": job_for_agent(job)}
    )
    save_result(db, candidate, result, job.weights)


def run_screening(run_id: int, candidate_ids: list[int]) -> None:
    """Screens the CVs one after another. Runs after the request has been answered."""
    started = time.monotonic()
    with SessionLocal() as db:
        run = db.get(ScreeningRun, run_id)
        job = db.get(JobProfile, run.job_profile_id) if run else None
        if job is None:
            return

        for candidate_id in candidate_ids:
            candidate = db.get(Candidate, candidate_id)
            if candidate is not None:
                try:
                    screen_candidate(db, candidate, job)
                except Exception as error:  # one bad CV never stops the batch (Q&A 6)
                    db.rollback()
                    log.error(
                        "screening crashed",
                        exc_info=error,
                        extra={
                            "event": "screening_crash",
                            "candidate_id": candidate_id,
                        },
                    )
                    candidate = db.get(Candidate, candidate_id)
                    candidate.status, candidate.error = (
                        "failed",
                        "Something went wrong while screening this CV.",
                    )
                if candidate.error:  # failed now (a kept earlier result also shows why)
                    run.failed += 1
            run.done += 1
            db.commit()

        run.status = "done"
        run.finished_at = datetime.now(timezone.utc)
        run.seconds = round(time.monotonic() - started, 1)
        db.commit()

        log.info(
            "screening finished",
            extra={
                "event": "screening_done",
                "job_id": job.id,
                "count": run.total,
                "seconds": run.seconds,
            },
        )


def mark_interrupted_runs() -> None:
    """At start-up: a run still "running" was cut off by a restart. Its queued CVs can be run again."""
    with SessionLocal() as db:
        db.execute(
            update(ScreeningRun)
            .where(ScreeningRun.status == "running")
            .values(status="interrupted")
        )
        db.commit()