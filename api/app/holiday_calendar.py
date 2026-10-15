"""Public holidays, with RAG over the government's holiday calendar PDF.

Where the calendar comes from: put the PDF in api/knowledge/holidays/ and rebuild. When the API starts,
load_holiday_calendars() reads every PDF there that it has not read before (in the background, so the
API is not held up), and saves the public holidays it finds. The list is also written to the log.

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
   The Bangla government calendar has a fixed layout: one paragraph per kind of holiday, each
   starting with its heading ("সাধারণ ছুটি" = general, "নির্বাহী আদেশে সরকারি ছুটি" = executive order,
   "ঐচ্ছিক ছুটি" = optional). For that calendar, plain code finds the two public paragraphs and every
   date written in them; the AI gets one paragraph at a time and gives each holiday its English name.
   The dates that are saved are the ones the code found in the text, so a date the AI leaves out
   (a long list is easy to cut short) or makes up can never change the list.
5. Only the public holidays are saved (optional ones, and ones only for some districts, are not).
   A newer calendar for the same year replaces the holidays read from the older one.

Weekends are not in the PDF list: Saturday and Sunday are fixed in settings (WORK_DAYS).
Why the planner does not ask the AI directly: it checks hundreds of possible times, and every
answer must be exact and the same each time. So it only reads the saved list.
"""

import hashlib
import logging
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Literal

import pytesseract
from pydantic import BaseModel, Field
from sqlalchemy import delete, extract, select
from sqlalchemy.orm import Session

from app import knowledge
from app.cv_text import CVReadError, pdf_ocr, pdf_text, tidy
from app.llm import LLMUnavailable, ask_llm
from app.db import SessionLocal
from app.models import Holiday, HolidayChunk, HolidaySource

log = logging.getLogger("talentsight")

HOLIDAY_FOLDER = Path(__file__).resolve().parent.parent / "knowledge" / "holidays"
# Part of each file's fingerprint: when the way calendars are read improves, raising this number makes
# every calendar be read again at the next start, with no command to remember.
READER_VERSION = "2"

MAX_PDF_BYTES = 10 * 1024 * 1024
CHUNK_CHARS = 600  # one piece: a few lines of the calendar
CHUNKS_FOR_LIST = 15  # how many pieces the AI reads when it lists the holidays
LIST_QUERY = "public holiday dates and names; general holidays; executive order holidays; optional holidays"
HOLIDAY_WORDS = ("holiday", "ছুটি")  # "ছুটি" is Bangla for holiday
MONTHS = (
    "january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december",
    "জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "জুন", "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর",
)  # "May" / "মে" are left out: they are too short and match ordinary words
BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
BANGLA_MONTHS = {
    "জানুয়ারি": 1, "ফেব্রুয়ারি": 2, "মার্চ": 3, "এপ্রিল": 4, "মে": 5, "জুন": 6,
    "জুলাই": 7, "আগস্ট": 8, "সেপ্টেম্বর": 9, "অক্টোবর": 10, "নভেম্বর": 11, "ডিসেম্বর": 12,
}
# "২১ মার্চ": a day number, then an English-calendar month written in Bangla. The Bangla-calendar date
# in brackets ("০৭ চৈত্র") uses other month names, so it never matches.
BANGLA_DATE = re.compile(
    r"(?<![০-৯0-9])([০-৯0-9]{1,2})\s+(" + "|".join(sorted(BANGLA_MONTHS, key=len, reverse=True)) + r")(?![\u0980-\u09FF])"
)
PUBLIC_HEADINGS = ("সাধারণ", "নির্বাহী")  # general holiday, executive-order holiday
ONLY_SOME_PLACES = "শুধু"  # "only" (for example "only for the three hill districts")


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

class Proposed(BaseModel):
    day: date
    name: str
    kind: str


class ReadResult(BaseModel):
    source: str
    year: int | None
    note: str = ""  # set when the list is right but incomplete in some way (read again next start)
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


