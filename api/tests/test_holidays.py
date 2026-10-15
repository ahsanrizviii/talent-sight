"""Tests for the holiday calendar on the Settings page (with RAG). The AI is faked; the PDF reading,
the chunking and the vector search are real (with the test embedding from conftest)."""

from datetime import date

from app import holiday_calendar
from app.holiday_calendar import FoundHoliday, FoundHolidays
from scripts.make_sample_cvs import make_pdf

GOVERNMENT_LIST = [
    "Government of the People's Republic of Bangladesh",
    "Public Holidays 2026",
    "Shaheed Day and International Mother Language Day - 21 February 2026",
    "Independence Day - 26 March 2026",
    "Eid ul-Fitr - 19 to 21 March 2026",
    "May Day - 1 May 2026",
    "Victory Day - 16 December 2026",
] + ["Offices remain closed on these days."] * 4


def fake_ai(monkeypatch, found: list[FoundHoliday], seen: list | None = None, reply: str = "Victory Day is on Wednesday, 16 December 2026."):
    def answer(system_prompt, user_prompt, answer_shape, **options):
        if seen is not None:
            seen.append(user_prompt)
        if answer_shape is holiday_calendar.HolidayAnswer:
            return holiday_calendar.HolidayAnswer(answer=reply)
        return FoundHolidays(holidays=found)

    monkeypatch.setattr(holiday_calendar, "ask_llm", answer)


def upload(client, headers, data: bytes, name="holidays.pdf"):
    return client.post("/api/holidays/read-pdf", files={"file": (name, data, "application/pdf")}, headers=headers)


def test_the_pdf_text_goes_to_the_ai_and_a_clean_list_comes_back(client, auth_headers, monkeypatch):
    seen: list = []
    fake_ai(
        monkeypatch,
        [
            FoundHoliday(date="2026-12-16", name="Victory Day", kind="public"),
            FoundHoliday(date="2026-03-26", name="Independence Day", kind="public"),
            FoundHoliday(date="moon-dependent", name="Shab-e-Barat", kind="public"),  # not a date: dropped
            FoundHoliday(date="2026-03-26", name="Another name", kind="optional"),  # same day: joined
        ],
        seen,
    )
    response = upload(client, auth_headers, make_pdf(GOVERNMENT_LIST))
    assert response.status_code == 200
    assert "Independence Day - 26 March 2026" in seen[0]  # the real text of the PDF reached the AI
    body = response.json()
    assert body["source"] == "holidays.pdf" and body["chunks_stored"] >= 1
    days = body["holidays"]
    assert [d["day"] for d in days] == ["2026-03-26", "2026-12-16"]  # sorted, one per day
    assert days[0]["name"] == "Independence Day / Another name"
    assert days[0]["kind"] == "public"


def test_reading_saves_nothing(client, auth_headers, monkeypatch):
    fake_ai(monkeypatch, [FoundHoliday(date="2026-05-01", name="May Day", kind="public")])
    upload(client, auth_headers, make_pdf(GOVERNMENT_LIST))
    assert client.get("/api/holidays", headers=auth_headers).json() == []


def test_only_pdfs_are_read(client, auth_headers):
    response = upload(client, auth_headers, b"hello", name="holidays.txt")
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_ai_down_gives_a_clear_message(client, auth_headers, monkeypatch):
    def down(*args, **kwargs):
        raise holiday_calendar.LLMUnavailable("The AI service is not available right now. Please try again.")

    monkeypatch.setattr(holiday_calendar, "ask_llm", down)
    response = upload(client, auth_headers, make_pdf(GOVERNMENT_LIST))
    assert response.status_code == 400
    assert "not available" in response.json()["detail"]


def test_saving_adds_new_days_and_renames_existing_ones(client, auth_headers):
    first = client.post(
        "/api/holidays",
        json={"source": "pdf", "holidays": [{"day": "2026-03-26", "name": "Independence Day"}, {"day": "2026-05-01", "name": "May Day"}]},
        headers=auth_headers,
    ).json()
    assert first["added"] == 2
    again = client.post(
        "/api/holidays",
        json={"holidays": [{"day": "2026-05-01", "name": "Labour Day"}, {"day": "2026-12-16", "name": "Victory Day"}]},
        headers=auth_headers,
    ).json()
    assert again["added"] == 1
    names = {h["day"]: h["name"] for h in again["holidays"]}
    assert names == {"2026-03-26": "Independence Day", "2026-05-01": "Labour Day", "2026-12-16": "Victory Day"}


def test_a_holiday_can_be_removed_and_years_filtered(client, auth_headers):
    saved = client.post(
        "/api/holidays",
        json={"holidays": [{"day": "2026-12-16", "name": "Victory Day"}, {"day": "2027-02-21", "name": "Language Day"}]},
        headers=auth_headers,
    ).json()["holidays"]
    assert [h["day"] for h in client.get("/api/holidays?year=2027", headers=auth_headers).json()] == ["2027-02-21"]
    assert client.delete(f"/api/holidays/{saved[0]['id']}", headers=auth_headers).status_code == 204
    assert [h["day"] for h in client.get("/api/holidays", headers=auth_headers).json()] == ["2027-02-21"]


def test_days_off_for_the_planner(client, auth_headers):
    client.post("/api/holidays", json={"holidays": [{"day": "2026-12-16", "name": "Victory Day"}]}, headers=auth_headers)
    from app.db import SessionLocal

    with SessionLocal() as db:
        assert holiday_calendar.days_off(db, date(2026, 12, 1), date(2026, 12, 31)) == {date(2026, 12, 16)}
        assert holiday_calendar.days_off(db, date(2027, 1, 1), date(2027, 1, 31)) == set()


