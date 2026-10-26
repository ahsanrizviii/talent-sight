"""Tests for the skills reference knowledge base (Task 9.1.1). The real embedding model is never loaded."""

from sqlalchemy import select

from app import references
from app.db import SessionLocal
from app.models import ReferenceChunk

SAMPLE = """# Python

Sources: https://docs.python.org/3/

## Exceptions

Errors are raised as exceptions
and handled with try and except.

## Generators

A generator uses yield to produce values lazily.
"""

PDF_TEXT = """TalentSight - Skills reference for the Evaluation Agent
Page 1
Skills Reference
Some title page text.
1. Python
Sources:
https://docs.python.org/3/tutorial/
https://peps.python.org/pep-0008/
1.1 Data types
Dictionaries keep insertion order since Python
3.7 and later, so the order can be trusted.
1.2 Generators
A generator uses yield to produce values lazily.
TalentSight - Skills reference for the Evaluation Agent
Page 2
2. Docker
Sources:
https://docs.docker.com/get-started/
2.1 Volumes
A volume keeps data after the container is removed.
"""


def test_every_section_becomes_one_chunk():
    chunks = references.split_reference(SAMPLE, "python.md")
    assert [c["heading"] for c in chunks] == ["Exceptions", "Generators"]
    first = chunks[0]
    assert first["skill"] == "Python" and first["source"] == "python.md"
    assert first["url"] == "https://docs.python.org/3/"
    # Lines of one section are joined, and the skill and heading lead the text so a search can find them.
    assert first["text"] == "Python — Exceptions: Errors are raised as exceptions and handled with try and except."


def test_the_pdf_text_becomes_one_document_per_skill():
    documents = references.pdf_to_markdown(PDF_TEXT)
    assert len(documents) == 2
    chunks = references.split_reference(documents[0], "skills-reference.pdf")
    assert [c["heading"] for c in chunks] == ["Data types", "Generators"]
    assert chunks[0]["url"] == "https://docs.python.org/3/tutorial/ https://peps.python.org/pep-0008/"
    # A wrapped line that starts with "3.7" is part of the paragraph, not a new heading; the page footer is dropped.
    assert chunks[0]["text"].endswith("since Python 3.7 and later, so the order can be trusted.")
    assert "Page 2" not in chunks[1]["text"]
    assert references.split_reference(documents[1], "skills-reference.pdf")[0]["skill"] == "Docker"


def test_a_file_without_sections_gives_nothing():
    assert references.split_reference("# Notes\n\nJust a line.\n", "notes.md") == []


def test_the_real_documents_are_well_formed():
    found = references.read_references()
    assert {c["source"] for c in found} == {"skills-reference.pdf"}
    assert len({c["skill"] for c in found}) >= 7  # one block per skill area
    for chunk in found:
        assert chunk["skill"] and chunk["heading"] and chunk["url"].startswith("https://")
        assert 300 < len(chunk["text"]) < 2500  # big enough to say something, small enough for one embedding


def test_the_table_matches_the_files_after_start(client):
    with SessionLocal() as db:
        stored = list(db.scalars(select(ReferenceChunk.text).order_by(ReferenceChunk.id)))
    assert stored == [c["text"] for c in references.read_references()]


def test_loading_twice_changes_nothing(client):
    with SessionLocal() as db:
        before = list(db.scalars(select(ReferenceChunk.id).order_by(ReferenceChunk.id)))
    references.load_references()
    with SessionLocal() as db:
        after = list(db.scalars(select(ReferenceChunk.id).order_by(ReferenceChunk.id)))
    assert before == after  # same rows, nothing embedded again


def test_search_finds_the_section_about_the_question(client):
    with SessionLocal() as db:
        found = references.search_references(db, "Docker volumes keep database data when the container is removed", limit=3)
    assert len(found) == 3
    assert any(chunk.skill == "Docker and Containers" for chunk in found)