from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Interviewer, InterviewSession
from app.security import read_access_token

bearer = HTTPBearer(auto_error=False)

def current_interviewer(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Interviewer:
    
    not_logged_in = HTTPException(status.HTTP_401_UNAUTHORIZED, "Please log in.")

    if credentials is None:
        raise not_logged_in

    try:
        payload = read_access_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise not_logged_in

    if payload.get("role") != "interviewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only interviewers can do this.")

    interviewer = db.get(Interviewer, int(payload["sub"]))
    if interviewer is None:
        raise not_logged_in

    return interviewer


def interviewer_from_token(db: Session, token: str) -> Interviewer | None:
    """The same check as current_interviewer, for WebSockets (Module 8).

    A browser cannot put a login header on a WebSocket, so the token arrives in the first
    message instead. Returns None for a missing, expired or non-interviewer token.
    """
    try:
        payload = read_access_token(token)
    except jwt.InvalidTokenError:
        return None
    if payload.get("role") != "interviewer":
        return None
    return db.get(Interviewer, int(payload["sub"]))


def open_session_for_invite(db: Session, invite_token: str) -> InterviewSession | None:
    """The interview behind an invite link, or None if the link is unknown, ended or expired."""
    session = db.scalar(
        select(InterviewSession).where(InterviewSession.invite_token == invite_token)
    )
    if (
        session is None
        or session.status == "ended"
        or session.invite_expires_at < datetime.now(timezone.utc)
    ):
        return None
    return session


def session_from_invite(
    invite_token: str,
    db: Session = Depends(get_db),
) -> InterviewSession:

    session = open_session_for_invite(db, invite_token)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite link is not valid.")
    return session