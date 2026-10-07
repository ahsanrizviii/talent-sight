import logging
import re
from functools import lru_cache
from pathlib import Path

from fastembed import TextEmbedding
from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import PolicyChunk

log = logging.getLogger("talentsight.knowledge")

MODEL_NAME = "BAAI/bge-small-en-v1.5"  
MODEL_DIR = "/opt/models"  
POLICY_FILE = Path(__file__).resolve().parent.parent / "knowledge" / "bjit-hiring-policies.pdf"

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


def load_policies() -> None:
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(PolicyChunk)):
            return
        if not POLICY_FILE.exists():
            log.warning("hiring policy file not found", extra={"event": "policies_missing"})
            return
        chunks = split_policy(read_pdf_text(POLICY_FILE))
        for chunk, vector in zip(chunks, embed_texts(chunks)):
            db.add(PolicyChunk(source=POLICY_FILE.name, text=chunk, embedding=vector))
        db.commit()
    log.info("hiring policies loaded", extra={"event": "policies_loaded"})


def search_policies(db: Session, question: str, limit: int = 5) -> list[PolicyChunk]:
    vector = embed_question(question)
    closest_first = select(PolicyChunk).order_by(PolicyChunk.embedding.cosine_distance(vector)).limit(limit)
    return list(db.scalars(closest_first))
