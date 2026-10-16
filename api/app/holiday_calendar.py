"""Public holidays: the days the interview planner never books.

Where they come from: a file in api/knowledge/holidays/ (normally a PDF list such as
bangladesh-public-holidays-2026.pdf). When the API starts, load_holiday_calendars() reads every file
there that it has not read before (in the background, so the API is not held up), saves the public
holidays and writes the list to the log. Weekends are not in these files: Saturday and Sunday are fixed
in settings (WORK_DAYS).

How a PDF becomes a holiday list (RAG):
1. Plain code takes the text out of the PDF.
2. The text is cut into small pieces ("chunks"), each turned into an embedding (384 numbers that capture
   its meaning) and stored in pgvector: the same set-up as the hiring policies.
3. RETRIEVAL (hybrid): pieces that say "holiday", plus the piece after each one, then the pieces closest
   in meaning to "public holiday dates" by vector search.
4. GENERATION: only those pieces go to the AI, which lists each holiday as date + name, public or optional.
5. CHECK by code: every date written in the PDF is found by plain code too. A date the AI left out
   (a long list is easy to cut short) is added, so the saved list is never shorter than the document.

A PDF whose text cannot be read (a scanned page, or the government's Bangla wall calendar, which uses
an old non-Unicode font) is refused with a clear message: reading it with OCR mixed the calendar grid
into the holiday list. A .txt file with one holiday per line ("2026-10-21  Durga Puja") also works and
is read by plain code only.

A file read again (because it changed) replaces the holidays of its years. Days added by hand stay.
Why the planner does not ask the AI directly: it checks hundreds of possible times, and every answer
must be exact and the same each time. So it only reads the saved list.
"""

import hashlib
import logging
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete, extract, select
from sqlalchemy.orm import Session

from app import knowledge
from app.cv_text import CVReadError, pdf_text, tidy
from app.db import SessionLocal
from app.llm import LLMUnavailable, ask_llm
from app.models import Holiday, HolidayChunk, HolidaySource

log = logging.getLogger("talentsight")

HOLIDAY_FOLDER = Path(__file__).resolve().parent.parent / "knowledge" / "holidays"
FILE_TYPES = (".txt", ".pdf")
# Part of each file's fingerprint: when the way files are read improves, raising this number makes
# every file be read again at the next start, with no command to remember.
READER_VERSION = "3"

MAX_FILE_BYTES = 10 * 1024 * 1024
CHUNK_CHARS = 600  # one piece: a few lines of the calendar
CHUNKS_FOR_LIST = 15  # how many pieces the AI reads when it lists the holidays
LIST_QUERY = "public holiday dates and names; general holidays; executive order holidays; optional holidays"
HOLIDAY_WORDS = ("holiday",)
MONTHS = ("january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december")
MONTH_NUMBERS = {name: number for number, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
)}

# A date: "2026-10-21", "21 October 2026" or "October 21, 2026". The text list needs it at the start of
# a line; the check of a PDF finds it anywhere.
ISO_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})\b")
DAY_MONTH_YEAR = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b")
MONTH_DAY_YEAR = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b")
WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


class HolidayReadError(ValueError):
    """The file could not be turned into a list of holidays. The message says why."""


class FoundHoliday(BaseModel):
    date: str = Field(description="The day as YYYY-MM-DD")
    name: str = Field(description="The holiday's name, in English if the document gives it")
    kind: Literal["public", "optional"] = Field(
        description="public = offices are closed for everyone (general or executive-order holiday); "
        "optional = only some staff may take it"
    )


class FoundHolidays(BaseModel):
    holidays: list[FoundHoliday]


HOLIDAY_PROMPT = (
    "You read parts of an official public holiday calendar and list its holidays. Give one entry per DAY: "
    "a holiday that lasts several days (for example 9-11 April, or '19, 20 and 22 March') becomes one entry "
    "for each day. Use the year the document is for. Copy only dates the text gives; never guess or add a date. "
    "Mark general and executive-order holidays as public, and holidays only for some groups or some districts "
    "(banks only, one region only) as optional. Ignore weekends that are only listed because a holiday falls on them."
)


class Proposed(BaseModel):
    day: date
    name: str
    kind: str


