"""Keeping the "Write a job with AI" chats (UI refresh).

Every job written with the AI started as a conversation. The team asked for that conversation
to stay readable afterwards: what the recruiter asked for, what the AI asked back, and which
job it became. This file writes that record and reads it again.

It never changes how the agent works. If writing the record fails, the chat carries on.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JdChat

log = logging.getLogger("talentsight")

RECRUITER = "recruiter"
ASSISTANT = "assistant"


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def short_title(text: str, limit: int = 70) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1].rstrip() + "…"


def line(role: str, text: str) -> dict:
    return {"role": role, "text": " ".join(text.split()) if role == RECRUITER else text, "at": now_text()}


def start(db: Session, thread_id: str, brief: str, state) -> None:
    """Writes the first two lines: the brief, and whatever the AI answered."""
    chat = JdChat(
        thread_id=thread_id,
        title=short_title(brief),
        brief=brief,
        status=state.status,
        messages=[line(RECRUITER, brief)],
    )
    db.add(chat)
    add_answer(chat, state)
    db.commit()


def add_reply(db: Session, thread_id: str, said: str, state) -> None:
    """Writes what the recruiter replied, then what the AI answered."""
    chat = db.scalar(select(JdChat).where(JdChat.thread_id == thread_id))
    if chat is None:
        return  # a chat from before this record existed: nothing to add to
    chat.messages = [*chat.messages, line(RECRUITER, said)]
    add_answer(chat, state)
    db.commit()


def add_answer(chat: JdChat, state) -> None:
    """Turns the agent's state into one readable line and updates the chat's own fields."""
    chat.status = state.status
    chat.updated_at = datetime.now(timezone.utc)

    if state.status == "failed":
        text = state.message or "The AI could not finish this job post."
    elif state.kind == "questions":
        text = "I need a few details:\n" + "\n".join(f"• {question}" for question in state.questions)
    elif state.kind == "draft":
        draft = state.draft or {}
        chat.title = draft.get("title") or chat.title
        skills = ", ".join(draft.get("required_skills", []))
        text = f"Here is a draft for {draft.get('title', 'the role')}.\nRequired skills: {skills}"
    else:
        chat.job_id = state.job_id
        text = "Saved the job profile" + (" and posted it on the blog." if state.blog_url else ".")

    chat.messages = [*chat.messages, line(ASSISTANT, text)]


def listing(db: Session, job_id: int | None = None) -> list[JdChat]:
    query = select(JdChat).order_by(JdChat.updated_at.desc())
    if job_id is not None:
        query = query.where(JdChat.job_id == job_id)
    return list(db.scalars(query).all())


def one(db: Session, thread_id: str) -> JdChat | None:
    return db.scalar(select(JdChat).where(JdChat.thread_id == thread_id))
