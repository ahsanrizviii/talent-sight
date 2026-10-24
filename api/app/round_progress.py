"""Where a candidate stands in the interview rounds of their job (hiring rounds). Read-only.

Kept apart from hiring_rounds.py, which books interviews and sends e-mails, so the interview and
workspace routers can use it without importing each other.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import round_info
from app.models import Candidate, HiringDecision, InterviewScore, JobProfile, RoundClosure, RoundDecision


def decisions_of(db: Session, candidate_id: int) -> dict[int, str]:
    """{round number: "passed" | "rejected"} for one candidate."""
    rows = db.execute(
        select(RoundDecision.round_number, RoundDecision.outcome).where(RoundDecision.candidate_id == candidate_id)
    ).all()
    return {number: outcome for number, outcome in rows}


def current_round(db: Session, candidate: Candidate) -> int:
    """The round this candidate is in now: 1 + the rounds they have passed, in order.
    A number past the job's last round means they have passed every round."""
    passed = decisions_of(db, candidate.id)
    number = 1
    while passed.get(number) == "passed":
        number += 1
    return number


def why_not_invitable(db: Session, candidate: Candidate, job: JobProfile) -> str:
    """Why this candidate cannot get an interview now, or "" when they can (for their current round)."""
    decisions = decisions_of(db, candidate.id)
    if "rejected" in decisions.values():
        return "This candidate did not pass an earlier round."
    if db.scalar(select(HiringDecision).where(HiringDecision.candidate_id == candidate.id)) is not None:
        return "A hiring decision has already been made for this candidate."
    number = current_round(db, candidate)
    if number > round_info.total_rounds(job):
        return "This candidate has passed every interview round."
    closed = db.scalar(
        select(RoundClosure).where(RoundClosure.job_profile_id == job.id, RoundClosure.round_number == number)
    )
    if closed is not None:
        return f"Round {number} is closed."
    return ""


def interview_score_of(db: Session, session_id: int) -> float | None:
    """The interview's own score (F9, 0-100), or None when it has not been scored yet."""
    row = db.scalar(select(InterviewScore).where(InterviewScore.session_id == session_id))
    if row is None or row.status != "done":
        return None
    overall = (row.result or {}).get("overall")
    return float(overall) if isinstance(overall, (int, float)) else None


def stage_maps(db: Session) -> tuple[dict[int, dict[int, str]], dict[int, str]]:
    """For every candidate at once: their round decisions, and their hiring decision."""
    rounds: dict[int, dict[int, str]] = {}
    for candidate_id, number, outcome in db.execute(
        select(RoundDecision.candidate_id, RoundDecision.round_number, RoundDecision.outcome)
    ).all():
        rounds.setdefault(candidate_id, {})[number] = outcome
    hiring = {candidate_id: decision for candidate_id, decision in db.execute(
        select(HiringDecision.candidate_id, HiringDecision.decision)
    ).all()}
    return rounds, hiring
