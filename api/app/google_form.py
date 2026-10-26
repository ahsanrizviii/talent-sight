import logging
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import google_api
from app.cv_files import CVFileError
from app.intake import add_cv
from app.models import Candidate, JobProfile
from app.settings import settings

log = logging.getLogger("talentsight.google_form")


def is_enabled() -> bool:
    return bool(settings.google_form_id and settings.google_refresh_token)


def apply_url(slug: str | None) -> str | None:
    """The form's link with this job's code filled in (None if no form is set up)."""
    if not slug or not settings.google_form_url:
        return None
    if not settings.google_form_job_field:
        return settings.google_form_url
    return (
        f"{settings.google_form_url}?usp=pp_url"
        f"&{settings.google_form_job_field}={quote(slug)}"
    )


def applications_for(slug: str, responses: list[dict]) -> list[dict]:
    """The uploaded files of every response whose job code is this job's slug."""
    found = []
    for response in responses:
        answers = response.get("answers", {}).values()
        texts = [
            a["value"].strip()
            for answer in answers
            for a in answer.get("textAnswers", {}).get("answers", [])
        ]
        if slug not in texts:
            continue
        for answer in answers:
            for upload in answer.get("fileUploadAnswers", {}).get("answers", []):
                found.append(
                    {
                        "ref": f"gform:{response['responseId']}:{upload['fileId']}",
                        "file_id": upload["fileId"],
                        "filename": upload.get("fileName", "cv"),
                        "email": response.get("respondentEmail", ""),
                    }
                )
    return found


def import_applications(db: Session, job: JobProfile) -> dict:
    """Adds every new CV sent for this job. Already imported CVs are skipped.

    Each file is handled on its own: one bad file never stops the others (Q&A 6).
    """
    max_bytes = settings.cv_max_mb * 1024 * 1024
    result = {"imported": 0, "skipped": 0, "failed": []}
    responses = google_api.form_responses(settings.google_form_id)

    for application in applications_for(job.slug, responses):
        if db.scalar(
            select(Candidate.id).where(Candidate.source_ref == application["ref"])
        ):
            result["skipped"] += 1
            continue

        try:
            filename, data = google_api.download_file(
                application["file_id"], max_bytes
            )
            candidate = add_cv(
                db,
                job,
                filename,
                data,
                source="google_form",
                source_ref=application["ref"],
            )
            candidate.email = application["email"]
            db.commit()
            result["imported"] += 1
        except (CVFileError, google_api.GoogleError) as error:
            db.rollback()
            result["failed"].append(
                {"filename": application["filename"], "error": str(error)}
            )

    log.info(
        "google form import",
        extra={"event": "form_import", "job_id": job.id, "count": result["imported"]},
    )
    return result