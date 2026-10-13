"""Live speech to text: the WebSockets that carry each speaker's microphone (Module 8).

Two doors, one per role, so the server always knows who is speaking (Q&A 4):
- the interviewer signs in with their login token, sent as the first message
  (a browser cannot put a login header on a WebSocket);
- the candidate's private invite link is their key, exactly like their other pages.
The speaker label comes from that key, never from anything the browser says.
"""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.db import SessionLocal
from app.deps import interviewer_from_token, open_session_for_invite
from app.models import InterviewSession
from app.transcription import SpeakerChannel

router = APIRouter(prefix="/api/ws", tags=["transcripts"])

SIGN_IN_SECONDS = 10  # the interviewer's first message must arrive within this time

# Close codes the browser understands (4000-4999 are free for applications).
NOT_SIGNED_IN = 4401
NOT_FOUND = 4404


# ---------- Who may send audio (plain database checks, run outside the event loop) ----------


def interviewer_may_speak(token: str | None, session_id: int) -> int | None:
    """None if the interviewer may send audio to this interview, otherwise the close code."""
    with SessionLocal() as db:
        if not token or interviewer_from_token(db, token) is None:
            return NOT_SIGNED_IN
        session = db.get(InterviewSession, session_id)
        if session is None or session.status == "ended":
            return NOT_FOUND
    return None


def session_of_invite(invite_token: str) -> int | None:
    """The interview id behind a valid invite link, or None."""
    with SessionLocal() as db:
        session = open_session_for_invite(db, invite_token)
        return session.id if session else None


async def read_sign_in(websocket: WebSocket) -> str | None:
    """The first message must be {"token": "<login token>"}."""
    try:
        message = await asyncio.wait_for(websocket.receive_text(), SIGN_IN_SECONDS)
        return str(json.loads(message)["token"])
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, KeyError, TypeError):
        return None


# ---------- The two doors ----------


@router.websocket("/interviews/{session_id}/audio")
async def interviewer_audio(websocket: WebSocket, session_id: int):
    await websocket.accept()  # accept first, so a refusal can carry a close code the browser can read
    refused = await run_in_threadpool(interviewer_may_speak, await read_sign_in(websocket), session_id)
    if refused:
        await websocket.close(code=refused)
        return
    await receive_audio(websocket, session_id, "interviewer")


@router.websocket("/invite/{invite_token}/audio")
async def candidate_audio(websocket: WebSocket, invite_token: str):
    await websocket.accept()
    session_id = await run_in_threadpool(session_of_invite, invite_token)
    if session_id is None:
        await websocket.close(code=NOT_FOUND)
        return
    await receive_audio(websocket, session_id, "candidate")


async def receive_audio(websocket: WebSocket, session_id: int, speaker: str) -> None:
    """Passes every audio piece to the speaker's channel until the browser disconnects."""

    async def tell(message: dict) -> None:
        """Sends a short status message to this browser. A browser that has just left is simply skipped."""
        try:
            await websocket.send_json(message)
        except Exception:
            pass

    channel = SpeakerChannel(session_id, speaker, tell)
    try:
        await websocket.send_json({"type": "ready"})
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes"):
                await channel.add_audio(message["bytes"])
            elif message.get("text") and '"ping"' in message["text"]:
                # Messages are handled in order, so "pong" also means: all audio before it was handled.
                await tell({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await channel.close()