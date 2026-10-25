"""Running the Assessment Agent for one candidate, in the background (Module 10, Task 10.1.2).

The interviewer asks for the assessment once the interview answers have been analysed (Module 9).
The request is answered at once and the agent works afterwards. While it works, the row's "step"
says what it is doing, so the screen can show progress.
"""

import logging
import time
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import round_info
from app.agents.assessment_agent import get_assessment_agent, report_of
from app.db import SessionLocal
from app.models import (
    Assessment,
    Candidate,
    CandidateScore,
    InterviewEvaluation,
    InterviewSession,
    JobProfile,
    RequirementVerdict,
)
from app.scoring import DIMENSIONS

log = logging.getLogger("talentsight.assessment")

FIRST_STEP = "Collecting the evidence from the CV and the interview"
# What the agent does after each step, shown on the screen while it works.
NEXT_STEP = {
    "gather_evidence": "Looking for evidence gaps",
    "find_gaps": "Working out the overall position",
    "compute_position": "Writing the strengths, weaknesses and follow-ups",
    "write_findings": "Checking that every finding points to its evidence",
}
CRASHED = "Something went wrong while writing the assessment. Please try again."
INTERRUPTED = "The assessment was cut off by a restart. Please run it again."
NOT_SCORED = "Screen and score this candidate first."
NOT_ANALYSED = "Analyse the interview answers first (Results page)."


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def score_of(db: Session, candidate_id: int) -> CandidateScore | None:
    return db.scalar(select(CandidateScore).where(CandidateScore.candidate_id == candidate_id))


def latest_analysis(db: Session, candidate_id: int) -> tuple[InterviewEvaluation, InterviewSession] | None:
    """The newest finished answer analysis of the candidate's interviews (Module 9), with its interview."""
    found = db.execute(
        select(InterviewEvaluation, InterviewSession)
        .join(InterviewSession, InterviewEvaluation.session_id == InterviewSession.id)
        .where(InterviewSession.candidate_id == candidate_id, InterviewEvaluation.status == "done")
        .order_by(InterviewEvaluation.finished_at.desc(), InterviewEvaluation.id.desc())
        .limit(1)
    ).first()
    return (found[0], found[1]) if found else None


def analyses_by_round(db: Session, candidate_id: int) -> list[tuple[InterviewEvaluation, InterviewSession]]:
    """The finished answer analysis of each interview round, in round order (hiring rounds). When a
    round has more than one analysed interview, the newest counts."""
    found = db.execute(
        select(InterviewEvaluation, InterviewSession)
        .join(InterviewSession, InterviewEvaluation.session_id == InterviewSession.id)
        .where(InterviewSession.candidate_id == candidate_id, InterviewEvaluation.status == "done")
        .order_by(InterviewSession.round_number, InterviewSession.id, InterviewEvaluation.id)
    ).all()
    by_round: dict[int, tuple[InterviewEvaluation, InterviewSession]] = {}
    for evaluation, session in found:
        by_round[session.round_number or 1] = (evaluation, session)
    return [by_round[number] for number in sorted(by_round)]


COVERAGE_ORDER = {"explored": 2, "weak": 1, "not_explored": 0}


def merge_analyses(job: JobProfile, items: list[tuple[InterviewEvaluation, InterviewSession]]) -> dict:
    """One answer analysis made from every round, so the report weighs the whole hiring process.

    The question-answer pairs of all rounds are numbered on (Q1, Q2 ... across the rounds) and each
    question says its round. A requirement counts as explored when any round explored it, with the
    best answer of all rounds. With one technical round the analysis is used as it is.

    HR rounds: their answers count towards the answer quality, but their coverage is about HR topics,
    so it never makes a job requirement look explored or unexplored."""
    def is_hr(evaluation: InterviewEvaluation, session: InterviewSession) -> bool:
        saved = (evaluation.result or {}).get("round_type")
        return saved == "hr" if saved else round_info.is_hr(job, session.round_number)

    technical = sum(1 for evaluation, session in items if not is_hr(evaluation, session))
    if len(items) == 1 and technical == 1:
        return {**(items[0][0].result or {}), "technical_rounds": 1}
    pairs: list[dict] = []
    coverage: dict[str, dict] = {}
    offset = 0
    for evaluation, session in items:
        result = evaluation.result or {}
        hr_round = is_hr(evaluation, session)
        label = round_info.label(job, session.round_number or 1)
        new_id = {}
        for pair in result.get("pairs", []):
            new_id[pair["id"]] = pair["id"] + offset
            pairs.append({**pair, "id": pair["id"] + offset, "question": f"[{label}] {pair.get('question', '')}"})
        offset = max([offset, *new_id.values()])
        if hr_round:
            continue  # HR topics are not job requirements
        for item in result.get("coverage", []):
            key = " ".join(str(item.get("requirement", "")).lower().split())
            linked = [new_id[p] for p in item.get("pairs", []) if p in new_id]
            merged = coverage.get(key)
            if merged is None:
                coverage[key] = {**item, "pairs": linked}
                continue
            merged["pairs"] = merged.get("pairs", []) + linked
            scores = [s for s in (merged.get("best_score"), item.get("best_score")) if s is not None]
            merged["best_score"] = max(scores) if scores else None
            if COVERAGE_ORDER.get(item.get("status"), 0) > COVERAGE_ORDER.get(merged.get("status"), 0):
                merged["status"] = item["status"]
    job_related = [p for p in pairs if p.get("kind") == "job_related"]
    scored = [p["overall"] for p in job_related if p.get("overall") is not None]
    lines = list(coverage.values())
    return {
        "pairs": pairs,
        "coverage": lines,
        "technical_rounds": technical,
        "summary": {
            "pairs": len(pairs),
            "job_related": len(job_related),
            "small_talk": len(pairs) - len(job_related),
            "scored": len(scored),
            "average": round(sum(scored) / len(scored)) if scored else None,
            "not_explored": sum(1 for c in lines if c.get("status") == "not_explored"),
            "weak": sum(1 for c in lines if c.get("status") == "weak"),
        },
    }