class ReadResult(BaseModel):
    source: str
    year: int | None
    chunks_stored: int
    chunks_used: int
    holidays: list[Proposed]


# ---------- 1. A text file: one holiday per line, read by plain code ----------


def to_date(match: re.Match, order: str) -> date | None:
    """The date in a regex match, or None when it is not a real date ("2026-02-30", "4 Foo 2026")."""
    parts = dict(zip(order, match.groups()))
    month = parts["m"]
    if not month.isdigit():
        month = MONTH_NUMBERS.get(month[:3].lower())
        if month is None:
            return None
    try:
        return date(int(parts["y"]), int(month), int(parts["d"]))
    except ValueError:
        return None


def tidy_name(text: str) -> str:
    """A holiday name without separators and without a weekday ("Wednesday")."""
    words = [w for w in text.strip(" \t-:|,").split() if w.lower().strip(",") not in WEEKDAYS]
    return " ".join(words).strip(" -:|,")[:200]


def line_date(line: str) -> tuple[date, str] | None:
    """The date at the start of a line, and the rest of the line (the name). None when there is none."""
    for pattern, order in ((ISO_DATE, "ymd"), (DAY_MONTH_YEAR, "dmy"), (MONTH_DAY_YEAR, "mdy")):
        match = pattern.match(line)
        if not match:
            continue
        day = to_date(match, order)
        if day is None:
            return None
        return day, tidy_name(line[match.end() :]) or "Public holiday"
    return None


def dates_in_text(text: str) -> dict[date, str]:
    """Every full date written anywhere in a document, with a name guessed from around it: the rest of
    its line, else the start of its line, else the next line that is not a weekday (a table cell)."""
    found: list[tuple[int, int, date]] = []
    for pattern, order in ((ISO_DATE, "ymd"), (DAY_MONTH_YEAR, "dmy"), (MONTH_DAY_YEAR, "mdy")):
        for match in pattern.finditer(text):
            day = to_date(match, order)
            if day is not None:
                found.append((match.start(), match.end(), day))
    found.sort()
    result: dict[date, str] = {}
    for index, (start, end, day) in enumerate(found):
        line_start = text.rfind("\n", 0, start) + 1
        line_end = text.find("\n", end)
        line_end = len(text) if line_end == -1 else line_end
        name = tidy_name(text[end:line_end]) or tidy_name(text[line_start:start])
        if not name:
            until = found[index + 1][0] if index + 1 < len(found) else len(text)
            following = (tidy_name(line) for line in text[line_end:until].splitlines())
            name = next((line for line in following if line), "")
        result.setdefault(day, name or "Public holiday")
    return result


def parse_text_list(text: str) -> tuple[list[tuple[date, str]], list[str]]:
    """Every holiday in a text file, and the lines that could not be read (for the log).
    Empty lines and lines starting with # are notes, not holidays."""
    found: dict[date, str] = {}
    unread: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed = line_date(line)
        if parsed is None:
            unread.append(line[:80])
            continue
        day, name = parsed
        found[day] = f"{found[day]} / {name}"[:200] if day in found and name not in found[day] else found.get(day, name)
    return sorted(found.items()), unread


# ---------- 2. A PDF with normal text: chunks, retrieval, generation (RAG) ----------


def readable(text: str) -> bool:
    """True when the text names a month: every holiday list does. Text from an old Bangla font, or a
    scanned page with no text at all, has none."""
    low = text.lower()
    return any(month in low for month in MONTHS)


def calendar_year(text: str) -> int | None:
    """The year the calendar is for: the first year in the text, which is the title."""
    found = re.search(r"\b(20[2-9]\d)\b", text)
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
    """Replaces the stored pieces of this file with the new ones (reading the same file again
    must not leave old copies behind)."""
    db.execute(delete(HolidayChunk).where(HolidayChunk.source == source))
    for chunk, vector in zip(chunks, knowledge.embed_texts(chunks)):
        db.add(HolidayChunk(source=source, text=chunk, embedding=vector))
    db.commit()


def search(db: Session, question: str, limit: int, source: str | None = None) -> list[HolidayChunk]:
    """The stored pieces closest in meaning to the question (cosine distance in pgvector)."""
    query = select(HolidayChunk).order_by(HolidayChunk.embedding.cosine_distance(knowledge.embed_question(question))).limit(limit)
    if source is not None:
        query = query.where(HolidayChunk.source == source)
    return list(db.scalars(query))


