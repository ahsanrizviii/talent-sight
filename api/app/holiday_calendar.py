"""Public holidays, with RAG over the government's holiday calendar PDF.

How a PDF becomes a holiday list:
1. Plain code takes the text out of the file (the same reader as for CVs). The government
   calendar is printed in Bangla with an old font, so its text layer is unreadable: then the page
   is read with Bangla + English OCR instead.
2. The text is cut into small pieces ("chunks"), each turned into an embedding (a list of 384
   numbers that captures its meaning) and stored in pgvector: the same RAG set-up as the hiring
   policies.
3. RETRIEVAL (hybrid): pieces that contain the word "holiday" (or "ছুটি" in Bangla), plus the
   piece after each one, then the pieces closest in meaning to "public holiday dates" by vector
   search. The keyword part matters because the embedding model only knows English.
4. GENERATION: only those pieces go to the AI, which lists each holiday as date + name.
5. A person checks the list and presses Save. Nothing is saved before that.

The stored pieces also answer questions in the "Ask about holidays" box (retrieve, then answer).

Why the planner does not ask the AI directly: it checks hundreds of possible times, and every
answer must be exact and the same each time. So it only reads the checked, saved list.
"""

import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Literal

import pytesseract
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import knowledge
from app.cv_text import CVReadError, pdf_ocr, pdf_text, tidy
from app.llm import LLMUnavailable, ask_llm
from app.models import Holiday, HolidayChunk

MAX_PDF_BYTES = 10 * 1024 * 1024
CHUNK_CHARS = 600  # one piece: a few lines of the calendar
CHUNKS_FOR_LIST = 15  # how many pieces the AI reads when it lists the holidays
CHUNKS_FOR_QUESTION = 5  # how many pieces it reads to answer a question
LIST_QUERY = "public holiday dates and names; general holidays; executive order holidays; optional holidays"
HOLIDAY_WORDS = ("holiday", "ছুটি")  # "ছুটি" is Bangla for holiday
MONTHS = (
    "january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december",
    "জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "জুন", "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর",
)  # "May" / "মে" are left out: they are too short and match ordinary words
BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


class HolidayReadError(ValueError):
    """The PDF could not be turned into a list of holidays. The message says why."""


class FoundHoliday(BaseModel):
    date: str = Field(description="The day as YYYY-MM-DD")
    name: str = Field(description="The holiday's name, in English if the document gives it")
    kind: Literal["public", "optional"] = Field(
        description="public = offices are closed for everyone (general or executive-order holiday); "
        "optional = only some staff may take it"
    )


class FoundHolidays(BaseModel):
    holidays: list[FoundHoliday]


class HolidayAnswer(BaseModel):
    answer: str = Field(description="A short answer in plain English, or a clear 'I could not find that'")


HOLIDAY_PROMPT = (
    "You read parts of an official public holiday calendar and list its holidays. Give one entry per DAY: "
    "a holiday that lasts several days (for example 9-11 April, or '19, 20 and 22 March') becomes one entry "
    "for each day. Use the year the document is for. Copy only dates the text gives; never guess or add a date. "
    "Mark general and executive-order holidays as public, and holidays only for some groups or some districts "
    "as optional. Ignore weekends that are only listed because a holiday falls on them. "
    "The calendar may be in Bangla, read by OCR, so expect a few wrong letters. In Bangla: "
    "'সাধারণ ছুটি' (general holiday) and 'নির্বাহী আদেশে সরকারি ছুটি' (executive-order holiday) are public; "
    "'ঐচ্ছিক ছুটি' (optional holiday, sometimes read as 'এচ্ছিক') is optional. Bangla digits ০১২৩৪৫৬৭৮৯ are 0-9. "
    "Each holiday is written as an English-calendar date, then a Bangla-calendar date in brackets, then the name, "
    "for example '২১ ফেব্রুয়ারি (০৮ ফাল্গুন)-শহিদ দিবস' = 21 February, Shaheed Day. Use the first date only; "
    "ignore the date in brackets. Give the names in English. Ignore rows of calendar numbers."
)

ASK_PROMPT = (
    "You answer questions about public holidays for a hiring team. Use ONLY the saved holiday list and "
    "the calendar excerpts you are given. If the answer is not there, say you could not find it. "
    "Give dates with the weekday, for example 'Wednesday, 16 December 2026'. Keep the answer short."
)