def assessment_of(db: Session, candidate_id: int) -> Assessment | None:
    return db.scalar(select(Assessment).where(Assessment.candidate_id == candidate_id))


def is_outdated(db: Session, row: Assessment) -> bool:
    """True when the interview answers were analysed again after this assessment was made."""
    if row.status != "done":
        return False
    latest = latest_analysis(db, row.candidate_id)
    return bool(latest and latest[0].finished_at and row.created_at and latest[0].finished_at > row.created_at)


def inputs_for(db: Session, candidate: Candidate) -> dict:
    """What the agent needs, read from the screening, the CV score and the answer analysis."""
    job = db.get(JobProfile, candidate.job_profile_id)
    score = score_of(db, candidate.id)
    verdicts = db.scalars(
        select(RequirementVerdict).where(RequirementVerdict.candidate_id == candidate.id).order_by(RequirementVerdict.id)
    )
    analysis = merge_analyses(job, analyses_by_round(db, candidate.id))
    weights = job.weights or {}
    return {
        "job": {"title": job.title},
        "verdicts": [
            {"requirement": v.requirement, "kind": v.kind, "mandatory": v.mandatory, "verdict": v.verdict, "explanation": v.explanation}
            for v in verdicts
        ],
        "cv_score": {
            "overall": score.overall,
            "dimensions": [
                {
                    "dimension": key,
                    "label": label,
                    "score": getattr(score, key),
                    "weight": weights.get(key, 0),
                    "justification": (score.justification or {}).get(key, ""),
                }
                for key, label in DIMENSIONS.items()
            ],
        },
        "analysis": analysis,
    }


def start_assessment(db: Session, candidate: Candidate) -> Assessment:
    """Checks the three earlier results exist and marks the assessment "running". The work is run_assessment()."""
    if candidate.status != "screened" or score_of(db, candidate.id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_SCORED)
    if latest_analysis(db, candidate.id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_ANALYSED)

    row = assessment_of(db, candidate.id)
    if row is not None and row.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "This candidate is already being assessed.")
    if row is None:
        row = Assessment(candidate_id=candidate.id)
        db.add(row)
    # Assessing again starts from a clean slate: the old report is replaced, never mixed in.
    row.status, row.step, row.error, row.report, row.overall_position = "running", FIRST_STEP, "", {}, ""
    row.created_at, row.finished_at, row.seconds = utcnow(), None, None
    db.commit()
    db.refresh(row)
    return row


def set_step(assessment_id: int, step: str) -> None:
    with SessionLocal() as db:
        db.execute(update(Assessment).where(Assessment.id == assessment_id).values(step=step))
        db.commit()


def run_assessment(assessment_id: int) -> None:
    """Runs the agent and stores the report. Runs after the request has been answered."""
    started = time.monotonic()
    with SessionLocal() as db:
        row = db.get(Assessment, assessment_id)
        if row is None:
            return
        candidate = db.get(Candidate, row.candidate_id)
        evaluation, session = latest_analysis(db, candidate.id)
        state = inputs_for(db, candidate)
        job = db.get(JobProfile, candidate.job_profile_id)
        rounds_used = [
            {
                "session_id": used.id,
                "round_number": used.round_number or 1,
                "round_name": round_info.round_of(job, used.round_number or 1)["name"],
                "held_at": (used.started_at or used.scheduled_at).isoformat(),
            }
            for _, used in analyses_by_round(db, candidate.id)
        ]
        about = {
            "interviews": rounds_used,
            "candidate": {"id": candidate.id, "name": candidate.name or candidate.cv_filename},
            "job": {"id": candidate.job_profile_id, "title": state["job"]["title"]},
            "interview": {
                "session_id": session.id,
                "held_at": (session.started_at or session.scheduled_at).isoformat(),
                "analysed_at": evaluation.finished_at.isoformat() if evaluation.finished_at else None,
            },
        }
    # The database connection is closed while the AI works.

    final: dict = {}
    try:
        for mode, chunk in get_assessment_agent().stream(state, stream_mode=["updates", "values"]):
            if mode == "values":
                final = chunk  # the whole state after the latest step
            else:
                for node in chunk:  # the step that just finished
                    if node in NEXT_STEP:
                        set_step(assessment_id, NEXT_STEP[node])
        error = final.get("error", "")
    except Exception as crash:  # an unexpected bug must not leave the assessment "running" for ever
        log.error("assessment crashed", exc_info=crash, extra={"event": "assessment_crash", "candidate_id": about["candidate"]["id"]})
        error = CRASHED

    with SessionLocal() as db:
        row = db.get(Assessment, assessment_id)
        if row is None:
            return  # the candidate was deleted while the agent worked (N19)
        row.status, row.step, row.error = ("failed" if error else "done"), "", error
        if not error:
            row.report = {**about, **report_of(final)}
            row.overall_position = final["position"]["code"]
        row.finished_at = utcnow()
        row.seconds = round(time.monotonic() - started, 1)
        db.commit()

    log.info(
        "assessment finished",
        extra={
            "event": "assessment_failed" if error else "assessment_done",
            "candidate_id": about["candidate"]["id"],
            "seconds": round(time.monotonic() - started, 1),
        },
    )


def mark_interrupted_assessments() -> None:
    """At start-up: an assessment still "running" was cut off by a restart. It can be run again."""
    with SessionLocal() as db:
        db.execute(update(Assessment).where(Assessment.status == "running").values(status="failed", step="", error=INTERRUPTED))
        db.commit()