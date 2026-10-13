"""Opening an account for a member of the hiring team (UI refresh).

TalentSight is one company's hiring tool, so sign-up is not open to the public. The company
sets SIGNUP_CODE in .env and gives that code to the people who are allowed in. An empty
SIGNUP_CODE switches sign-up off, and only the accounts created by hand can log in.
SIGNUP_EMAIL_DOMAINS can narrow it further to the company's own e-mail addresses.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Interviewer, InterviewerProfile
from app.security import hash_password
from app.settings import settings

EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8


class SignupRefused(Exception):
    """The sign-up cannot go ahead. The message is written for the person reading it."""


def signup_is_open() -> bool:
    return bool(settings.signup_code.strip())


def allowed_domains() -> list[str]:
    return [part.strip().lower() for part in settings.signup_email_domains.split(",") if part.strip()]


def check_code(code: str) -> None:
    if not signup_is_open():
        raise SignupRefused("New accounts are switched off. Ask your administrator to create one for you.")
    if code.strip() != settings.signup_code.strip():
        raise SignupRefused("That company code is not right. Ask your administrator for the current one.")


def check_email(email: str) -> str:
    address = email.strip().lower()
    if not EMAIL_SHAPE.match(address):
        raise SignupRefused("That e-mail address does not look right.")
    domains = allowed_domains()
    if domains and address.rsplit("@", 1)[-1] not in domains:
        raise SignupRefused(f"Use your work e-mail address ({', '.join('@' + d for d in domains)}).")
    return address


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise SignupRefused(f"Use at least {MIN_PASSWORD} characters for the password.")


def create_account(db: Session, full_name: str, email: str, password: str, code: str) -> Interviewer:
    """Makes the account and returns it. Raises SignupRefused with a readable reason instead."""
    check_code(code)
    address = check_email(email)
    check_password(password)

    if db.scalar(select(Interviewer).where(Interviewer.email == address)):
        raise SignupRefused("There is already an account with that e-mail address. Log in instead.")

    interviewer = Interviewer(email=address, password_hash=hash_password(password))
    db.add(interviewer)
    db.flush()  # gives the new row its id, so the profile can point at it
    db.add(InterviewerProfile(interviewer_id=interviewer.id, full_name=" ".join(full_name.split())))
    db.commit()
    db.refresh(interviewer)
    return interviewer


def display_name(db: Session, interviewer: Interviewer) -> str:
    """The name to greet someone by. Accounts made before sign-up existed fall back to their e-mail."""
    profile = db.scalar(
        select(InterviewerProfile).where(InterviewerProfile.interviewer_id == interviewer.id)
    )
    if profile and profile.full_name:
        return profile.full_name
    return interviewer.email.split("@", 1)[0]
