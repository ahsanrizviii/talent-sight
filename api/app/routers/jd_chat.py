import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import jd_history
from app.agents.jd_agent import get_jd_agent
from app.db import get_db
from app.deps import current_interviewer

router = APIRouter(prefix="/api/jd-chat", tags=["jd chat"], dependencies=[Depends(current_interviewer)])


class StartChat(BaseModel):
    brief: str = Field(min_length=10, max_length=4000)


class ChatReply(BaseModel):
    text: str = Field(default="", max_length=4000)
    approve: bool = False


class ChatState(BaseModel):
    thread_id: str
    status: str
    kind: str | None = None
    questions: list[str] = []
    draft: dict | None = None
    policies: list[str] = []  # the company policy paragraphs found by RAG, shown with the draft
    job_id: int | None = None
    slug: str | None = None
    blog_url: str | None = None
    message: str = ""


class ChatMessage(BaseModel):
    role: str  # recruiter | assistant
    text: str
    at: str


class ChatSummary(BaseModel):
    """One line in the history list."""

    thread_id: str
    title: str
    status: str
    job_id: int | None
    created_at: datetime
    updated_at: datetime
    messages: int


class ChatHistory(ChatSummary):
    brief: str
    lines: list[ChatMessage]


def chat_state(thread_id: str) -> ChatState:
    snapshot = get_jd_agent().get_state({"configurable": {"thread_id": thread_id}})
    values = snapshot.values

    if not values:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found.")

    if values.get("error"):
        return ChatState(thread_id=thread_id, status="failed", message=values["error"])

    if snapshot.interrupts:
        waiting_for = snapshot.interrupts[0].value
        return ChatState(
            thread_id=thread_id,
            status="waiting",
            kind=waiting_for["kind"],
            questions=waiting_for.get("questions", []),
            draft=waiting_for.get("draft"),
            policies=values.get("policies") or [],
        )
    return ChatState(
        thread_id=thread_id,
        status="done",
        job_id=values.get("job_id"),
        slug=values.get("slug"),
        blog_url=values.get("blog_url") or None,
    )


@router.post("", response_model=ChatState)
def start_chat(body: StartChat, db: Session = Depends(get_db)):
    thread_id = str(uuid.uuid4())
    get_jd_agent().invoke({"brief": body.brief}, {"configurable": {"thread_id": thread_id}})
    state = chat_state(thread_id)
    jd_history.start(db, thread_id, body.brief, state)
    return state


@router.post("/{thread_id}/reply", response_model=ChatState)
def reply(thread_id: str, body: ChatReply, db: Session = Depends(get_db)):
    if chat_state(thread_id).status != "waiting":
        raise HTTPException(status.HTTP_409_CONFLICT, "This chat is already finished. Please start a new one.")

    get_jd_agent().invoke(Command(resume=body.model_dump()), {"configurable": {"thread_id": thread_id}})
    state = chat_state(thread_id)
    jd_history.add_reply(db, thread_id, body.text.strip() or ("Approved the draft." if body.approve else ""), state)
    return state


@router.get("", response_model=list[ChatSummary])
def list_chats(job_id: int | None = None, db: Session = Depends(get_db)):
    """Every chat, newest first. With job_id, only the chats that wrote that job."""
    return [
        ChatSummary(
            thread_id=chat.thread_id,
            title=chat.title,
            status=chat.status,
            job_id=chat.job_id,
            created_at=chat.created_at,
            updated_at=chat.updated_at,
            messages=len(chat.messages),
        )
        for chat in jd_history.listing(db, job_id)
    ]


@router.get("/{thread_id}/history", response_model=ChatHistory)
def chat_history(thread_id: str, db: Session = Depends(get_db)):
    """The whole conversation, as it was said."""
    chat = jd_history.one(db, thread_id)
    if chat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That chat was not kept.")
    return ChatHistory(
        thread_id=chat.thread_id,
        title=chat.title,
        status=chat.status,
        job_id=chat.job_id,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=len(chat.messages),
        brief=chat.brief,
        lines=[ChatMessage(**message) for message in chat.messages],
    )


@router.get("/{thread_id}", response_model=ChatState)
def get_chat(thread_id: str):
    return chat_state(thread_id)
