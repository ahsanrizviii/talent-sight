"""The Interview Assistant (question chat) in the interview room (Module 13).

Interviewers only. The candidate's page never calls it and never sees it (N9).
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app import interview_chat
from app.db import get_db
from app.deps import current_interviewer
from app.models import InterviewChatMessage
from app.routers.interviews import find_session

router = APIRouter(prefix="/api", tags=["interview chat"], dependencies=[Depends(current_interviewer)])

MAX_MESSAGE = 1000


class ChatIn(BaseModel):
    message: str = Field(max_length=MAX_MESSAGE)

    @field_validator("message")
    @classmethod
    def not_empty(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Type a message first.")
        return value


class ChatMessageOut(BaseModel):
    id: int
    role: str                # interviewer | assistant
    text: str
    suggestions: list[dict]  # [{"question", "why", "source": {"id", "kind", "text", "turn"?, "at"?, "speaker"?}}]
    created_at: datetime


class ChatTurnOut(BaseModel):
    question: ChatMessageOut
    answer: ChatMessageOut


def to_out(row: InterviewChatMessage) -> ChatMessageOut:
    return ChatMessageOut(id=row.id, role=row.role, text=row.text, suggestions=row.suggestions or [], created_at=row.created_at)


@router.get("/interviews/{session_id}/chat", response_model=list[ChatMessageOut])
def get_chat(session_id: int, db: Session = Depends(get_db)):
    """The whole chat of this interview, oldest first."""
    find_session(db, session_id)
    return [to_out(row) for row in interview_chat.messages_of(db, session_id)]


@router.post("/interviews/{session_id}/chat", response_model=ChatTurnOut)
def send_chat(session_id: int, body: ChatIn, db: Session = Depends(get_db)):
    """Answers the interviewer's message with a short reply and up to three suggested questions."""
    asked, replied = interview_chat.answer(db, find_session(db, session_id), body.message)
    return ChatTurnOut(question=to_out(asked), answer=to_out(replied))