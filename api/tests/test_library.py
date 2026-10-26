"""Tests for the Library page: the documents the AI reads, managed from the website (Task 4.3.2 follow-up).

Every test has its own empty library folder (conftest.py), filled from api/knowledge at start-up.
Embeddings are the fake from conftest.py, so no model is loaded.
"""

from sqlalchemy import select

from app import holiday_calendar, knowledge, library
from app.db import SessionLocal
from app.models import JobProfile, PolicyChunk
from tests.conftest import fake_embedding

SKILL_NOTE = b"""# Testing
Sources: https://docs.pytest.org/

## Unit tests
A unit test checks one small piece of code on its own, with fixed inputs and an expected output.
Fixtures prepare what the test needs, and a fake replaces anything slow or outside the program,
such as a network service, so the test is fast and gives the same answer every time it runs.
"""


def documents(client, headers) -> dict[str, dict]:
    response = client.get("/api/library", headers=headers)
    assert response.status_code == 200, response.text
    return {kind["kind"]: kind for kind in response.json()}


def names(kind: dict) -> list[str]:
    return [document["name"] for document in kind["documents"]]


def upload(client, headers, kind: str, name: str, data: bytes):
    return client.post(f"/api/library/{kind}", headers=headers, files={"file": (name, data)})


def test_the_library_starts_with_the_documents_that_ship_with_the_code(client, auth_headers):
    found = documents(client, auth_headers)
    assert names(found["policies"]) == ["bjit-hiring-policies.pdf"]
    assert names(found["skills"]) == ["skills-reference.pdf"]
    assert names(found["holidays"]) == ["bangladesh-public-holidays-2026.pdf"]
    assert found["policies"]["documents"][0]["status"] == "read"
    assert found["skills"]["documents"][0]["status"] == "read"
    assert library.is_set_up("policies")


def test_a_new_skills_note_is_read_after_upload(client, auth_headers):
    response = upload(client, auth_headers, "skills", "testing.md", SKILL_NOTE)
    assert response.status_code == 201
    note = next(d for d in documents(client, auth_headers)["skills"]["documents"] if d["name"] == "testing.md")
    assert note["status"] == "read" and note["detail"] == "1 section"


def test_only_the_right_file_types_are_accepted(client, auth_headers):
    wrong = upload(client, auth_headers, "policies", "rules.docx", b"not a pdf")
    assert wrong.status_code == 400 and "PDF" in wrong.json()["detail"]
    fake_pdf = upload(client, auth_headers, "policies", "rules.pdf", b"hello")
    assert fake_pdf.status_code == 400 and "not a readable PDF" in fake_pdf.json()["detail"]
    assert client.post("/api/library/recipes", headers=auth_headers, files={"file": ("a.pdf", b"%PDF")}).status_code == 404


def test_a_file_name_cannot_reach_outside_the_library(client, auth_headers):
    assert upload(client, auth_headers, "skills", "../../evil.md", SKILL_NOTE).status_code == 201
    assert "evil.md" in names(documents(client, auth_headers)["skills"])
    assert (library.folder("skills") / "evil.md").is_file()


def test_removing_a_policy_document_removes_what_the_ai_knew_from_it(client, auth_headers):
    with SessionLocal() as db:
        assert db.scalars(select(PolicyChunk)).first() is not None
    response = client.delete("/api/library/policies/bjit-hiring-policies.pdf", headers=auth_headers)
    assert response.status_code == 200
    assert names(documents(client, auth_headers)["policies"]) == []
    with SessionLocal() as db:
        assert db.scalars(select(PolicyChunk)).first() is None
    assert client.delete("/api/library/policies/bjit-hiring-policies.pdf", headers=auth_headers).status_code == 404


def test_a_holiday_list_added_on_the_page_is_read(client, auth_headers, monkeypatch):
    monkeypatch.setattr(holiday_calendar, "HOLIDAY_FOLDER", None)  # read the Library, as in production
    # The real holiday PDF is read with OCR and the AI, which tests must never call: take it out first.
    (library.folder("holidays") / "bangladesh-public-holidays-2026.pdf").unlink()
    upload(client, auth_headers, "holidays", "holidays-2027.txt", b"2027-02-21  Shaheed Day\n2027-12-16  Victory Day\n")
    listed = next(d for d in documents(client, auth_headers)["holidays"]["documents"] if d["name"] == "holidays-2027.txt")
    assert listed["status"] == "read" and listed["detail"] == "2 public holidays (2027)"


def test_a_document_can_be_downloaded(client, auth_headers):
    upload(client, auth_headers, "skills", "testing.md", SKILL_NOTE)
    response = client.get("/api/library/skills/testing.md", headers=auth_headers)
    assert response.status_code == 200 and response.content == SKILL_NOTE


def test_the_library_needs_a_login(client):
    assert client.get("/api/library").status_code == 401


# ---------- Choosing the policy documents for one job ----------


def test_the_policy_search_can_be_limited_to_chosen_documents(client):
    with SessionLocal() as db:
        db.query(PolicyChunk).delete()
        for source, text in (("a.pdf", "1. Levels: junior roles need one year"), ("b.pdf", "1. Levels: junior roles need two years")):
            db.add(PolicyChunk(source=source, text=text, embedding=fake_embedding(text)))
        db.commit()
        everything = knowledge.search_policies(db, "junior roles", limit=5)
        chosen = knowledge.search_policies(db, "junior roles", limit=5, sources=["b.pdf"])
    assert {chunk.source for chunk in everything} == {"a.pdf", "b.pdf"}
    assert [chunk.source for chunk in chosen] == ["b.pdf"]


def test_a_job_says_which_policy_documents_it_was_written_with(client, auth_headers):
    with SessionLocal() as db:
        job = JobProfile(title="Backend Developer", required_skills=["Python"], policy_sources=["b.pdf"])
        db.add(job)
        db.commit()
        job_id = job.id
    assert client.get(f"/api/jobs/{job_id}", headers=auth_headers).json()["policy_sources"] == ["b.pdf"]
