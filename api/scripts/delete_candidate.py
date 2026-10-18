"""Deletes one candidate and everything about them, from the command line (Module 11, N19).

The same delete as the "Delete candidate" button, for an administrator without the web app:

    docker compose exec api python -m scripts.delete_candidate 12          shows what would be deleted
    docker compose exec api python -m scripts.delete_candidate 12 --yes    deletes it
"""

import argparse
import sys

from app.db import SessionLocal
from app.models import Candidate
from app.privacy import delete_candidate, what_is_kept


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete a candidate and all their data (N19).")
    parser.add_argument("candidate_id", type=int, help="the candidate's number (from the address /candidates/<number>)")
    parser.add_argument("--yes", action="store_true", help="really delete; without it, only show what would go")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        candidate = db.get(Candidate, args.candidate_id)
        if candidate is None:
            print(f"There is no candidate {args.candidate_id}.")
            return 1

        print(f"Candidate {candidate.id}: {candidate.name or candidate.cv_filename} (job {candidate.job_profile_id})")
        print("CV file: " + ("yes" if candidate.cv_path else "none"))
        for name, count in what_is_kept(db, candidate.id).items():
            print(f"{name}: {count}")

        if not args.yes:
            print("Nothing was deleted. Run again with --yes to delete all of this.")
            return 0
        delete_candidate(db, candidate)
        print(f"Candidate {args.candidate_id} and all their data were deleted.")
        return 0


if __name__ == "__main__":
    sys.exit(main())