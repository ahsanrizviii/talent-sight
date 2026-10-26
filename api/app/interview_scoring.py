"""Running the Interview Scoring Agent for one interview, in the background (Module 13, F9)."""

from app import agent_runs
from app.agents.interview_score_agent import get_interview_score_agent
from app.db import SessionLocal
from app.interview_context import review_context
from app.models import InterviewScore, InterviewSession

FIRST_STEP = "Measuring how far the requirements (or HR topics) were covered"
NEXT_STEP = {
    "measure_alignment": "Scoring the answers in five parts",
    "score": "Checking each part against the candidate's answers",
}


def run_scoring(row_id: int) -> None:
    with SessionLocal() as db:
        row = db.get(InterviewScore, row_id)
        if row is None:
            return
        context = review_context(db, db.get(InterviewSession, row.session_id))
    state = {key: context[key] for key in ("job", "turns", "pairs", "coverage", "round_type")}
    agent_runs.run(
        InterviewScore, row_id, get_interview_score_agent(), state, NEXT_STEP,
        save=lambda final: {"dimensions": final["dimensions"], "overall": final["overall"], "answers": final["answers"]},
        name="interview_score",
    )