class Proposed(BaseModel):
    day: date
    name: str
    kind: str


class ReadResult(BaseModel):
    source: str
    chunks_stored: int
    chunks_used: int
    holidays: list[Proposed]


# ---------- 1-2. Text and chunks ----------


def readable(text: str) -> bool:
    """True when the text names a month, in English or Bangla: every holiday list does. Text from an
    old Bangla font comes out as letters like 'Rvbyqvwi' (for জানুয়ারি) and has none."""
    low = text.lower()
    return any(month in low for month in MONTHS)


def ocr_languages() -> str:
    """Bangla and English when the Bangla pack is installed, else English only."""
    try:
        have = set(pytesseract.get_languages(config=""))
    except Exception:
        have = {"eng"}
    return "+".join(lang for lang in ("ben", "eng") if lang in have) or "eng"


def calendar_text(path: Path) -> str:
    """The calendar's text: the PDF's own text when it is readable, else Bangla + English OCR."""
    try:
        text = tidy(pdf_text(path))
    except CVReadError as error:  # for example a password-protected PDF
        raise HolidayReadError(str(error)) from error
    except Exception as error:
        raise HolidayReadError("The file is damaged or cannot be opened.") from error
    if readable(text):
        return text
    try:
        text = tidy(pdf_ocr(path, lang=ocr_languages()))
    except Exception as error:
        raise HolidayReadError("The PDF could not be read. You can add the holidays by hand below.") from error
    if not readable(text):
        raise HolidayReadError("No month names could be read in this PDF, so it does not look like a holiday calendar. You can add the holidays by hand below.")
    return text


def calendar_year(text: str) -> int | None:
    """The year the calendar is for: the first year in the text, which is the title (Bangla digits
    count too). Not the most common one: the printer's line at the bottom says "2025" twice."""
    found = re.search(r"\b(20[2-9]\d)\b", text.translate(BANGLA_DIGITS))
    return int(found.group(1)) if found else None


