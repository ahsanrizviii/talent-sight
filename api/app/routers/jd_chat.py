import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.agents.jd_agent import get_jd_agent
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
def start_chat(body: StartChat):
    thread_id = str(uuid.uuid4())
    get_jd_agent().invoke({"brief": body.brief}, {"configurable": {"thread_id": thread_id}})
    return chat_state(thread_id)


@router.post("/{thread_id}/reply", response_model=ChatState)
def reply(thread_id: str, body: ChatReply):
    if chat_state(thread_id).status != "waiting":
        raise HTTPException(status.HTTP_409_CONFLICT, "This chat is already finished. Please start a new one.")

    get_jd_agent().invoke(Command(resume=body.model_dump()), {"configurable": {"thread_id": thread_id}})
    return chat_state(thread_id)


@router.get("/{thread_id}", response_model=ChatState)
def get_chat(thread_id: str):
    return chat_state(thread_id)