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
    """Lets the request through only for a logged-in interviewer."""
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


def session_from_invite(
    invite_token: str,
    db: Session = Depends(get_db),
) -> InterviewSession:
    """Lets a candidate in only with a valid, unexpired invite token, and only to their own interview."""
    session = db.scalar(
        select(InterviewSession).where(InterviewSession.invite_token == invite_token)
    )
    if (
        session is None
        or session.status == "ended"
        or session.invite_expires_at < datetime.now(timezone.utc)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite link is not valid.")
    return session