def split_chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Cuts the text into pieces of whole lines, about `size` characters each. A holiday list is one
    line per holiday, so a line is never cut in half and a date always stays next to its name."""
    chunks, current = [], ""
    for line in (line.strip() for line in text.splitlines()):
        if not line:
            continue
        if current and len(current) + len(line) + 1 > size:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def store_chunks(db: Session, source: str, chunks: list[str]) -> None:
    """Replaces the stored pieces of this file with the new ones (uploading the same file again
    must not leave old copies behind)."""
    db.execute(delete(HolidayChunk).where(HolidayChunk.source == source))
    for chunk, vector in zip(chunks, knowledge.embed_texts(chunks)):
        db.add(HolidayChunk(source=source, text=chunk, embedding=vector))
    db.commit()


# ---------- 3. Retrieval ----------


def search(db: Session, question: str, limit: int, source: str | None = None) -> list[HolidayChunk]:
    """The stored pieces closest in meaning to the question (cosine distance in pgvector)."""
    query = select(HolidayChunk).order_by(HolidayChunk.embedding.cosine_distance(knowledge.embed_question(question))).limit(limit)
    if source is not None:
        query = query.where(HolidayChunk.source == source)
    return list(db.scalars(query))


def holiday_pieces(db: Session, source: str) -> list[HolidayChunk]:
    """Hybrid retrieval for listing the holidays, at most CHUNKS_FOR_LIST pieces, in document order.
    First every piece that says "holiday" / "ছুটি" plus the piece after it (a list can run on into the
    next piece), then the closest pieces by vector search to fill up."""
    stored = list(db.scalars(select(HolidayChunk).where(HolidayChunk.source == source).order_by(HolidayChunk.id)))
    picked: dict[int, HolidayChunk] = {}
    for index, chunk in enumerate(stored):
        if any(word in chunk.text.lower() for word in HOLIDAY_WORDS):
            for piece in stored[index : index + 2]:
                picked.setdefault(piece.id, piece)
    for chunk in search(db, LIST_QUERY, CHUNKS_FOR_LIST, source):
        picked.setdefault(chunk.id, chunk)
    chosen = list(picked.values())[:CHUNKS_FOR_LIST]  # keyword pieces come first, so they are kept
    return sorted(chosen, key=lambda chunk: chunk.id)  # back in the document's own order, easier for the AI


# ---------- 4. Generation, then 5. a person checks ----------


def read_pdf(db: Session, data: bytes, filename: str) -> ReadResult:
    """Stores the PDF's pieces, finds the ones about holiday dates, and has the AI list the holidays.
    Only PROPOSES: nothing goes into the holiday list here. Raises HolidayReadError."""
    if not data.startswith(b"%PDF"):
        raise HolidayReadError("Please upload the holiday calendar as a PDF file.")
    if len(data) > MAX_PDF_BYTES:
        raise HolidayReadError("The PDF is larger than 10 MB.")
    source = re.sub(r"[^\w.\- ]", "", Path(filename or "holidays.pdf").name)[:200] or "holidays.pdf"
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "holidays.pdf"
        path.write_bytes(data)
        text = calendar_text(path)

    chunks = split_chunks(text)
    store_chunks(db, source, chunks)
    found = holiday_pieces(db, source)
    year = calendar_year(text)
    heading = f"This calendar is for the year {year}.\n\n" if year else ""
    try:
        answer = ask_llm(HOLIDAY_PROMPT, heading + "\n\n".join(chunk.text for chunk in found), FoundHolidays)
    except LLMUnavailable as error:
        raise HolidayReadError(str(error)) from error
    return ReadResult(source=source, chunks_stored=len(chunks), chunks_used=len(found), holidays=clean(answer.holidays))


def clean(found: list[FoundHoliday]) -> list[Proposed]:
    """Drops entries that are not real dates, joins two names given for the same day, sorts by date."""
    by_day: dict[date, Proposed] = {}
    for item in found:
        try:
            day = date.fromisoformat(item.date.strip())
        except ValueError:
            continue  # "Depends on the moon" and the like: a person can add it by hand later
        name = " ".join(item.name.split())[:200] or "Holiday"
        if day in by_day:
            old = by_day[day]
            if name not in old.name:
                old.name = f"{old.name} / {name}"[:200]
            if item.kind == "public":
                old.kind = "public"
        else:
            by_day[day] = Proposed(day=day, name=name, kind=item.kind)
    return [by_day[day] for day in sorted(by_day)]


def ask(db: Session, question: str) -> tuple[str, list[HolidayChunk]]:
    """Answers a question about holidays: retrieves the closest pieces of the calendar, then asks
    the AI with those pieces and the saved list. Returns the answer and the pieces it read."""
    pieces = search(db, question, CHUNKS_FOR_QUESTION)
    saved = db.scalars(select(Holiday).order_by(Holiday.day)).all()
    saved_text = "\n".join(f"{h.day:%A, %d %B %Y}: {h.name}" for h in saved) or "(none saved yet)"
    excerpts = "\n\n".join(f"[{p.source}]\n{p.text}" for p in pieces) or "(no calendar uploaded yet)"
    prompt = f"Saved holiday list:\n{saved_text}\n\nCalendar excerpts:\n{excerpts}\n\nQuestion: {question}"
    try:
        answer = ask_llm(ASK_PROMPT, prompt, HolidayAnswer)
    except LLMUnavailable as error:
        raise HolidayReadError(str(error)) from error
    return answer.answer, pieces


def documents(db: Session) -> list[tuple[str, int]]:
    """Which calendar PDFs are stored, and in how many pieces."""
    rows = db.execute(select(HolidayChunk.source, HolidayChunk.id)).all()
    counts: dict[str, int] = {}
    for source, _ in rows:
        counts[source] = counts.get(source, 0) + 1
    return sorted(counts.items())


def remove_document(db: Session, source: str) -> None:
    db.execute(delete(HolidayChunk).where(HolidayChunk.source == source))
    db.commit()


# ---------- The checked list the planner uses ----------


def save_many(db: Session, items: list[tuple[date, str]], source: str) -> int:
    """Adds the days, or renames ones that are already there. Returns how many were new."""
    added = 0
    for day, name in items:
        name = " ".join(name.split())[:200] or "Holiday"
        row = db.scalar(select(Holiday).where(Holiday.day == day))
        if row is None:
            db.add(Holiday(day=day, name=name, source=source))
            added += 1
        else:
            row.name = name
    db.commit()
    return added


def days_off(db: Session, first: date, last: date) -> set[date]:
    """Every holiday between first and last (both included): the planner skips these days."""
    return set(db.scalars(select(Holiday.day).where(Holiday.day >= first, Holiday.day <= last)))
