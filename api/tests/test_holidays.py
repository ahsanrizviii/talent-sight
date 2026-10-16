"""Tests for the holiday list, read from the knowledge/holidays folder when the API starts.
A text file is read by plain code; a PDF with normal text is read with RAG (the AI is faked; the
chunking and the vector search are real, with the test embedding from conftest). The folder is a
temporary one (conftest), so the real files are never read here."""

from datetime import date
from pathlib import Path

from sqlalchemy import select

from app import holiday_calendar
from app.db import SessionLocal
from app.holiday_calendar import FoundHoliday, FoundHolidays
from app.cv_text import pdf_text, tidy
from app.models import Holiday, HolidaySource, JobProfile
from scripts.make_sample_cvs import make_pdf

REAL_LIST = Path(__file__).resolve().parent.parent / "knowledge" / "holidays" / "bangladesh-public-holidays-2026.pdf"

TEXT_LIST = """# Public holidays 2026
2026-02-21  Shaheed Day
2026-10-20  Durga Puja (Nabami)
2026-10-21  Durga Puja (Bijoya Dashami)
16 December 2026  Victory Day
December 25, 2026 - Christmas Day
this line has no date
"""

ENGLISH_PDF = [
    "Government of the People's Republic of Bangladesh",
    "Public Holidays 2026",
    "Shaheed Day and International Mother Language Day - 21 February 2026",
    "Independence Day - 26 March 2026",
    "Victory Day - 16 December 2026",
    "Optional holiday: Shab-e-Miraj - 17 January 2026",
] + ["Offices remain closed on these days."] * 4

FOUND = [
    FoundHoliday(date="2026-12-16", name="Victory Day", kind="public"),
    FoundHoliday(date="2026-03-26", name="Independence Day", kind="public"),
    FoundHoliday(date="2026-01-17", name="Shab-e-Miraj", kind="optional"),  # optional: not saved
    FoundHoliday(date="moon-dependent", name="Shab-e-Barat", kind="public"),  # not a date: dropped
]


def fake_ai(monkeypatch, found: list[FoundHoliday] | None = None, seen: list | None = None, down: bool = False):
    def answer(system_prompt, user_prompt, answer_shape, **options):
        if down:
            raise holiday_calendar.LLMUnavailable("The AI service is not available right now. Please try again.")
        if seen is not None:
            seen.append(user_prompt)
        return FoundHolidays(holidays=FOUND if found is None else found)

    monkeypatch.setattr(holiday_calendar, "ask_llm", answer)


def put(name: str, content: str | bytes) -> None:
    path = holiday_calendar.HOLIDAY_FOLDER / name
    path.write_bytes(content.encode() if isinstance(content, str) else content)


def saved() -> dict[str, str]:
    with SessionLocal() as db:
        return {h.day.isoformat(): h.name for h in db.scalars(select(Holiday).order_by(Holiday.day))}


# ---------- A text file: one holiday per line ----------


def test_a_text_list_is_read_by_code_without_the_ai(client, monkeypatch):
    asked: list = []
    fake_ai(monkeypatch, seen=asked)
    put("holidays-2026.txt", TEXT_LIST)
    assert holiday_calendar.load_holiday_calendars() == ["holidays-2026.txt: 5 public holidays saved"]
    assert saved() == {
        "2026-02-21": "Shaheed Day",
        "2026-10-20": "Durga Puja (Nabami)",
        "2026-10-21": "Durga Puja (Bijoya Dashami)",
        "2026-12-16": "Victory Day",
        "2026-12-25": "Christmas Day",
    }
    assert asked == []  # a clean list needs no AI


def test_the_real_2026_list_has_every_government_holiday(client):
    found = holiday_calendar.dates_in_text(tidy(pdf_text(REAL_LIST)))
    days = {day.isoformat() for day in found}
    assert len(days) == 25
    assert {"2026-10-20", "2026-10-21", "2026-12-16", "2026-12-25", "2026-03-21", "2026-05-28"} <= days
    assert "2026-04-13" not in days  # hill districts only
    assert all(date.fromisoformat(d).year == 2026 for d in days)


def test_a_file_read_before_is_not_read_again(client, monkeypatch):
    put("holidays-2026.txt", TEXT_LIST)
    holiday_calendar.load_holiday_calendars()
    assert holiday_calendar.load_holiday_calendars() == ["holidays-2026.txt: already read"]
    assert holiday_calendar.load_holiday_calendars(force=True) == ["holidays-2026.txt: 5 public holidays saved"]


