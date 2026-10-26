"""The company's name and contact, used in every e-mail and calendar entry.

Filled in once, in the sign-up form of the first person who signs up (routers/auth.py).
"""

from email.utils import parseaddr

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import company_profile, invite_mail
from app.db import get_db
from app.deps import current_interviewer
from app.models import CompanyProfile

router = APIRouter(prefix="/api/company", tags=["company"], dependencies=[Depends(current_interviewer)])


class CompanyIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=120)
    sender_name: str = Field(default="", max_length=120)
    contact_name: str = Field(default="", max_length=120)
    contact_email: str = Field(default="", max_length=255)

class CompanyOut(CompanyIn):
    sending_address: str  # the mailbox e-mails really come from (SMTP_USER): set in .env, not here
    from_line: str  # exactly what candidates see in "From"


def to_out(db: Session, details: company_profile.Company) -> CompanyOut:
    server = invite_mail.mail_server()
    row = db.get(CompanyProfile, 1)
    return CompanyOut(
        company_name=details.name,
        sender_name=row.sender_name if row else "",  # as typed: empty means "<company> Hiring"
        contact_name=details.contact_name,
        contact_email=details.contact_email,
        sending_address=parseaddr(invite_mail.sender(server))[1] if server else "",
        from_line=invite_mail.sender(server) if server else "",
    )


@router.get("", response_model=CompanyOut)
def read_company(db: Session = Depends(get_db)):
    return to_out(db, company_profile.current(db))


@router.put("", response_model=CompanyOut)
def save_company(body: CompanyIn, db: Session = Depends(get_db)):
    try:
        saved = company_profile.save(db, body.company_name, body.sender_name, body.contact_name, body.contact_email)
    except ValueError as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem))
    return to_out(db, saved)