def holiday_pieces(db: Session, source: str) -> list[HolidayChunk]:
    """Hybrid retrieval for listing the holidays, at most CHUNKS_FOR_LIST pieces, in document order.
    First every piece that says "holiday" plus the piece after it (a list can run on into the next
    piece), then the closest pieces by vector search to fill up."""
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


def read_pdf(db: Session, data: bytes, filename: str) -> ReadResult:
    """Stores the PDF's pieces, finds the ones about holiday dates, and has the AI list the holidays.
    Saves nothing in the holiday list itself (load_file does that). Raises HolidayReadError."""
    if not data.startswith(b"%PDF"):
        raise HolidayReadError("This is not a PDF file.")
    source = re.sub(r"[^\w.\- ]", "", Path(filename or "holidays.pdf").name)[:200] or "holidays.pdf"
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "holidays.pdf"
        path.write_bytes(data)
        try:
            text = tidy(pdf_text(path))
        except CVReadError as error:  # for example a password-protected PDF
            raise HolidayReadError(str(error)) from error
        except Exception as error:
            raise HolidayReadError("The file is damaged or cannot be opened.") from error
    if not readable(text):
        raise HolidayReadError(
            "The text in this PDF cannot be read (a scanned page, or an old Bangla font). "
            "Make a PDF or .txt list with normal text instead, one holiday per line, like: 21 October 2026  Durga Puja"
        )

    chunks = split_chunks(text)
    store_chunks(db, source, chunks)
    found = holiday_pieces(db, source)
    year = calendar_year(text)
    heading = f"This calendar is for the year {year}.\n\n" if year else ""
    in_text = dates_in_text(text)
    try:
        answer = ask_llm(HOLIDAY_PROMPT, heading + "\n\n".join(chunk.text for chunk in found), FoundHolidays)
        holidays = clean(answer.holidays)
    except LLMUnavailable as error:
        if not in_text:
            raise HolidayReadError(str(error)) from error
        log.warning("holiday calendar: the AI was not available, the dates written in the PDF were used", extra={"event": "holiday_ai_down"})
        holidays = []
    # The check: a date written in the PDF that the AI did not mention at all is added. (A date the AI
    # did mention, as optional, stays out.)
    mentioned = {h.day for h in holidays}
    missed = sorted(day for day in set(in_text) - mentioned if "optional" not in in_text[day].lower())
    if missed and holidays:
        log.info(f"holiday calendar: the check added {len(missed)} dates the AI left out", extra={"event": "holiday_dates_added"})
    holidays += [Proposed(day=day, name=in_text[day], kind="public") for day in missed]
    holidays.sort(key=lambda h: h.day)
    return ReadResult(source=source, year=year, chunks_stored=len(chunks), chunks_used=len(found), holidays=holidays)


def clean(found: list[FoundHoliday]) -> list[Proposed]:
    """Drops entries that are not real dates, joins two names given for the same day, sorts by date."""
    by_day: dict[date, Proposed] = {}
    for item in found:
        try:
            day = date.fromisoformat(item.date.strip())
        except ValueError:
            continue  # "Depends on the moon" and the like
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


# ---------- 3. The saved list the planner uses ----------


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


def replace_years(db: Session, items: list[tuple[date, str]], source: str) -> None:
    """Saves a file's holidays. The file is the truth for its years: days of those years that came
    from a file before (and are not in this one) are removed. Days added by hand stay."""
    for year in {day.year for day, _ in items}:
        db.execute(delete(Holiday).where(Holiday.source != "manual", extract("year", Holiday.day) == year))
    save_many(db, items, source)


def calendar_status(db: Session, today: date) -> tuple[int, str]:
    """For the invite pop-up: how many public holidays from today are on the list, and what is wrong
    with the holiday files, if anything ("" = fine). So an empty or failed list is never silent."""
    ahead = len(db.scalars(select(Holiday.id).where(Holiday.day >= today)).all())
    sources = db.scalars(select(HolidaySource)).all()
    if not sources:
        return ahead, "No holiday list has been read yet. Put the holiday file in api/knowledge/holidays and restart the API."
    problems = [f"{s.file_name}: {s.error}" for s in sources if s.error]
    if not problems and ahead == 0:
        problems = ["The holiday list has no days from today on. Add next year's holidays to api/knowledge/holidays."]
    return ahead, " ".join(problems)


