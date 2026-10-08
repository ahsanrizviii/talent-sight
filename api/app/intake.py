from pathlib import Path

from sqlalchemy.orm import Session

from app.cv_files import check_cv, clean_filename, store_cv
from app.models import Candidate, JobProfile


def add_cv(
    db: Session,
    job: JobProfile,
    filename: str,
    data: bytes,
    source: str = "upload",
    source_ref: str | None = None,
) -> Candidate:

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
    db.add(candidate)
    db.flush()  
    return candidate