import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_interviewer
from app.models import Interviewer
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("talentsight.auth")


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class Me(BaseModel):
    id: int
    email: str
    role: str = "interviewer"


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
def me(interviewer: Interviewer = Depends(current_interviewer)):
    """Who am I? The frontend calls this to check the saved token still works."""
    return Me(id=interviewer.id, email=interviewer.email)