"""Adds one CV to a job: check the file, store it, read its text (WBS 5.1, 5.2).

Used by the upload endpoint and by the Google Form import, so both follow the same rules.
"""
from pathlib import Path

from sqlalchemy.orm import Session

from app.cv_files import check_cv, clean_filename, store_cv
from app.cv_text import CVReadError, extract_text
from app.models import Candidate, JobProfile


def add_cv(
    db: Session,
    job: JobProfile,
    filename: str,
    data: bytes,
    source: str = "upload",
    source_ref: str | None = None,
) -> Candidate:
    """Raises CVFileError if the file is refused. A file we cannot read is kept as "unreadable"."""
    filename = clean_filename(filename)
    extension = check_cv(filename, data)
    path = store_cv(job.id, extension, data)

    candidate = Candidate(
        job_profile_id=job.id,
        name=Path(filename).stem[:200],  # until the AI reads the real name from the CV
        source=source,
        source_ref=source_ref,
        cv_filename=filename,
        cv_path=str(path),
    )

    try:
        candidate.cv_text, candidate.text_method = extract_text(path)
    except CVReadError as error:
        candidate.status, candidate.error = "unreadable", str(error)

    db.add(candidate)
    db.flush()  # gives the candidate its id now
    return candidate