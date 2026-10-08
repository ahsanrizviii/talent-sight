"""Turns the four dimension scores into one total with the job's weights (WBS 6.2).

Plain arithmetic, no AI: the same scores and weights always give the same total.
"""

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Candidate, CandidateScore, JobProfile

DIMENSIONS = {
    "technical_skills": "Technical skills",
    "experience": "Relevant experience",
    "qualifications": "Qualifications",
    "jd_match": "Job description match",
}


def aggregate(scores: dict, weights: dict) -> float:
    """The weighted average of the four scores, 0-100, rounded half up to one decimal (77.75 -> 77.8)."""
    total_weight = sum(weights[d] for d in DIMENSIONS)
    average = sum(scores[d] * weights[d] for d in DIMENSIONS) / total_weight
    return math.floor(average * 10 + 0.5) / 10


def save_scores(db: Session, candidate: Candidate, scores: dict, weights: dict) -> None:
    """Stores the scores and their justifications (Q&A 46). scores = {dimension: {score, justification}}."""
    numbers = {d: scores[d]["score"] for d in DIMENSIONS}
    db.add(
        CandidateScore(
            candidate_id=candidate.id,
            **numbers,
            overall=aggregate(numbers, weights),
            justification={d: scores[d]["justification"] for d in DIMENSIONS},
        )
    )


def rescore_job(db: Session, job: JobProfile) -> None:
    """After the weights change, recomputes every total of the job. No AI call is needed."""
    rows = db.scalars(
        select(CandidateScore).join(Candidate).where(Candidate.job_profile_id == job.id)
    ).all()
    for row in rows:
        row.overall = aggregate({d: getattr(row, d) for d in DIMENSIONS}, job.weights)
    db.commit()