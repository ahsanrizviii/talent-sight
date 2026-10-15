"""Holidays on the Settings page: read the government PDF, check the list, save it, add or remove days."""

from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from app import holiday_calendar
from app.db import get_db
from app.deps import current_interviewer
from app.models import Holiday

router = APIRouter(prefix="/api/holidays", tags=["holidays"], dependencies=[Depends(current_interviewer)])


class HolidayOut(BaseModel):
    id: int
    day: date
    name: str
    source: str


class HolidayIn(BaseModel):
    day: date
    name: str = Field(default="", max_length=200)


class SaveIn(BaseModel):
    holidays: list[HolidayIn] = Field(max_length=400)
    source: str = "manual"  # manual | pdf


class SaveOut(BaseModel):
    added: int
    holidays: list[HolidayOut]


def listed(db: Session, year: int | None = None) -> list[HolidayOut]:
    query = select(Holiday).order_by(Holiday.day)
    if year:
        query = query.where(extract("year", Holiday.day) == year)
    return [HolidayOut(id=h.id, day=h.day, name=h.name, source=h.source) for h in db.scalars(query)]


@router.get("", response_model=list[HolidayOut])
def list_holidays(year: int | None = None, db: Session = Depends(get_db)):
    return listed(db, year)


@router.post("/read-pdf", response_model=holiday_calendar.ReadResult)
def read_holiday_pdf(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Stores the PDF's pieces for RAG and PROPOSES a holiday list. The list itself is not saved here."""
    try:
        return holiday_calendar.read_pdf(db, file.file.read(holiday_calendar.MAX_PDF_BYTES + 1), file.filename or "")
    except holiday_calendar.HolidayReadError as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem))


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=300)


class SourcePiece(BaseModel):
    source: str
    text: str


class AskOut(BaseModel):
    answer: str
    sources: list[SourcePiece]  # the pieces of the calendar the answer was built from


@router.post("/ask", response_model=AskOut)
def ask_about_holidays(body: AskIn, db: Session = Depends(get_db)):
    """'Is there a holiday during Eid?': retrieves the closest pieces of the calendar, then answers."""
    try:
        answer, pieces = holiday_calendar.ask(db, body.question.strip())
    except holiday_calendar.HolidayReadError as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem))
    return AskOut(answer=answer, sources=[SourcePiece(source=p.source, text=p.text) for p in pieces])


class DocumentOut(BaseModel):
    source: str
    chunks: int


@router.get("/documents", response_model=list[DocumentOut])
def stored_documents(db: Session = Depends(get_db)):
    """The calendar PDFs stored for RAG."""
    return [DocumentOut(source=source, chunks=count) for source, count in holiday_calendar.documents(db)]


@router.delete("/documents/{source}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(source: str, db: Session = Depends(get_db)):
    """Forgets a calendar PDF (its pieces). The saved holiday list stays as it is."""
    holiday_calendar.remove_document(db, source)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("", response_model=SaveOut)
def save_holidays(body: SaveIn, db: Session = Depends(get_db)):
    """Saves the days a person checked (from the PDF) or typed in."""
    source = "pdf" if body.source == "pdf" else "manual"
    added = holiday_calendar.save_many(db, [(h.day, h.name) for h in body.holidays], source)
    return SaveOut(added=added, holidays=listed(db))


@router.delete("/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holiday(holiday_id: int, db: Session = Depends(get_db)):
    row = db.get(Holiday, holiday_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holiday not found.")
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
