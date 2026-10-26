"""What is known about one interview, gathered in one place (Module 13).

The Interview Assistant uses it now; the interview quality and interview scoring features reuse it, so each
of them reads the CV, the job and the transcript the same way. Plain code, no AI.

    context_for(db, session) -> {
        "job":      {"title", "requirements": [text, ...]}   in an HR round: the round's HR topics
        "round_type": "technical" | "hr"
        "cv":       [{"id": "C1", "text": "..."}, ...]   numbered CV facts, so an answer can point to one
        "turns":    [{"n", "speaker", "text", "start_ms", "end_ms"}, ...]   the transcript so far
        "coverage": [{"requirement", "status"}, ...]   explored / weak / not_explored, or mentioned / not_mentioned
    }
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import round_info
from app.agents.evaluation_agent import build_turns
from app.agents.screening_agent import requirements_of
from app.evaluation import transcript_of
from app.models import Candidate, InterviewEvaluation, InterviewSession, JobProfile
from app.requirement_checks import checked_by_documents, interview_items

MAX_CV_LINES = 30  # enough for a full CV, short enough for the AI's free limit


def tidy(text) -> str:
    return " ".join(str(text or "").split())


def names_term(text: str, term: str) -> bool:
    """True when the text names the term as a whole word ("Go" must not match "good")."""
    term = tidy(term).lower()
    return bool(term) and bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text.lower()))


def cv_lines(profile: dict) -> list[dict]:
    """The structured CV as short numbered facts: C1, C2 ... Roles first, then projects and the rest."""
    lines: list[str] = []
    for item in profile.get("work_history", []):
        title, company = tidy(item.get("title")), tidy(item.get("company"))
        if title or company:
            when = " to ".join(p for p in (tidy(item.get("start")), tidy(item.get("end"))) if p)
            line = f"{title} at {company}" + (f" ({when})" if when else "")
            lines.append(line + (f": {tidy(item.get('summary'))}" if tidy(item.get("summary")) else ""))
    years = profile.get("total_experience_years") or 0
    if years:
        lines.append(f"{years:g} years of work experience in total")
    for item in profile.get("projects", []):
        if tidy(item.get("name")):
            lines.append(f"Project {tidy(item['name'])}" + (f": {tidy(item.get('summary'))}" if tidy(item.get("summary")) else ""))
    for item in profile.get("education", []):
        if tidy(item.get("degree")) or tidy(item.get("institution")):
            year = f" ({tidy(item.get('year'))})" if tidy(item.get("year")) else ""
            lines.append(f"Education: {tidy(item.get('degree'))}, {tidy(item.get('institution'))}{year}")
    for name in profile.get("certifications", []):
        if tidy(name):
            lines.append(f"Certification: {tidy(name)}")
    skills = [tidy(s) for s in profile.get("skills", []) if tidy(s)]
    if skills:
        lines.append("Skills: " + ", ".join(dict.fromkeys(skills)))
    languages = [tidy(s) for s in profile.get("languages", []) if tidy(s)]
    if languages:
        lines.append("Languages: " + ", ".join(languages))
    return [{"id": f"C{n}", "text": text} for n, text in enumerate(lines[:MAX_CV_LINES], start=1)]


def coverage_for(db: Session, session_id: int, requirements: list[str], turns: list[dict]) -> list[dict]:
    """How far each requirement has been talked about.

    After the answers are analysed (Module 9) its coverage is used: explored, weak or not_explored.
    Before that (for example during the interview) plain code checks whether the requirement has been
    named yet: mentioned or not_mentioned.
    """
    analysed = db.scalar(
        select(InterviewEvaluation)
        .where(InterviewEvaluation.session_id == session_id, InterviewEvaluation.status == "done")
        .order_by(InterviewEvaluation.finished_at.desc(), InterviewEvaluation.id.desc())
        .limit(1)
    )
    # Degrees, certificates and written skills are checked with documents, never in the interview.
    found = interview_items((analysed.result or {}).get("coverage", [])) if analysed else []
    found = [item for item in found if item["requirement"] in requirements] if requirements else found
    if found:
        return [{"requirement": item["requirement"], "status": item["status"]} for item in found]
    said = " ".join(turn["text"] for turn in turns)
    return [{"requirement": r, "status": "mentioned" if names_term(said, r) else "not_mentioned"} for r in requirements]


def context_for(db: Session, session: InterviewSession) -> dict:
    candidate = db.get(Candidate, session.candidate_id)
    job = db.get(JobProfile, candidate.job_profile_id)
    found = round_info.round_of(job, session.round_number or 1)
    if found["type"] == "hr":
        requirements = round_info.hr_topics(found["focus"])
    else:
        requirements = [r["requirement"] for r in requirements_of(job) if not checked_by_documents(r)]
    turns = build_turns(transcript_of(db, session.id))
    return {
        "round_type": found["type"],
        "job": {"title": job.title, "requirements": requirements},
        "cv": cv_lines(candidate.profile or {}),
        "turns": turns,
        "coverage": coverage_for(db, session.id, requirements, turns),
    }




def analysis_of(db: Session, session_id: int) -> InterviewEvaluation | None:
    """The newest finished answer analysis of this interview (Module 9), or None."""
    return db.scalar(
        select(InterviewEvaluation)
        .where(InterviewEvaluation.session_id == session_id, InterviewEvaluation.status == "done")
        .order_by(InterviewEvaluation.finished_at.desc(), InterviewEvaluation.id.desc())
        .limit(1)
    )


def review_context(db: Session, session: InterviewSession) -> dict:
    """context_for plus the answer analysis: the question-answer pairs with their scores and the full
    coverage (which also says which requirements are mandatory). Used by the interview quality review
    and the interview score, after the answers have been analysed."""
    analysed = analysis_of(db, session.id)
    result = (analysed.result or {}) if analysed else {}
    context = context_for(db, session)
    return {
        **context,
        "turns": result.get("turns") or context["turns"],  # the same numbering the analysis used
        "pairs": result.get("pairs", []),
        # The full coverage (with "mandatory"), without the document checks: they are not the interview's job.
        "coverage": interview_items(result.get("coverage")) or context["coverage"],
    }