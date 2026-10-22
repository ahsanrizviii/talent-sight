import logging
import re
from functools import lru_cache
from pathlib import Path

from fastembed import TextEmbedding
from pypdf import PdfReader
from sqlalchemy import func, select, delete
from sqlalchemy.orm import Session

from app import library
from app.db import SessionLocal
from app.models import PolicyChunk

log = logging.getLogger("talentsight.knowledge")

MODEL_NAME = "BAAI/bge-small-en-v1.5"  
MODEL_DIR = "/opt/models"  

SECTION_HEADING = re.compile(r"^\d+\.\s+[A-Z]")

@lru_cache  
def embedding_model() -> TextEmbedding:
    return TextEmbedding(MODEL_NAME, cache_dir=MODEL_DIR)


def embed_texts(texts: list[str]) -> list[list[float]]:
    return [vector.tolist() for vector in embedding_model().passage_embed(texts)]


def embed_question(question: str) -> list[float]:
    return next(iter(embedding_model().query_embed(question))).tolist()


def read_pdf_text(path: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def split_policy(text: str) -> list[str]:

    chunks: list[str] = []
    heading = ""
    body = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if SECTION_HEADING.match(line):
            if heading and body:
                chunks.append(f"{heading}: {body}")
            heading, body = line, ""
        elif heading:
            
            body += line if body.endswith("-") or not body else f" {line}"
    if heading and body:
        chunks.append(f"{heading}: {body}")
    return chunks


def read_policies() -> list[tuple[str, str]]:
    """(file name, section) for every section of every policy document in the Library, in a fixed order."""
    found: list[tuple[str, str]] = []
    for path in library.files_of("policies"):
        try:
            found += [(path.name, chunk) for chunk in split_policy(read_pdf_text(path))]
        except Exception as error:  # one broken PDF must not hide the other policies
            log.warning(f"policy file {path.name} could not be read", exc_info=error, extra={"event": "policy_file_failed"})
    return found


def load_policies() -> None:
    """Makes policy_chunks match the policy documents in the Library. Runs at every start and after
    every change on the Library page, so an added, replaced or removed document takes effect."""
    chunks = read_policies()
    with SessionLocal() as db:
        stored = [(row.source, row.text) for row in db.scalars(select(PolicyChunk).order_by(PolicyChunk.id))]
        if stored == chunks:
            return  # nothing changed
        db.execute(delete(PolicyChunk))
        if chunks:
            for (source, chunk), vector in zip(chunks, embed_texts([text for _, text in chunks])):
                db.add(PolicyChunk(source=source, text=chunk, embedding=vector))
        else:
            log.warning("no hiring policy documents found", extra={"event": "policies_missing"})
        db.commit()
    log.info("hiring policies loaded", extra={"event": "policies_loaded", "count": len(chunks)})


def search_policies(db: Session, question: str, limit: int = 5, sources: list[str] | None = None) -> list[PolicyChunk]:
    """The policy sections closest in meaning to the question. sources: only these documents (None = all)."""
    vector = embed_question(question)
    query = select(PolicyChunk)
    if sources:
        query = query.where(PolicyChunk.source.in_(sources))
    closest_first = query.order_by(PolicyChunk.embedding.cosine_distance(vector)).limit(limit)
    return list(db.scalars(closest_first))