def test_a_changed_file_replaces_the_days_of_its_year_but_keeps_hand_added_ones(client):
    put("holidays-2026.txt", TEXT_LIST)
    holiday_calendar.load_holiday_calendars()
    with SessionLocal() as db:
        db.add(Holiday(day=date(2026, 11, 2), name="Company anniversary", source="manual"))
        db.add(Holiday(day=date(2026, 7, 11), name="junk from an old reading", source="pdf"))
        db.commit()
    put("holidays-2026.txt", "2026-12-16  Victory Day\n")
    holiday_calendar.load_holiday_calendars()
    assert saved() == {"2026-11-02": "Company anniversary", "2026-12-16": "Victory Day"}


def test_a_text_file_without_dates_says_how_to_write_it(client):
    put("holidays.txt", "Victory Day is in December.\n")
    result = holiday_calendar.load_holiday_calendars()[0]
    assert "one holiday per line" in result
    with SessionLocal() as db:
        assert "2026-10-21" in db.scalar(select(HolidaySource)).error


def test_a_file_taken_out_of_the_folder_is_forgotten(client):
    put("holidays-2026.txt", TEXT_LIST)
    holiday_calendar.load_holiday_calendars()
    (holiday_calendar.HOLIDAY_FOLDER / "holidays-2026.txt").unlink()
    holiday_calendar.load_holiday_calendars()
    with SessionLocal() as db:
        assert db.scalars(select(HolidaySource)).all() == []
    assert "2026-12-16" in saved()  # its days stay until a newer file for 2026 replaces them


def test_an_empty_or_missing_folder_does_nothing(client, monkeypatch, tmp_path):
    assert holiday_calendar.load_holiday_calendars() == []
    monkeypatch.setattr(holiday_calendar, "HOLIDAY_FOLDER", tmp_path / "missing")
    assert holiday_calendar.load_holiday_calendars() == []


def test_days_off_for_the_planner(client):
    with SessionLocal() as db:
        holiday_calendar.save_many(db, [(date(2026, 12, 16), "Victory Day")], source="file")
        assert holiday_calendar.days_off(db, date(2026, 12, 1), date(2026, 12, 31)) == {date(2026, 12, 16)}
        assert holiday_calendar.days_off(db, date(2027, 1, 1), date(2027, 1, 31)) == set()


def test_the_old_holiday_pages_are_gone(client, auth_headers):
    assert client.get("/api/holidays", headers=auth_headers).status_code == 404


# ---------- A PDF with normal text: RAG ----------


def test_an_english_pdf_is_read_with_rag(client, monkeypatch):
    seen: list = []
    fake_ai(monkeypatch, seen=seen)
    put("Calendar_2026.pdf", make_pdf(ENGLISH_PDF))
    assert holiday_calendar.load_holiday_calendars() == ["Calendar_2026.pdf: 3 public holidays saved"]
    assert saved() == {
        "2026-02-21": "Shaheed Day and International Mother Language Day",  # the AI left it out: the check added it
        "2026-03-26": "Independence Day",
        "2026-12-16": "Victory Day",
    }  # the optional one (17 January) and the undated one stay out
    assert "Independence Day - 26 March 2026" in seen[0]  # the real text of the PDF reached the AI
    assert "This calendar is for the year 2026." in seen[0]


def test_the_check_adds_every_date_the_ai_cut_short(client, monkeypatch):
    """The real failure on the Bangla calendar: the AI listed 11 of 25 days. Here it lists only one."""
    fake_ai(monkeypatch, [FoundHoliday(date="2026-02-04", name="Shab-e-Barat", kind="public")])
    put("bangladesh-public-holidays-2026.pdf", REAL_LIST.read_bytes())
    assert holiday_calendar.load_holiday_calendars() == ["bangladesh-public-holidays-2026.pdf: 25 public holidays saved"]
    days = saved()
    assert days["2026-10-21"] == "Durga Puja (Bijoya Dashami)"
    assert days["2026-12-25"] == "Christmas Day"


