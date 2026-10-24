"""The interview rounds of a job, read from job.interview_rounds (hiring rounds).

Plain code with no database access, so the e-mails, the calendar entry and every list can use it
without importing each other. A job saved before rounds existed has one round called "Interview".
"""

from app.models import DEFAULT_ROUNDS, JobProfile


def rounds_of(job: JobProfile) -> list[dict]:
    """[{"number": 1, "name": "HR interview", "focus": "..."}, ...] in order. Never empty."""
    saved = job.interview_rounds or DEFAULT_ROUNDS
    rounds = []
    for number, item in enumerate(saved, start=1):
        name = " ".join(str(item.get("name") or "").split()) or f"Round {number}"
        focus = " ".join(str(item.get("focus") or "").split())
        rounds.append({"number": number, "name": name, "focus": focus})
    return rounds


def total_rounds(job: JobProfile) -> int:
    return len(rounds_of(job))


def round_of(job: JobProfile, number: int) -> dict:
    """One round by its number. A number past the end (a round removed later) still gets a name."""
    rounds = rounds_of(job)
    if 1 <= number <= len(rounds):
        return rounds[number - 1]
    return {"number": number, "name": f"Round {number}", "focus": ""}


def label(job: JobProfile, number: int) -> str:
    """"Round 2 · Technical interview": how a round is named on screens and in the report."""
    return f"Round {number} · {round_of(job, number)['name']}"
