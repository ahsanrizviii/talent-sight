"""The interview rounds of a job, read from job.interview_rounds (hiring rounds).

Plain code with no database access, so the e-mails, the calendar entry and every list can use it
without importing each other. A job saved before rounds existed has one round called "Interview".

Every round has a type: "technical" (judged on the job's requirements) or "hr" (judged on HR topics such
as communication, motivation and teamwork). A round saved before types existed gets one from its name.
"""

import re

from app.models import DEFAULT_ROUNDS, JobProfile

ROUND_TYPES = ("technical", "hr")
HR_WORDS = re.compile(
    r"(?<![a-z])(hr|human resources?|behaviou?ral|culture|cultural fit|soft skills?|personality|people)(?![a-z])",
    re.IGNORECASE,
)

# What an HR round is judged on when its focus text names nothing. Used by the answer analysis,
# the interview score, the quality review and the Interview Assistant.
DEFAULT_HR_TOPICS = [
    "Communication",
    "Motivation and fit for the role",
    "Teamwork and collaboration",
    "Situational judgement (handling difficult situations)",
    "Professionalism and attitude",
    "Expectations: salary, notice period and joining date",
]


def guess_type(name: str, focus: str = "") -> str:
    """"hr" when the round's name (or, failing that, its focus) says it is an HR round, else "technical"."""
    if HR_WORDS.search(name or ""):
        return "hr"
    if "technical" in (name or "").lower():
        return "technical"
    return "hr" if HR_WORDS.search(focus or "") else "technical"


def type_or_guess(item: dict) -> str:
    saved = str(item.get("type") or "").strip().lower()
    return saved if saved in ROUND_TYPES else guess_type(str(item.get("name") or ""), str(item.get("focus") or ""))


def rounds_of(job: JobProfile) -> list[dict]:
    """[{"number": 1, "name": "HR interview", "focus": "...", "type": "hr"}, ...] in order. Never empty."""
    saved = job.interview_rounds or DEFAULT_ROUNDS
    rounds = []
    for number, item in enumerate(saved, start=1):
        name = " ".join(str(item.get("name") or "").split()) or f"Round {number}"
        focus = " ".join(str(item.get("focus") or "").split())
        rounds.append({"number": number, "name": name, "focus": focus, "type": type_or_guess(item)})
    return rounds


def total_rounds(job: JobProfile) -> int:
    return len(rounds_of(job))


def round_of(job: JobProfile, number: int) -> dict:
    """One round by its number. A number past the end (a round removed later) still gets a name."""
    rounds = rounds_of(job)
    if 1 <= number <= len(rounds):
        return rounds[number - 1]
    return {"number": number, "name": f"Round {number}", "focus": "", "type": "technical"}


def is_hr(job: JobProfile, number: int | None) -> bool:
    return round_of(job, number or 1)["type"] == "hr"


def hr_topics(focus: str) -> list[str]:
    """The topics an HR round is judged on: the ones its focus text lists (split on commas, "and",
    semicolons or full stops), or the default list when the focus names fewer than two."""
    parts = [p.strip(" .-") for p in re.split(r",|;|\.|\band\b|\n", focus or "", flags=re.IGNORECASE)]
    named = [p[:1].upper() + p[1:] for p in parts if len(p) >= 3]
    return list(dict.fromkeys(named))[:8] if len(named) >= 2 else list(DEFAULT_HR_TOPICS)


def label(job: JobProfile, number: int) -> str:
    """"Round 2 · Technical interview": how a round is named on screens and in the report."""
    return f"Round {number} · {round_of(job, number)['name']}"