def test_a_pdf_whose_text_cannot_be_read_is_refused_clearly(client, monkeypatch):
    """The government's Bangla wall calendar: an old font, so its text comes out as letters like this."""
    monkeypatch.setattr(holiday_calendar, "pdf_text", lambda path: "MYcÖRvZš¿x evsjv‡`k miKvi 2026\nRvbyqvwi †cŠl-gvN\n" + "16 10 17 11 " * 30)
    asked: list = []
    fake_ai(monkeypatch, seen=asked)
    put("Calendar_2026.pdf", make_pdf(["anything"]))
    result = holiday_calendar.load_holiday_calendars()[0]
    assert "cannot be read" in result and "normal text" in result
    assert saved() == {} and asked == []  # nothing guessed, nothing saved


def test_when_the_ai_is_down_the_dates_written_in_the_pdf_are_used(client, monkeypatch):
    fake_ai(monkeypatch, down=True)
    put("Calendar_2026.pdf", make_pdf(ENGLISH_PDF))
    assert holiday_calendar.load_holiday_calendars() == ["Calendar_2026.pdf: 3 public holidays saved"]
    assert "2026-01-17" not in saved()  # the line says "Optional"


def test_when_the_ai_is_down_and_no_date_is_written_out_it_is_tried_again(client, monkeypatch):
    fake_ai(monkeypatch, down=True)
    put("Calendar_2026.pdf", make_pdf(["Public holidays 2026", "Eid: three days in March, after the moon is seen."]))
    assert "not available" in holiday_calendar.load_holiday_calendars()[0]
    fake_ai(monkeypatch, [FoundHoliday(date="2026-03-20", name="Eid-ul-Fitr", kind="public")])
    assert holiday_calendar.load_holiday_calendars() == ["Calendar_2026.pdf: 1 public holidays saved"]


def test_a_broken_file_never_stops_the_others(client):
    put("a-broken.pdf", b"%PDF-1.4 this is not really a pdf")
    put("holidays-2026.txt", TEXT_LIST)
    results = holiday_calendar.load_holiday_calendars()
    assert "holidays-2026.txt: 5 public holidays saved" in results
    assert "a-broken.pdf: The file is damaged or cannot be opened." in results


LONG_DOCUMENT = (
    ["Ministry of Public Administration circular about office hours."]
    + ["Offices open at nine in the morning and close at five in the evening. Staff sign the register daily."] * 30
    + ["Public holidays 2026: Victory Day 16 December 2026, a general holiday. Christmas Day 25 December 2026, a public holiday."]
    + ["Annual leave rules for government staff are described in a separate circular."] * 30
)


def test_only_the_holiday_pieces_reach_the_ai(client, monkeypatch):
    seen: list = []
    fake_ai(monkeypatch, [FoundHoliday(date="2026-12-16", name="Victory Day", kind="public")], seen)
    monkeypatch.setattr(holiday_calendar, "CHUNKS_FOR_LIST", 2)
    with SessionLocal() as db:
        result = holiday_calendar.read_pdf(db, make_pdf(LONG_DOCUMENT), "bd-holidays-2026.pdf")
    assert result.chunks_stored > 5  # a long document is cut into many pieces
    assert result.chunks_used == 2
    assert "Victory Day 16 December 2026" in seen[0]  # retrieval found the piece with the dates
    assert seen[0].count("sign the register") < 10  # and left most of the office-hours text out


def test_a_clean_list_comes_back(client):
    cleaned = holiday_calendar.clean(
        [
            FoundHoliday(date="2026-12-16", name="Victory Day", kind="public"),
            FoundHoliday(date="2026-03-26", name="Independence Day", kind="public"),
            FoundHoliday(date="2026-03-26", name="Another name", kind="optional"),  # same day: joined
        ]
    )
    assert [h.day.isoformat() for h in cleaned] == ["2026-03-26", "2026-12-16"]
    assert cleaned[0].name == "Independence Day / Another name" and cleaned[0].kind == "public"


# ---------- The invite pop-up never hides a missing list ----------


def test_the_invite_pop_up_says_how_many_holidays_are_skipped(client, auth_headers):
    with SessionLocal() as db:
        job = JobProfile(title="Data Engineer")
        db.add(job)
        db.commit()
        job_id = job.id
    info = client.get(f"/api/jobs/{job_id}/invite-info", headers=auth_headers).json()
    assert info["holidays_ahead"] == 0 and "No holiday list" in info["calendar_problem"]

    put("holidays-2030.txt", "2030-12-16  Victory Day\n2030-12-25  Christmas Day\n")
    holiday_calendar.load_holiday_calendars()
    info = client.get(f"/api/jobs/{job_id}/invite-info", headers=auth_headers).json()
    assert info == {"holidays_ahead": 2, "calendar_problem": ""}
