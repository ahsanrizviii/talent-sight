"""Litmus (F11) for every screened candidate of one job, from the terminal (Task 12.5.1).

Run:  docker compose exec api python -m scripts.litmus_run <job id>
      docker compose exec api python -m scripts.litmus_run <job id> --excluded   (also the excluded CVs)
      docker compose exec api python -m scripts.litmus_run <job id> --again      (check up-to-date ones again)

Uses the real AI, one candidate after another (about 12 AI calls each), so a job of 20 CVs takes a
while and uses Groq's free limits. Candidates already checked and up to date are skipped unless --again,
so it can be stopped and started again without paying twice. Prints each result and the job summary.
"""

import sys

from sqlalchemy import select

from app import litmus_run
from app.db import SessionLocal
from app.models import Candidate, JobProfile, LitmusCheck


def main(args: list[str]) -> int:
    numbers = [a for a in args if a.isdigit()]
    if not numbers:
        print(__doc__)
        return 1
    job_id = int(numbers[0])
    statuses = ("screened", "excluded") if "--excluded" in args else ("screened",)
    again = "--again" in args

    with SessionLocal() as db:
        job = db.get(JobProfile, job_id)
        if job is None:
            print(f"There is no job {job_id}.")
            return 1
        title = job.title
        candidates = db.scalars(
            select(Candidate).where(Candidate.job_profile_id == job_id, Candidate.status.in_(statuses)).order_by(Candidate.id)
        ).all()
        todo = []
        for candidate in candidates:
            if litmus_run.is_busy(db, candidate.id):
                print(f"  skip  {candidate.name or candidate.cv_filename}: a check is already running")
                continue
            latest = litmus_run.latest_of(db, candidate.id)
            if not again and latest and latest.status == "done" and latest.input_hash == litmus_run.input_hash(job, candidate):
                print(f"  skip  {candidate.name or candidate.cv_filename}: already checked and up to date")
                continue
            todo.append(litmus_run.new_row(db, candidate, job, queued=True))
        db.commit()
        check_ids = [row.id for row in todo]

    print(f"Job {job_id} '{title}': {len(check_ids)} candidate(s) to check.")
    for number, check_id in enumerate(check_ids, start=1):
        litmus_run.run_check(check_id)
        with SessionLocal() as db:
            row = db.get(LitmusCheck, check_id)
            candidate = db.get(Candidate, row.candidate_id)
            outcome = (row.result or {}).get("outcome", row.status)
            flags = (row.result or {}).get("flag_count", 0)
            print(
                f"  {number:>2}/{len(check_ids)}  {(candidate.name or candidate.cv_filename)[:28]:<28} "
                f"{outcome:<13} flags {flags}  calls {row.llm_calls:>2}  ${row.cost_usd:.4f}  {row.seconds or 0:.0f}s"
                + (f"  ERROR {row.error}" if row.error else "")
            )

    with SessionLocal() as db:
        summary = litmus_run.job_summary(db, db.get(JobProfile, job_id))
    print()
    print(f"Checked: {summary['checked']}   steady: {summary['outcomes']['steady']}   "
          f"needs review: {summary['outcomes']['needs_review']}   inconclusive: {summary['outcomes']['inconclusive']}")
    print(f"Pass rate: {summary['pass_rate']}%   total cost of all checks for this job: ${summary['total_cost_usd']:.4f}")
    for copy in summary["copies"]:
        print(f"  {copy['label']:<28} checked {copy['runs']:>2}  flagged {copy['flags']:>2}  average move {copy['average_move']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
