import logging

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Interviewer
from app.security import hash_password
from app.settings import settings

log = logging.getLogger("talentsight.seed")


def seed_interviewer() -> None:

    email = settings.seed_interviewer_email.lower()

    with SessionLocal() as db:
        if db.scalar(select(Interviewer).where(Interviewer.email == email)):
            return
        db.add(
            Interviewer(
                email=email,
                password_hash=hash_password(settings.seed_interviewer_password),
            )
        )
        db.commit()

    log.info("interviewer account created", extra={"event": "seed_interviewer"})