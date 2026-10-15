import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import accounts, company_profile
from app.db import get_db
from app.deps import current_interviewer
from app.models import Interviewer
from app.security import create_access_token, verify_password
from app.settings import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("talentsight.auth")


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class SignupRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)
    company_code: str = Field(default="", max_length=120)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class Me(BaseModel):
    id: int
    email: str
    name: str = ""
    company: str = ""
    role: str = "interviewer"


class SignInOptions(BaseModel):
    """What the login page needs before anyone has logged in."""

    company: str
    signup_open: bool
    email_domains: list[str] = []


@router.get("/options", response_model=SignInOptions)
def sign_in_options():
    """Public: tells the login page whether to offer the Create account tab."""
    return SignInOptions(
        company=company_profile.current().name,
        signup_open=accounts.signup_is_open(),
        email_domains=accounts.allowed_domains(),
    )


@router.post("/signup", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    """Opens an account for someone on the hiring team, then logs them straight in."""
    try:
        interviewer = accounts.create_account(db, body.full_name, body.email, body.password, body.company_code)
    except accounts.SignupRefused as refused:
        log.info("signup refused", extra={"event": "signup_refused"})
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(refused))

    log.info("account created", extra={"event": "signup_ok"})
    return LoginResponse(access_token=create_access_token(interviewer.id))


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    interviewer = db.scalar(
        select(Interviewer).where(Interviewer.email == body.email.strip().lower())
    )
    if interviewer is None or not verify_password(body.password, interviewer.password_hash):
        log.info("login failed", extra={"event": "login_failed"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong e-mail or password.")

    log.info("login ok", extra={"event": "login_ok"})
    return LoginResponse(access_token=create_access_token(interviewer.id))


@router.get("/me", response_model=Me)
def me(interviewer: Interviewer = Depends(current_interviewer), db: Session = Depends(get_db)):
    """Who am I? The frontend calls this to check the saved token still works."""
    return Me(
        id=interviewer.id,
        email=interviewer.email,
        name=accounts.display_name(db, interviewer),
        company=company_profile.current(db).name,
    )
