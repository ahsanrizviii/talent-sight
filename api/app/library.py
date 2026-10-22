"""The Library: every document the AI reads, managed from the website (Task 4.3.2 follow-up).

Three kinds of document, each in its own folder on the "library" Docker volume (LIBRARY_DIR):
    policies   the hiring policies the JD Agent follows when it writes a job (Module 4)
    skills     the skills references the Evaluation Agent compares answers with (Module 9)
    holidays   the public holiday calendars the interview planner skips (Module 7)

The first time the API starts, the documents that ship with the code (api/knowledge/) are copied into
the library, so nothing changes for an existing install. From then on the library is the truth: a
document uploaded, replaced or removed on the Library page is read again in the background, and a
file kept on the volume survives a rebuild of the image.

Until a kind has been set up (for example in a test, or when the volume cannot be written), the
documents that ship with the code are read instead, so the AI never runs without its knowledge.
"""

import logging
import re
import shutil
from pathlib import Path

from app.settings import settings

log = logging.getLogger("talentsight.library")

BUILT_IN = Path(__file__).resolve().parent.parent / "knowledge"
MARKER = ".set-up"  # written once a kind's folder has been filled from the built-in documents
MAX_FILE_BYTES = 10 * 1024 * 1024

KINDS: dict[str, dict] = {
    "policies": {
        "label": "Hiring policies",
        "used_for": "Followed by the AI when it writes a job. You choose which ones apply when you start a new job.",
        "types": (".pdf",),
        "built_in": [BUILT_IN / "bjit-hiring-policies.pdf"],
    },
    "skills": {
        "label": "Skills references",
        "used_for": "Compared with the candidate's technical answers, so an accuracy score rests on documentation.",
        "types": (".pdf", ".md"),
        "built_in": "skills",
    },
    "holidays": {
        "label": "Holiday calendars",
        "used_for": "Public holidays are skipped when interview times are planned. A PDF takes about a minute to read.",
        "types": (".pdf", ".txt"),
        "built_in": "holidays",
    },
}

UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class LibraryError(Exception):
    """A document that cannot be accepted, with a sentence the user can act on."""


def folder(kind: str) -> Path:
    return Path(settings.library_dir) / kind


def is_set_up(kind: str) -> bool:
    return (folder(kind) / MARKER).exists()


def built_in_files(kind: str) -> list[Path]:
    source = KINDS[kind]["built_in"]
    if isinstance(source, list):
        return [path for path in source if path.is_file()]
    directory = BUILT_IN / source
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in KINDS[kind]["types"])


def files_of(kind: str) -> list[Path]:
    """The documents of one kind that the AI reads now, in a fixed order."""
    if not is_set_up(kind):
        return built_in_files(kind)
    return sorted(
        p for p in folder(kind).iterdir() if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in KINDS[kind]["types"]
    )


def reading_folder(kind: str) -> Path:
    """The folder the documents of one kind are read from (for readers that list a folder themselves)."""
    if is_set_up(kind):
        return folder(kind)
    source = KINDS[kind]["built_in"]
    return BUILT_IN / source if isinstance(source, str) else BUILT_IN


def set_up() -> None:
    """At start-up: fills each kind's folder once from the built-in documents. Never raises."""
    for kind in KINDS:
        if is_set_up(kind):
            continue
        try:
            folder(kind).mkdir(parents=True, exist_ok=True)
            for path in built_in_files(kind):
                target = folder(kind) / path.name
                if not target.exists():
                    shutil.copy2(path, target)
            (folder(kind) / MARKER).write_text("The documents of this folder are managed on the Library page.\n")
            log.info(f"library {kind} set up", extra={"event": "library_set_up"})
        except OSError as error:  # a read-only or missing volume: keep reading the built-in documents
            log.warning(f"library {kind} could not be set up", exc_info=error, extra={"event": "library_set_up_failed"})


def safe_name(filename: str) -> str:
    """A file name that is safe to keep: no folders, no odd characters. 'My CV (1).pdf' -> 'My-CV-1-.pdf'."""
    name = UNSAFE.sub("-", Path(filename or "").name).strip("-.")
    return name[:120]


def check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise LibraryError("There is no such kind of document.")


def save(kind: str, filename: str, data: bytes) -> Path:
    """Stores an uploaded document. A document with the same name is replaced."""
    check_kind(kind)
    name = safe_name(filename)
    allowed = KINDS[kind]["types"]
    if not name or Path(name).suffix.lower() not in allowed:
        raise LibraryError(f"Only {', '.join(t.lstrip('.').upper() for t in allowed)} files can be added here.")
    if not data:
        raise LibraryError("The file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise LibraryError("The file is larger than 10 MB.")
    if Path(name).suffix.lower() == ".pdf" and not data.startswith(b"%PDF"):
        raise LibraryError("This file is not a readable PDF.")
    set_up()
    target = folder(kind) / name
    target.write_bytes(data)
    log.info(f"library {kind}: {name} saved", extra={"event": "library_saved"})
    return target


def find(kind: str, name: str) -> Path:
    check_kind(kind)
    path = folder(kind) / safe_name(name)
    if not is_set_up(kind) or not path.is_file() or path.name.startswith("."):
        raise LibraryError("That document is not in the library.")
    return path


def remove(kind: str, name: str) -> None:
    path = find(kind, name)
    path.unlink()
    log.info(f"library {kind}: {path.name} removed", extra={"event": "library_removed"})