# ---------- 4. Generation ----------


def read_pdf(db: Session, data: bytes, filename: str) -> ReadResult:
    """Stores the PDF's pieces, finds the ones about holiday dates, and has the AI list the holidays.
    Saves nothing in the holiday list itself (load_file does that). Raises HolidayReadError."""
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

    public = public_sections(text)
    if public and year is not None:
        holidays, note = read_bangla_calendar(public, year, heading)
        return ReadResult(source=source, year=year, note=note, chunks_stored=len(chunks), chunks_used=len(found), holidays=holidays)

    try:
        answer = ask_llm(HOLIDAY_PROMPT, heading + "\n\n".join(chunk.text for chunk in found), FoundHolidays)
    except LLMUnavailable as error:
        raise HolidayReadError(str(error)) from error
    return ReadResult(source=source, year=year, chunks_stored=len(chunks), chunks_used=len(found), holidays=clean(answer.holidays))


# ---------- The Bangla government calendar: headings and dates found by code ----------


def public_sections(text: str) -> list[str]:
    """The paragraphs of public holidays (general and executive order) in the Bangla calendar.
    A paragraph starts at a line whose beginning says "ছুটি" (holiday) and runs to the next such line.
    Returns [] for a calendar without these headings (then the normal AI reading is used)."""
    sections: list[tuple[bool, list[str]]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        start = line[:40]
        if line.startswith("টীকা"):  # "Note:" at the end of the list
            current = None
        elif "ছুটি" in start:
            current = [line]
            sections.append((any(word in start for word in PUBLIC_HEADINGS), current))
        elif current is not None:
            current.append(line)
    return ["\n".join(lines) for is_public, lines in sections if is_public]


def dates_in(section: str, year: int) -> list[tuple[date, str]]:
    """Every holiday date written in one paragraph, with the Bangla name that follows it.
    Leaves out holidays only for some places ("শুধু ..." = only for ...)."""
    matches = list(BANGLA_DATE.finditer(section))
    found: list[tuple[date, str]] = []
    for index, match in enumerate(matches):
        until = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        after = section[match.end() : until]
        if ONLY_SOME_PLACES in after[:160]:
            continue
        try:
            day = date(year, BANGLA_MONTHS[match.group(2)], int(match.group(1).translate(BANGLA_DIGITS)))
        except ValueError:
            continue  # an OCR slip such as "৩২ মার্চ"
        name = after.split(")", 1)[1] if ")" in after else ""
        name = re.split(r"[|।৷]", name)[0].strip(" -_*\n")
        name = re.sub(r"\s+[0-9]+$", "", name)  # OCR often reads the "।" at the end as "1"
        found.append((day, " ".join(name.split())[:80]))
    # "১৯ মার্চ, ২০ মার্চ এবং ২২ মার্চ (...)-ঈদ-উল-ফিতর": the name follows only the last date of the group.
    for index in range(len(found) - 2, -1, -1):
        if not found[index][1]:
            found[index] = (found[index][0], found[index + 1][1])
    return found


def read_bangla_calendar(sections: list[str], year: int, heading: str) -> tuple[list[Proposed], str]:
    """The public holidays of the Bangla calendar. The dates come from the text (dates_in); the AI,
    one paragraph at a time, gives the English names. Returns the list and a note ("" when all is well)."""
    by_day: dict[date, str] = {}
    for section in sections:
        for day, name in dates_in(section, year):
            by_day.setdefault(day, name)
    english: list[FoundHoliday] = []
    note = ""
    for section in sections:
        try:
            answer = ask_llm(HOLIDAY_PROMPT, heading + "Every holiday below is a public holiday.\n\n" + section, FoundHolidays)
            english.extend(answer.holidays)
        except LLMUnavailable:
            note = "The AI was not available, so some holiday names are in Bangla. The dates are complete."
    names = {item.day: item.name for item in clean(english)}
    extra = sorted(set(names) - set(by_day))
    if extra:
        log.info(f"holiday calendar: {len(extra)} dates from the AI are not in the text and were left out", extra={"event": "holiday_dates_dropped"})
    holidays = [Proposed(day=day, name=names.get(day) or by_day[day] or "Public holiday", kind="public") for day in sorted(by_day)]
    return holidays, note


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


# ---------- 5. The saved list the planner uses ----------


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


def calendar_status(db: Session, today: date) -> tuple[int, str]:
    """For the invite pop-up: how many public holidays from today are on the list, and what is wrong
    with the calendar, if anything ("" = fine). So an empty or failed calendar is never silent."""
    ahead = len(db.scalars(select(Holiday.id).where(Holiday.day >= today)).all())
    sources = db.scalars(select(HolidaySource)).all()
    if not sources:
        return ahead, "No holiday calendar has been read yet. Put the PDF in api/knowledge/holidays and restart the API."
    problems = [f"{s.file_name}: {s.error}" for s in sources if s.error]
    return ahead, " ".join(problems)


def days_off(db: Session, first: date, last: date) -> set[date]:
    """Every holiday between first and last (both included): the planner skips these days."""
    return set(db.scalars(select(Holiday.day).where(Holiday.day >= first, Holiday.day <= last)))


def load_file(db: Session, path: Path, force: bool = False) -> str:
    """Reads one calendar PDF and saves its public holidays. Returns what happened, for the log.
    A file read before (same name and same contents) is skipped unless force is True."""
    data = path.read_bytes()
    fingerprint = hashlib.sha256(data + READER_VERSION.encode()).hexdigest()
    record = db.scalar(select(HolidaySource).where(HolidaySource.file_name == path.name))
    if record is not None and record.sha256 == fingerprint and not record.error and not force:
        return f"{path.name}: already read"
    record = record or HolidaySource(file_name=path.name, sha256=fingerprint)
    record.sha256 = fingerprint
    try:
        result = read_pdf(db, data, path.name)
    except HolidayReadError as problem:
        record.error = str(problem)[:500]
        db.add(record)
        db.commit()
        log.warning(f"holiday calendar {path.name} could not be read: {problem}", extra={"event": "holiday_calendar_failed"})
        return f"{path.name}: {problem}"

    public = [h for h in result.holidays if h.kind == "public"]
    if not public:
        record.error = "No public holidays were found in this calendar."
        db.add(record)
        db.commit()
        log.warning(f"holiday calendar {path.name}: no public holidays found", extra={"event": "holiday_calendar_failed"})
        return f"{path.name}: no public holidays found"
    if result.year is not None:
        # A new calendar for this year replaces what an older one said: remove the old PDF days first.
        db.execute(delete(Holiday).where(Holiday.source == "pdf", extract("year", Holiday.day) == result.year))
    save_many(db, [(h.day, h.name) for h in public], source="pdf")
    record.year, record.holidays_found, record.error = result.year, len(public), result.note
    db.add(record)
    db.commit()
    listing = "; ".join(f"{h.day:%a %d %b %Y} {h.name}" for h in public) or "none"
    log.info(f"holiday calendar {path.name}: {len(public)} public holidays saved: {listing}", extra={"event": "holiday_calendar_read"})
    return f"{path.name}: {len(public)} public holidays saved"


def load_holiday_calendars(force: bool = False) -> list[str]:
    """Reads every PDF in the knowledge/holidays folder that has not been read yet.
    Called once at start-up, in the background. Never raises: a problem is logged and tried again
    at the next start."""
    if not HOLIDAY_FOLDER.is_dir():
        return []
    results = []
    for path in sorted(HOLIDAY_FOLDER.glob("*.pdf")):
        try:
            with SessionLocal() as db:
                results.append(load_file(db, path, force))
        except Exception as error:  # a broken file must never stop the API
            log.warning(f"holiday calendar {path.name} failed", exc_info=error, extra={"event": "holiday_calendar_failed"})
            results.append(f"{path.name}: failed ({type(error).__name__})")
    return results
