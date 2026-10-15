"""How many CVs arrived for a job since this person last opened it (the "new CVs" notice)."""

from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Candidate, JobVisit

SAME_VISIT_SECONDS = 60  # opening the job again this soon (a refresh) is still the same visit


class VisitOut(BaseModel):
    new_cvs: int  # CVs that arrived after `since`; on the first visit ever, all CVs
    since: datetime | None  # the previous visit; None = this person never opened the job before


def _now() -> datetime:
    return datetime.now(timezone.utc)


def record_visit(db: Session, interviewer_id: int, job_id: int, now: datetime | None = None) -> VisitOut:
    """Notes that the job was opened and counts the CVs that are new to this person."""
    now = now or _now()
    row = db.scalar(select(JobVisit).where(JobVisit.interviewer_id == interviewer_id, JobVisit.job_profile_id == job_id))
    if row is None:
        row = JobVisit(interviewer_id=interviewer_id, job_profile_id=job_id, seen_at=now, previous_seen_at=None)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            # Two opens at the same moment (a double click): the other one already made the row.
            db.rollback()
            return record_visit(db, interviewer_id, job_id, now)
    elif (now - row.seen_at).total_seconds() > SAME_VISIT_SECONDS:
        row.previous_seen_at = row.seen_at
        row.seen_at = now

    since = row.previous_seen_at
    query = select(func.count()).select_from(Candidate).where(Candidate.job_profile_id == job_id)
    if since is not None:
        query = query.where(Candidate.created_at > since)
    new_cvs = db.scalar(query) or 0
    db.commit()
    return VisitOut(new_cvs=new_cvs, since=since)
