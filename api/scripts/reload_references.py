"""Embeds the skills reference documents again (Module 9).

Run it after changing the PDF in api/knowledge/skills/ and rebuilding the image:
    docker compose exec api python -m scripts.reload_references
"""

from sqlalchemy import delete

from app.db import SessionLocal
from app.models import ReferenceChunk
from app.references import load_references

with SessionLocal() as db:
    db.execute(delete(ReferenceChunk))
    db.commit()

load_references()

print("Skills references reloaded.")