def test_holidays_need_a_login(client):
    assert client.get("/api/holidays").status_code == 401
    assert client.post("/api/holidays", json={"holidays": []}).status_code == 401


# ---------- RAG: pieces, retrieval, questions ----------

LONG_DOCUMENT = (
    ["Ministry of Public Administration circular about office hours."]
    + ["Offices open at nine in the morning and close at five in the evening. Staff sign the register daily."] * 30
    + ["Public holidays 2026: Victory Day 16 December 2026, a general holiday. Christmas Day 25 December 2026, a public holiday."]
    + ["Annual leave rules for government staff are described in a separate circular."] * 30
)


def test_the_pdf_is_stored_in_pieces_and_only_the_holiday_pieces_reach_the_ai(client, auth_headers, monkeypatch):
    seen: list = []
    fake_ai(monkeypatch, [FoundHoliday(date="2026-12-16", name="Victory Day", kind="public")], seen)
    monkeypatch.setattr(holiday_calendar, "CHUNKS_FOR_LIST", 2)
    body = upload(client, auth_headers, make_pdf(LONG_DOCUMENT), name="bd-holidays-2026.pdf").json()
    assert body["chunks_stored"] > 5  # a long document is cut into many pieces
    assert body["chunks_used"] == 2
    assert "Victory Day 16 December 2026" in seen[0]  # retrieval found the piece with the dates
    assert seen[0].count("sign the register") < 10  # and left most of the office-hours text out
    docs = client.get("/api/holidays/documents", headers=auth_headers).json()
    assert docs == [{"source": "bd-holidays-2026.pdf", "chunks": body["chunks_stored"]}]


def test_uploading_the_same_file_again_replaces_its_pieces(client, auth_headers, monkeypatch):
    fake_ai(monkeypatch, [])
    first = upload(client, auth_headers, make_pdf(GOVERNMENT_LIST)).json()
    upload(client, auth_headers, make_pdf(GOVERNMENT_LIST))
    assert client.get("/api/holidays/documents", headers=auth_headers).json()[0]["chunks"] == first["chunks_stored"]


def test_questions_are_answered_from_the_calendar_with_sources(client, auth_headers, monkeypatch):
    seen: list = []
    fake_ai(monkeypatch, [], seen)
    upload(client, auth_headers, make_pdf(LONG_DOCUMENT))
    client.post("/api/holidays", json={"holidays": [{"day": "2026-12-16", "name": "Victory Day"}]}, headers=auth_headers)
    seen.clear()
    response = client.post("/api/holidays/ask", json={"question": "When is Victory Day holiday?"}, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Victory Day is on Wednesday, 16 December 2026."
    assert any("Victory Day 16 December" in piece["text"] for piece in body["sources"])
    assert "Wednesday, 16 December 2026: Victory Day" in seen[0]  # the saved list went in too


def test_a_stored_calendar_can_be_forgotten(client, auth_headers, monkeypatch):
    fake_ai(monkeypatch, [])
    upload(client, auth_headers, make_pdf(GOVERNMENT_LIST), name="old.pdf")
    assert client.delete("/api/holidays/documents/old.pdf", headers=auth_headers).status_code == 204
    assert client.get("/api/holidays/documents", headers=auth_headers).json() == []


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


def test_an_unreadable_text_layer_is_read_with_bangla_ocr(client, auth_headers, monkeypatch):
    languages = bangla_calendar(monkeypatch)
    seen: list = []
    fake_ai(monkeypatch, [FoundHoliday(date="2026-12-16", name="Victory Day", kind="public")], seen)
    response = upload(client, auth_headers, make_pdf(["anything"]))
    assert response.status_code == 200
    assert languages == ["ben+eng"]
    assert "This calendar is for the year 2026." in seen[0]
    assert "সাধারণ ছুটি-২১ ফেব্রুয়ারি" in seen[0]  # the Bangla holiday lines reached the AI
    assert response.json()["holidays"][0]["name"] == "Victory Day"


def test_a_pdf_with_no_month_names_is_refused_clearly(client, auth_headers, monkeypatch):
    bangla_calendar(monkeypatch, ocr_text="just some pictures")
    fake_ai(monkeypatch, [])
    response = upload(client, auth_headers, make_pdf(["anything"]))
    assert response.status_code == 400
    assert "month names" in response.json()["detail"]
    assert "by hand" in response.json()["detail"]


def test_holiday_pieces_are_found_by_keyword_even_when_far_down(client):
    from app.db import SessionLocal

    filler = [f"{n} {n + 1} {n + 2} {n + 3} জানুয়ারি" for n in range(30)]
    pieces = filler[:20] + ["সাধারণ ছুটি-২১ ফেব্রুয়ারি (০৮ ফাল্গুন)-শহিদ দিবস | ২১ মার্চ (০৭", "চৈত্র)-*ঈদ-উল-ফিতর |"] + filler[20:]
    with SessionLocal() as db:
        holiday_calendar.store_chunks(db, "calendar.pdf", pieces)
        texts = [chunk.text for chunk in holiday_calendar.holiday_pieces(db, "calendar.pdf")]
    assert len(texts) <= holiday_calendar.CHUNKS_FOR_LIST
    assert pieces[20] in texts  # says "ছুটি"
    assert pieces[21] in texts  # the piece after it: the Eid line runs on into it
    assert texts.index(pieces[20]) + 1 == texts.index(pieces[21])  # kept in document order
