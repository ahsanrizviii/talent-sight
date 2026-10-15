"""Tests for the holiday calendar, read from the knowledge/holidays folder when the API starts (RAG).
The AI is faked; the PDF reading, the chunking and the vector search are real (with the test
embedding from conftest). The folder is a temporary one (conftest), so no real PDF is ever read."""

from datetime import date

from sqlalchemy import select

from app import holiday_calendar
from app.db import SessionLocal
from app.holiday_calendar import FoundHoliday, FoundHolidays
from app.models import Holiday, HolidaySource
from scripts.make_sample_cvs import make_pdf

GOVERNMENT_LIST = [
    "Government of the People's Republic of Bangladesh",
    "Public Holidays 2026",
    "Shaheed Day and International Mother Language Day - 21 February 2026",
    "Independence Day - 26 March 2026",
    "May Day - 1 May 2026",
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


def put_pdf(name: str = "Calendar_2026.pdf", lines: list[str] = GOVERNMENT_LIST) -> None:
    (holiday_calendar.HOLIDAY_FOLDER / name).write_bytes(make_pdf(lines))


def saved() -> dict[str, str]:
    with SessionLocal() as db:
        return {h.day.isoformat(): h.name for h in db.scalars(select(Holiday).order_by(Holiday.day))}


# ---------- Reading the folder ----------


def test_public_holidays_in_the_folder_are_saved(client, monkeypatch):
    seen: list = []
    fake_ai(monkeypatch, seen=seen)
    put_pdf()
    results = holiday_calendar.load_holiday_calendars()
    assert results == ["Calendar_2026.pdf: 2 public holidays saved"]
    assert saved() == {"2026-03-26": "Independence Day", "2026-12-16": "Victory Day"}  # optional and undated left out
    assert "Independence Day - 26 March 2026" in seen[0]  # the real text of the PDF reached the AI
    assert "This calendar is for the year 2026." in seen[0]


def test_a_file_read_before_is_not_read_again(client, monkeypatch):
    seen: list = []
    fake_ai(monkeypatch, seen=seen)
    put_pdf()
    holiday_calendar.load_holiday_calendars()
    assert holiday_calendar.load_holiday_calendars() == ["Calendar_2026.pdf: already read"]
    assert len(seen) == 1  # the AI was asked only once
    holiday_calendar.load_holiday_calendars(force=True)
    assert len(seen) == 2  # unless asked to read everything again


def test_a_changed_calendar_replaces_the_days_of_that_year(client, monkeypatch):
    fake_ai(monkeypatch)
    put_pdf()
    holiday_calendar.load_holiday_calendars()
    fake_ai(monkeypatch, [FoundHoliday(date="2026-12-16", name="Victory Day", kind="public")])
    put_pdf(lines=GOVERNMENT_LIST + ["Corrected edition"])  # same file name, new contents
    holiday_calendar.load_holiday_calendars()
    assert saved() == {"2026-12-16": "Victory Day"}  # 26 March came from the old file: gone


def test_when_the_ai_is_down_it_is_tried_again_next_start(client, monkeypatch):
    fake_ai(monkeypatch, down=True)
    put_pdf()
    assert "not available" in holiday_calendar.load_holiday_calendars()[0]
    with SessionLocal() as db:
        assert db.scalar(select(HolidaySource)).error != ""
    fake_ai(monkeypatch)
    assert holiday_calendar.load_holiday_calendars() == ["Calendar_2026.pdf: 2 public holidays saved"]


def test_a_broken_file_never_stops_the_others(client, monkeypatch):
    fake_ai(monkeypatch)
    (holiday_calendar.HOLIDAY_FOLDER / "a-broken.pdf").write_bytes(b"%PDF-1.4 this is not really a pdf")
    put_pdf()
    results = holiday_calendar.load_holiday_calendars()
    assert len(results) == 2
    assert "Calendar_2026.pdf: 2 public holidays saved" in results
    assert "a-broken.pdf: The file is damaged or cannot be opened." in results


def test_an_empty_or_missing_folder_does_nothing(client, monkeypatch, tmp_path):
    assert holiday_calendar.load_holiday_calendars() == []
    monkeypatch.setattr(holiday_calendar, "HOLIDAY_FOLDER", tmp_path / "missing")
    assert holiday_calendar.load_holiday_calendars() == []


def test_days_off_for_the_planner(client):
    with SessionLocal() as db:
        holiday_calendar.save_many(db, [(date(2026, 12, 16), "Victory Day")], source="pdf")
        assert holiday_calendar.days_off(db, date(2026, 12, 1), date(2026, 12, 31)) == {date(2026, 12, 16)}
        assert holiday_calendar.days_off(db, date(2027, 1, 1), date(2027, 1, 31)) == set()


def test_the_old_holiday_pages_are_gone(client, auth_headers):
    assert client.get("/api/holidays", headers=auth_headers).status_code == 404


# ---------- RAG: pieces and retrieval ----------

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


def test_only_pdfs_are_read(client):
    with SessionLocal() as db:
        try:
            holiday_calendar.read_pdf(db, b"hello", "holidays.txt")
        except holiday_calendar.HolidayReadError as problem:
            assert "PDF" in str(problem)
        else:
            raise AssertionError("a text file was accepted")


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


# ---------- The Bangla government calendar ----------

# What the PDF's own text layer gives for the government calendar: an old Bangla font (Bijoy),
# so the letters are wrong ("Rvbyqvwi" is "জানুয়ারি", January).
OLD_FONT_TEXT = "MYcÖRvZš¿x evsjv‡`k miKvi 2026 wLªóvã\nRvbyqvwi †cŠl-gvN iRe-kvevb †deªæqvwi\n" + "16 10 17 11 18 12 19 13 " * 20

# What Bangla + English OCR gives for the same page (a short part of it, with an OCR slip: "এচ্ছিক").
BANGLA_OCR_TEXT = "\n".join(
    [
        "২০২৬ খ্রিষ্টাব্দ | ১৪৩২-১৪৩৩ বঙ্গাব্দ | ১৪৪৭-১৪৪৮ হিজরি",
        "জানুয়ারি পৌষ-মাঘ ফেব্রুয়ারি মাঘ-ফাল্গুন মার্চ ফাল্গুন-চৈত্র",
        "সাধারণ ছুটি-২১ ফেব্রুয়ারি (০৮ ফাল্গুন)-শহিদ দিবস ও আন্তর্জাতিক মাতৃভাষা দিবস | ২৬ মার্চ (১২ চৈত্র)-স্বাধীনতা ও জাতীয় দিবস |",
        "১৬ ডিসেম্বর (০১ পৌষ)-বিজয় দিবস।",
        "এচ্ছিক ছুটি (মুসলিম পর্ব)-১৭ জানুয়ারি (০৩ মাঘ)-*শব-ই-মিরাজ |",
    ]
)


def bangla_calendar(monkeypatch, ocr_text: str = BANGLA_OCR_TEXT) -> list:
    """Fakes the two ways of reading the PDF. Returns a list that collects the OCR languages used."""
    languages: list = []

    def ocr(path, lang="eng"):
        languages.append(lang)
        return ocr_text

    monkeypatch.setattr(holiday_calendar, "pdf_text", lambda path: OLD_FONT_TEXT)
    monkeypatch.setattr(holiday_calendar, "pdf_ocr", ocr)
    monkeypatch.setattr(holiday_calendar, "ocr_languages", lambda: "ben+eng")
    return languages


def test_text_with_month_names_is_readable_and_old_font_text_is_not():
    assert holiday_calendar.readable("\n".join(GOVERNMENT_LIST))
    assert holiday_calendar.readable(BANGLA_OCR_TEXT)
    assert not holiday_calendar.readable(OLD_FONT_TEXT)


def test_the_year_is_found_in_bangla_or_english_digits():
    assert holiday_calendar.calendar_year(BANGLA_OCR_TEXT) == 2026
    assert holiday_calendar.calendar_year("বর্ষপঞ্জি\n২০২৬ খ্রিষ্টাব্দ\n...\nপ্রেস-২৫৫২ ২০২৫/২৬ কপি, ২০২৫") == 2026  # title, not the printer's line
    assert holiday_calendar.calendar_year("no year here") is None


def test_an_unreadable_text_layer_is_read_with_bangla_ocr(client, monkeypatch):
    languages = bangla_calendar(monkeypatch)
    seen: list = []
    fake_ai(monkeypatch, [FoundHoliday(date="2026-12-16", name="Victory Day", kind="public")], seen)
    put_pdf()
    assert holiday_calendar.load_holiday_calendars() == ["Calendar_2026.pdf: 3 public holidays saved"]
    assert languages == ["ben+eng"]
    assert "This calendar is for the year 2026." in seen[0]
    assert "সাধারণ ছুটি-২১ ফেব্রুয়ারি" in seen[0]  # the Bangla holiday lines reached the AI


def test_a_pdf_with_no_month_names_is_refused_clearly(client, monkeypatch):
    bangla_calendar(monkeypatch, ocr_text="just some pictures")
    fake_ai(monkeypatch, [])
    put_pdf()
    result = holiday_calendar.load_holiday_calendars()[0]
    assert "month names" in result
    assert saved() == {}


def test_holiday_pieces_are_found_by_keyword_even_when_far_down(client):
    filler = [f"{n} {n + 1} {n + 2} {n + 3} জানুয়ারি" for n in range(30)]
    pieces = filler[:20] + ["সাধারণ ছুটি-২১ ফেব্রুয়ারি (০৮ ফাল্গুন)-শহিদ দিবস | ২১ মার্চ (০৭", "চৈত্র)-*ঈদ-উল-ফিতর |"] + filler[20:]
    with SessionLocal() as db:
        holiday_calendar.store_chunks(db, "calendar.pdf", pieces)
        texts = [chunk.text for chunk in holiday_calendar.holiday_pieces(db, "calendar.pdf")]
    assert len(texts) <= holiday_calendar.CHUNKS_FOR_LIST
    assert pieces[20] in texts  # says "ছুটি"
    assert pieces[21] in texts  # the piece after it: the Eid line runs on into it
    assert texts.index(pieces[20]) + 1 == texts.index(pieces[21])  # kept in document order


# ---------- The Bangla calendar: the dates come from the text, the AI only names them ----------

# The two public paragraphs of the real 2026 calendar, as OCR reads them (shortened), then an optional one.
GOVERNMENT_OCR = "\n".join(
    [
        "২০২৬ খ্রিষ্টাব্দ | ১৪৩২-১৪৩৩ বঙ্গাব্দ",
        "জানুয়ারি ফেব্রুয়ারি মার্চ",
        "১০ ১২১১ ১৩:১২ ১৪1১৩ ১৫",  # a row of calendar numbers: no month name, so no date
        "সাধারণ ছুটি-২১ ফেব্রুয়ারি (০৮ ফাল্গুন)_শহিদ দিবস ও আন্তর্জাতিক মাতৃভাষা দিবস | ২১ মার্চ (04",
        "চৈত্র)-*ঈদ-উল-ফিতর | ১৩ এপ্রিল (৩০ চৈত্র)-চৈত্রসংক্রান্তি শুধু রাঙ্গামাটি, খাগড়াছড়ি ও",
        "বান্দরবান পার্বত্য জেলাসমূহের জন্য প্রযোজ্য)। ০১ মে (১৮ বৈশাখ)-মে দিবস 1 ২১ অক্টোবর (০৫ কার্তিক)-দুর্গাপূজা (বিজয়া দশমী) |",
        "১৬ ডিসেম্বর (০১ পৌষ)_বিজয় দিবস।",
        "নির্বাহী আদেশে সরকারি ছুটি_১৯ মার্চ, ২০ মার্চ এবং ২২",
        "মার্চ ও ২৩ মার্চ (০৫, ০৬ চৈত্র ও ০৮, ০৯ চৈত্র)-*ঈদ-উল-ফিতর | ২০ অক্টোবর (০৪ কার্তিক)-_ দুর্গাপূজা (নবমী)।",
        "এচ্ছিক ছুটি (মুসলিম পর্ব)_১৭ জানুয়ারি (০৩ মাঘ)-*শব-ই-মিরাজ |",
        "টীকা : একজন কর্মচারীকে তার নিজ ধর্ম অনুযায়ী ঐচ্ছিক ছুটি",
    ]
)
PUBLIC_DAYS = [
    "2026-02-21", "2026-03-19", "2026-03-20", "2026-03-21", "2026-03-22", "2026-03-23",
    "2026-05-01", "2026-10-20", "2026-10-21", "2026-12-16",
]


def test_the_public_paragraphs_and_their_dates_are_found_by_code():
    sections = holiday_calendar.public_sections(GOVERNMENT_OCR)
    assert len(sections) == 2  # general and executive order; the optional one is left out
    found = {day.isoformat(): name for section in sections for day, name in holiday_calendar.dates_in(section, 2026)}
    assert sorted(found) == PUBLIC_DAYS  # 13 April (only the hill districts) and 17 January (optional) are not there
    assert found["2026-03-19"] == "ঈদ-উল-ফিতর"  # a group of dates shares the name written after the last one
    assert found["2026-05-01"] == "মে দিবস"  # the OCR "1" at the end is cleaned off


def test_dates_the_ai_leaves_out_are_still_saved_and_made_up_ones_are_not(client, monkeypatch):
    """The real failure: the AI cut a long list short (11 of 25). The dates come from the text now."""
    monkeypatch.setattr(holiday_calendar, "pdf_text", lambda path: OLD_FONT_TEXT)
    monkeypatch.setattr(holiday_calendar, "pdf_ocr", lambda path, lang="eng": GOVERNMENT_OCR)
    monkeypatch.setattr(holiday_calendar, "ocr_languages", lambda: "ben+eng")
    asked: list = []
    fake_ai(
        monkeypatch,
        [
            FoundHoliday(date="2026-02-21", name="Shaheed Day", kind="public"),
            FoundHoliday(date="2026-07-07", name="Made-up holiday", kind="public"),  # not in the text
        ],
        asked,
    )
    put_pdf()
    assert holiday_calendar.load_holiday_calendars() == ["Calendar_2026.pdf: 10 public holidays saved"]
    days = saved()
    assert sorted(days) == PUBLIC_DAYS
    assert days["2026-02-21"] == "Shaheed Day"  # the AI's English name where it gave one
    assert days["2026-10-21"] == "দুর্গাপূজা (বিজয়া দশমী)"  # the Bangla name where it did not
    assert len(asked) == 2  # one short paragraph per AI call, not the whole calendar at once
    assert all("Every holiday below is a public holiday." in prompt for prompt in asked)


def test_with_the_ai_down_the_dates_are_still_saved(client, monkeypatch):
    monkeypatch.setattr(holiday_calendar, "pdf_text", lambda path: OLD_FONT_TEXT)
    monkeypatch.setattr(holiday_calendar, "pdf_ocr", lambda path, lang="eng": GOVERNMENT_OCR)
    monkeypatch.setattr(holiday_calendar, "ocr_languages", lambda: "ben+eng")
    fake_ai(monkeypatch, down=True)
    put_pdf()
    holiday_calendar.load_holiday_calendars()
    assert sorted(saved()) == PUBLIC_DAYS  # the planner already skips every holiday
    with SessionLocal() as db:
        assert "Bangla" in db.scalar(select(HolidaySource)).error  # so the names are tried again next start


def test_the_invite_pop_up_says_how_many_holidays_are_skipped(client, auth_headers, monkeypatch):
    from app.models import JobProfile

    with SessionLocal() as db:
        job = JobProfile(title="Data Engineer")
        db.add(job)
        db.commit()
        job_id = job.id
    info = client.get(f"/api/jobs/{job_id}/invite-info", headers=auth_headers).json()
    assert info["holidays_ahead"] == 0 and "No holiday calendar" in info["calendar_problem"]

    fake_ai(monkeypatch)
    put_pdf()
    holiday_calendar.load_holiday_calendars()
    info = client.get(f"/api/jobs/{job_id}/invite-info", headers=auth_headers).json()
    assert info["calendar_problem"] == ""