def days_off(db: Session, first: date, last: date) -> set[date]:
    """Every holiday between first and last (both included): the planner skips these days."""
    return set(db.scalars(select(Holiday.day).where(Holiday.day >= first, Holiday.day <= last)))


# ---------- 4. Reading the folder at start-up ----------


def read_file(db: Session, path: Path) -> list[tuple[date, str]]:
    """The public holidays in one file. Raises HolidayReadError with a readable reason."""
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise HolidayReadError("The file is larger than 10 MB.")
    if path.suffix.lower() == ".txt":
        text = data.decode("utf-8-sig", errors="replace")
        days, unread = parse_text_list(text)
        if unread:
            log.warning(f"holiday list {path.name}: {len(unread)} lines without a date were skipped: {unread[:5]}", extra={"event": "holiday_lines_skipped"})
        if not days:
            raise HolidayReadError("No dates were found. Write one holiday per line, like: 2026-10-21  Durga Puja")
        store_chunks(db, path.name, split_chunks(text))  # kept for search, like any other knowledge
        return days
    result = read_pdf(db, data, path.name)
    return [(h.day, h.name) for h in result.holidays if h.kind == "public"]


def load_file(db: Session, path: Path, force: bool = False) -> str:
    """Reads one holiday file and saves its public holidays. Returns what happened, for the log.
    A file read before (same name and same contents) is skipped unless force is True."""
    fingerprint = hashlib.sha256(path.read_bytes() + READER_VERSION.encode()).hexdigest()
    record = db.scalar(select(HolidaySource).where(HolidaySource.file_name == path.name))
    if record is not None and record.sha256 == fingerprint and not record.error and not force:
        return f"{path.name}: already read"
    record = record or HolidaySource(file_name=path.name, sha256=fingerprint)
    record.sha256 = fingerprint
    try:
        days = read_file(db, path)
    except HolidayReadError as problem:
        record.error = str(problem)[:500]
        db.add(record)
        db.commit()
        log.warning(f"holiday calendar {path.name} could not be read: {problem}", extra={"event": "holiday_calendar_failed"})
        return f"{path.name}: {problem}"
    if not days:
        record.error = "No public holidays were found in this file."
        db.add(record)
        db.commit()
        return f"{path.name}: no public holidays found"

    replace_years(db, days, source="file" if path.suffix.lower() == ".txt" else "pdf")
    record.year = min(day.year for day, _ in days)
    record.holidays_found, record.error = len(days), ""
    db.add(record)
    db.commit()
    listing = "; ".join(f"{day:%a %d %b %Y} {name}" for day, name in days)
    log.info(f"holiday calendar {path.name}: {len(days)} public holidays saved: {listing}", extra={"event": "holiday_calendar_read"})
    return f"{path.name}: {len(days)} public holidays saved"


def load_holiday_calendars(force: bool = False) -> list[str]:
    """Reads every holiday file in the knowledge/holidays folder that has not been read yet.
    Called once at start-up, in the background. Never raises: a problem is logged and tried again
    at the next start. A file that was taken out of the folder is forgotten (its days stay until a
    newer file for the same year replaces them)."""
    if not HOLIDAY_FOLDER.is_dir():
        return []
    paths = sorted(p for p in HOLIDAY_FOLDER.iterdir() if p.suffix.lower() in FILE_TYPES)
    with SessionLocal() as db:
        names = {p.name for p in paths}
        for record in db.scalars(select(HolidaySource)).all():
            if record.file_name not in names:
                db.delete(record)
        db.commit()
    results = []
    for path in paths:
        try:
            with SessionLocal() as db:
                results.append(load_file(db, path, force))
        except Exception as error:  # a broken file must never stop the API
            log.warning(f"holiday calendar {path.name} failed", exc_info=error, extra={"event": "holiday_calendar_failed"})
            results.append(f"{path.name}: failed ({type(error).__name__})")
    return results
