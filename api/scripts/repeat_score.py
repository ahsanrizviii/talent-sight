"""Repeat-run test (B2): scores the same CV for the same job three times with the real AI.

Run:  docker compose exec api python -m scripts.repeat_score <candidate id>
The candidate must be screened already (it needs a profile and verdicts).
Passes when the totals of the three runs are at most 5 points apart.
"""

import sys

from sqlalchemy import select

from app.agents.screening_agent import job_for_agent, score_candidate
from app.db import SessionLocal
from app.models import Candidate, JobProfile, RequirementVerdict
from app.scoring import DIMENSIONS, aggregate

TIMES = 3
ALLOWED_SPREAD = 5  # points


def main(candidate_id: int) -> int:
    with SessionLocal() as db:
        candidate = db.get(Candidate, candidate_id)
        if candidate is None or not candidate.profile:
            print("Screen this candidate first.")
            return 1
        job = db.get(JobProfile, candidate.job_profile_id)
        verdicts = db.scalars(select(RequirementVerdict).where(RequirementVerdict.candidate_id == candidate_id)).all()
        state = {
            "job": job_for_agent(job),
            "profile": candidate.profile,
            "verdicts": [{"requirement": v.requirement, "verdict": v.verdict, "explanation": v.explanation} for v in verdicts],
        }
        totals = []
        print(f"Candidate {candidate_id}, job '{job.title}', weights {job.weights}")
        for run in range(1, TIMES + 1):
            result = score_candidate(state)
            if result.get("error"):
                print(f"Run {run}: {result['error']}")
                return 1
            numbers = {d: result["scores"][d]["score"] for d in DIMENSIONS}
            totals.append(aggregate(numbers, job.weights))
            print(f"Run {run}: {numbers} -> total {totals[-1]}")
    spread = max(totals) - min(totals)
    print(f"Spread of the totals: {spread:.1f} points ({'PASS' if spread <= ALLOWED_SPREAD else 'FAIL'}, allowed {ALLOWED_SPREAD})")
    return 0 if spread <= ALLOWED_SPREAD else 1


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1])))