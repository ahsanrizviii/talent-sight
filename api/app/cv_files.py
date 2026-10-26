from pathlib import Path
from uuid import uuid4

from app.settings import settings

SIGNATURES = {".pdf": b"%PDF", ".docx": b"PK\x03\x04"}

class CVFileError(ValueError):
    """The file cannot be accepted as a CV. The message says why, for the interviewer."""

def clean_filename(filename: str | None) -> str:
    """The original name without any folder part, at most 200 characters."""
    name = Path((filename or "").replace("\\", "/")).name.strip()
    return (name or "cv")[:200]

def check_cv(filename: str, data: bytes) -> str:

    extension = Path(filename).suffix.lower()
    if extension not in SIGNATURES:
        raise CVFileError("Only PDF and DOCX files are accepted.")
    if not data:
        raise CVFileError("The file is empty.")
    if len(data) > settings.cv_max_mb * 1024 * 1024:
        raise CVFileError(f"The file is larger than {settings.cv_max_mb} MB.")
    if not data.startswith(SIGNATURES[extension]):
        raise CVFileError(f"The file is not a real {extension[1:].upper()} file.")
    return extension

def store_cv(job_id: int, extension: str, data: bytes) -> Path:

    folder = Path(settings.cv_upload_dir) / f"job-{job_id}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid4().hex}{extension}"
    path.write_bytes(data)
    return path

def delete_cv_file(path: str) -> None:
    if path:
        Path(path).unlink(missing_ok=True)