
import logging
import re
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import knowledge, library
from app.db import SessionLocal
from app.models import ReferenceChunk

log = logging.getLogger("talentsight.references")



def split_reference(markdown: str, source: str) -> list[dict]:
    """One dict per "## " section: the skill, the heading, the source links and the text."""
    skill, url, heading, lines = "", "", "", []
    sections: list[dict] = []

    def close_section() -> None:
        body = " ".join(line for line in lines if line)
        if heading and body:
            sections.append({"source": source, "skill": skill, "heading": heading, "url": url, "body": body})

    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            close_section()
            heading, lines = line[3:].strip(), []
        elif line.startswith("# ") and not skill:
            skill = line[2:].strip()
        elif line.lower().startswith("sources:") and not heading:
            url = line.split(":", 1)[1].strip()
        elif heading:
            lines.append(line)
    close_section()

    for section in sections:
        # The skill and heading go into the chunk itself, so a search for "Python exceptions" finds it.
        section["text"] = f"{section['skill']} — {section['heading']}: {section.pop('body')}"
    return sections


SKILL_LINE = re.compile(r"^(\d+)\.\s+(\S.*)$")  # "1. Python"
SECTION_LINE = re.compile(r"^(\d+)\.(\d+)\s+(\S.*)$")  # "1.2 Functions, arguments and scope"
PAGE_NOISE = re.compile(r"^(TalentSight - Skills reference.*|Page \d+)$")  # the footer printed on every page


def pdf_to_markdown(text: str) -> list[str]:
    """Turns the text of the skills PDF into one small Markdown document per skill.

    The PDF numbers its headings: "1. Python" is a skill, "1.1 Data types" is a section of it.
    A line only counts as a heading when its number is the next one in order, so a wrapped line
    such as "3.7 and later ..." inside a paragraph is never mistaken for one.
    """
    documents: list[list[str]] = []
    skill_number, last_section, in_sources = 0, 0, False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or PAGE_NOISE.match(line):
            continue
        skill = SKILL_LINE.match(line)
        section = SECTION_LINE.match(line)
        if skill and int(skill.group(1)) == skill_number + 1:
            skill_number, last_section, in_sources = skill_number + 1, 0, True
            documents.append([f"# {skill.group(2)}", ""])
        elif not documents:
            continue  # the title page, before the first skill
        elif section and int(section.group(1)) == skill_number and int(section.group(2)) == last_section + 1:
            last_section, in_sources = last_section + 1, False
            documents[-1] += ["", f"## {section.group(3)}"]
        elif in_sources:
            if line.lower() == "sources:":
                documents[-1].append("Sources:")
            else:
                documents[-1][-1] += f" {line}"  # every link is added to the one "Sources:" line
        else:
            documents[-1].append(line)
    return ["\n".join(document) for document in documents]


def read_references() -> list[dict]:
    """Every section of every skills reference document in the Library, in a fixed order.

    One PDF holds all the skills. A Markdown file (one skill per file) still works, so a new skill
    can be added on the Library page without rebuilding the PDF.
    """
    found: list[dict] = []
    for path in library.files_of("skills"):
        if path.suffix == ".md":
            found += split_reference(path.read_text(encoding="utf-8"), path.name)
        elif path.suffix == ".pdf":
            text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
            for document in pdf_to_markdown(text):
                found += split_reference(document, path.name)
    return found


def load_references() -> None:
    """Makes reference_chunks match the files. Runs at every start, like the hiring policies."""
    sections = read_references()
    with SessionLocal() as db:
        stored = [(row.source, row.text) for row in db.scalars(select(ReferenceChunk).order_by(ReferenceChunk.id))]
        if stored == [(s["source"], s["text"]) for s in sections]:
            return  # nothing changed, so nothing is embedded again
        db.execute(delete(ReferenceChunk))
        if sections:
            # knowledge.embed_texts, not a copy of it: the tests swap it for a fake without the real model.
            vectors = knowledge.embed_texts([s["text"] for s in sections])
            for section, vector in zip(sections, vectors):
                db.add(ReferenceChunk(**section, embedding=vector))
        else:
            log.warning("no skills reference documents found", extra={"event": "references_missing"})
        db.commit()
    log.info("skills references loaded", extra={"event": "references_loaded", "count": len(sections)})


def search_references(db: Session, question: str, limit: int = 3) -> list[ReferenceChunk]:
    """The sections closest in meaning to the question (cosine distance), closest first."""
    vector = knowledge.embed_question(question)
    closest_first = select(ReferenceChunk).order_by(ReferenceChunk.embedding.cosine_distance(vector)).limit(limit)
    return list(db.scalars(closest_first))