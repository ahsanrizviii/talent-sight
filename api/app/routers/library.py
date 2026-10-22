"""The Library page: the documents the AI reads, added, replaced and removed from the website.

Interviewers only. After every change the documents of that kind are read again in the background
(the hiring policies and skills references are embedded again; a holiday PDF is read with OCR and AI,
which takes about a minute), and the page shows "Reading…" until it is done.
"""

import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import holiday_calendar, knowledge, library, references
from app.db import get_db
from app.deps import current_interviewer
from app.models import HolidaySource, PolicyChunk, ReferenceChunk

router = APIRouter(prefix="/api/library", tags=["library"], dependencies=[Depends(current_interviewer)])
log = logging.getLogger("talentsight.library")

# Which kinds are being read again right now. A dict guarded by a lock: the reading runs in a worker thread.
reading: dict[str, bool] = {kind: False for kind in library.KINDS}
lock = threading.Lock()


class DocumentOut(BaseModel):
    name: str
    size: int
    added_at: datetime
    status: str  # read | not_read | failed
    detail: str  # "12 sections", "17 public holidays", or what went wrong


class KindOut(BaseModel):
    kind: str
    label: str
    used_for: str
    accepts: list[str]
    reading: bool  # being read again after a change
    documents: list[DocumentOut]


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def describe(db: Session, kind: str, name: str) -> tuple[str, str]:
    """Whether the AI has read this document, and what it found in it."""
    if kind == "policies":
        count = db.scalar(select(func.count()).select_from(PolicyChunk).where(PolicyChunk.source == name))
        return ("read", plural(count, "section")) if count else ("not_read", "No numbered sections found yet")
    if kind == "skills":
        count = db.scalar(select(func.count()).select_from(ReferenceChunk).where(ReferenceChunk.source == name))
        return ("read", plural(count, "section")) if count else ("not_read", "No sections found yet")
    record = db.scalar(select(HolidaySource).where(HolidaySource.file_name == name))
    if record is None:
        return "not_read", "Not read yet"
    if record.error:
        return "failed", record.error
    return "read", plural(record.holidays_found, "public holiday") + (f" ({record.year})" if record.year else "")


def kind_out(db: Session, kind: str) -> KindOut:
    info = library.KINDS[kind]
    documents = []
    for path in library.files_of(kind):
        state, detail = describe(db, kind, path.name)
        stat = path.stat()
        documents.append(
            DocumentOut(
                name=path.name,
                size=stat.st_size,
                added_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                status=state,
                detail=detail,
            )
        )
    return KindOut(
        kind=kind,
        label=info["label"],
        used_for=info["used_for"],
        accepts=[t.lstrip(".").upper() for t in info["types"]],
        reading=reading[kind],
        documents=documents,
    )


def read_again(kind: str) -> None:
    """Reads the documents of one kind again. Runs after the request was answered. Never raises."""
    with lock:
        reading[kind] = True
    try:
        if kind == "policies":
            knowledge.load_policies()
        elif kind == "skills":
            references.load_references()
        else:
            holiday_calendar.load_holiday_calendars()
    except Exception as error:  # a broken document must not take the API down
        log.error(f"library {kind} could not be read", exc_info=error, extra={"event": "library_read_failed"})
    finally:
        with lock:
            reading[kind] = False


def check_kind(kind: str) -> None:
    if kind not in library.KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no such kind of document.")


@router.get("", response_model=list[KindOut])
def list_documents(db: Session = Depends(get_db)):
    return [kind_out(db, kind) for kind in library.KINDS]


@router.post("/{kind}", response_model=KindOut, status_code=status.HTTP_201_CREATED)
async def add_document(kind: str, background: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Adds a document, or replaces the one with the same name, then reads that kind again in the background."""
    check_kind(kind)
    data = await file.read(library.MAX_FILE_BYTES + 1)
    try:
        library.save(kind, file.filename or "", data)
    except library.LibraryError as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem))
    with lock:
        reading[kind] = True  # shown at once; read_again sets it back when it is done
    background.add_task(read_again, kind)
    return kind_out(db, kind)


@router.delete("/{kind}/{name}", response_model=KindOut)
def remove_document(kind: str, name: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    check_kind(kind)
    try:
        library.remove(kind, name)
    except library.LibraryError as problem:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(problem))
    with lock:
        reading[kind] = True
    background.add_task(read_again, kind)
    return kind_out(db, kind)


@router.post("/{kind}/read-again", response_model=KindOut)
def read_kind_again(kind: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Reads every document of this kind again, for example after a failed read."""
    check_kind(kind)
    with lock:
        reading[kind] = True
    background.add_task(read_again, kind)
    return kind_out(db, kind)


@router.get("/{kind}/{name}")
def download_document(kind: str, name: str):
    check_kind(kind)
    try:
        path = library.find(kind, name)
    except library.LibraryError as problem:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(problem))
    return FileResponse(path, filename=path.name)
