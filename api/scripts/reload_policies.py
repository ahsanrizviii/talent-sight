from sqlalchemy import delete

from app.db import SessionLocal
from app.knowledge import load_policies
from app.models import PolicyChunk

with SessionLocal() as db:
    db.execute(delete(PolicyChunk))
    db.commit()

load_policies()

print("Policies reloaded.")