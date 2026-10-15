"""Who the company is: the name and contact that appear in e-mails, calendars and the careers page.

TalentSight is sold to many companies, so none of this is written into the code. It is kept in the
company_profile table and edited on the Settings page. Anything left empty falls back to .env.
"""

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import CompanyProfile
from app.settings import settings

EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Company:
    name: str
    sender_name: str  # "From: <sender_name> <mailbox>"
    contact_name: str
    contact_email: str  # Reply-To, and "For any query" in the e-mail; "" = not given


def one_line(text: str) -> str:
    """Collapses spaces and line breaks, so nothing can sneak a new line into an e-mail header."""
    return " ".join(text.split())


def _from_row(row: CompanyProfile | None) -> Company:
    name = one_line(row.company_name if row and row.company_name else "") or one_line(settings.company_name)
    return Company(
        name=name,
        sender_name=one_line(row.sender_name if row else "") or f"{name} Hiring",
        contact_name=one_line(row.contact_name if row else ""),
        contact_email=(row.contact_email.strip() if row else ""),
    )


def current(db: Session | None = None) -> Company:
    """The company as it is now. Opens its own database session when none is given."""
    if db is not None:
        return _from_row(db.get(CompanyProfile, 1))
    with SessionLocal() as own:
        return _from_row(own.get(CompanyProfile, 1))


def save(db: Session, company_name: str, sender_name: str, contact_name: str, contact_email: str) -> Company:
    """Stores the company details. Raises ValueError with a readable message when something is wrong."""
    contact_email = contact_email.strip()
    if not one_line(company_name):
        raise ValueError("Please enter the company name.")
    if contact_email and not EMAIL_SHAPE.match(contact_email):
        raise ValueError("The contact e-mail address looks wrong.")
    row = db.get(CompanyProfile, 1) or CompanyProfile(id=1)
    row.company_name = one_line(company_name)[:120]
    row.sender_name = one_line(sender_name)[:120]
    row.contact_name = one_line(contact_name)[:120]
    row.contact_email = contact_email[:255]
    db.add(row)
    db.commit()
    return _from_row(row)
