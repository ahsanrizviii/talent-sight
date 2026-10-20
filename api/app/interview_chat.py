"""The interviewer's question chat for one interview (Module 13).

Answered straight away (a few seconds), not in the background: the interviewer is waiting for it
during the interview. The chat history is kept per interview, so a follow-up message makes sense,
and it is deleted with the interview and the candidate (N19). Logs never contain what was typed (N22).
"""

import logging
import time

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.chat_agent import HISTORY, get_chat_agent
from app.interview_context import context_for
from app.models import InterviewChatMessage, InterviewSession

log = logging.getLogger("talentsight.interview_chat")

CRASHED = "Something went wrong while writing the answer. Please try again."


def messages_of(db: Session, session_id: int) -> list[InterviewChatMessage]:
    return list(db.scalars(
        select(InterviewChatMessage)
        .where(InterviewChatMessage.session_id == session_id)
        .order_by(InterviewChatMessage.id)
    ))


def answer(db: Session, session: InterviewSession, message: str) -> tuple[InterviewChatMessage, InterviewChatMessage]:
    """Runs the Question Chat Agent and saves the question and the answer together.

    When the AI is not available nothing is saved and a clear error is returned (N6), so the
    interviewer can simply send the message again.
    """
    started = time.monotonic()
    earlier = messages_of(db, session.id)[-HISTORY:]
    state = {
        **context_for(db, session),
        "message": message,
        "history": [{"role": m.role, "text": m.text, "suggestions": m.suggestions or []} for m in earlier],
    }
    try:
        final = get_chat_agent().invoke(state)
    except Exception as crash:  # an unexpected bug must not show a raw error
        log.error("chat crashed", exc_info=crash, extra={"event": "chat_crash", "session_id": session.id})
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, CRASHED) from crash
    if final.get("error"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, final["error"])

    asked = InterviewChatMessage(session_id=session.id, role="interviewer", text=message, suggestions=[])
    replied = InterviewChatMessage(session_id=session.id, role="assistant", text=final["reply"], suggestions=final["suggestions"])
    db.add_all([asked, replied])
    db.commit()
    db.refresh(asked)
    db.refresh(replied)
    log.info(
        "chat answered",
        extra={
            "event": "chat_answered",
            "session_id": session.id,
            "count": len(final["suggestions"]),
            "seconds": round(time.monotonic() - started, 1),
        },
    )
    return asked, replied