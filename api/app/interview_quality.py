"""Running the Interview Quality Agent for one interview, in the background (Module 13, F10)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import agent_runs
from app.agents.quality_agent import get_quality_agent
from app.db import SessionLocal
from app.interview_context import review_context
from app.models import Candidate, InterviewQuality, InterviewSession

FIRST_STEP = "Measuring talk time, questions and coverage"
# What the agent does after each step, shown on the screen while it works.
NEXT_STEP = {
    "measure": "Reviewing each question",
    "review": "Checking the recommendations against the transcript",
}
KEPT = ("measures", "compare", "personal", "questions", "kinds", "recommendations", "summary")


def inputs_for(db: Session, session: InterviewSession) -> dict:
    context = review_context(db, session)
    candidate = db.get(Candidate, session.candidate_id)
    # The other reviewed interviews for the same job, so this one can be compared with them.
    others = db.scalars(
        select(InterviewQuality)
        .join(InterviewSession, InterviewQuality.session_id == InterviewSession.id)
        .join(Candidate, InterviewSession.candidate_id == Candidate.id)
        .where(
            Candidate.job_profile_id == candidate.job_profile_id,
            InterviewQuality.session_id != session.id,
            InterviewQuality.status == "done",
        )
    ).all()
    return {
        "job": context["job"],
        "turns": context["turns"],
        "pairs": context["pairs"],
        "coverage": context["coverage"],
        "others": [(row.result or {}).get("measures", {}) for row in others],
    }


def run_review(row_id: int) -> None:
    with SessionLocal() as db:
        row = db.get(InterviewQuality, row_id)
        if row is None:
            return
        state = inputs_for(db, db.get(InterviewSession, row.session_id))
    # The database connection is closed while the AI works.
    agent_runs.run(
        InterviewQuality, row_id, get_quality_agent(), state, NEXT_STEP,
        save=lambda final: {key: final.get(key) for key in KEPT},
        name="interview_quality",
    )