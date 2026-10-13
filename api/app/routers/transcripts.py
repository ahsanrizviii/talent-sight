"""Live speech to text (Module 8): the WebSockets that carry each speaker's microphone,
and the transcript itself for the interviewer.

Two doors, one per role, so the server always knows who is speaking (Q&A 4):
- the interviewer signs in with their login token, sent as the first message
  (a browser cannot put a login header on a WebSocket);
- the candidate's private invite link is their key, exactly like their other pages.
The speaker label comes from that key, never from anything the browser says.
"""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app import transcript_feed
from app.db import SessionLocal, get_db
from app.deps import current_interviewer, interviewer_from_token, open_session_for_invite
from app.models import InterviewSession, TranscriptSegment
from app.transcription import SpeakerChannel

router = APIRouter(prefix="/api/ws", tags=["transcripts"])
# Normal (non-WebSocket) endpoints: interviewers only. The candidate never sees the transcript (N9).
pages = APIRouter(prefix="/api", tags=["transcripts"], dependencies=[Depends(current_interviewer)])

SIGN_IN_SECONDS = 10  # the interviewer's first message must arrive within this time

# Close codes the browser understands (4000-4999 are free for applications).
# Two more are in transcription.py: REPLACED (4409) and INTERVIEW_ENDED (4410).
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

def interviewer_may_read(token: str | None, session_id: int) -> int | None:
    """None if the interviewer may follow this interview's transcript, otherwise the close code."""
    with SessionLocal() as db:
        if not token or interviewer_from_token(db, token) is None:
            return NOT_SIGNED_IN
        if db.get(InterviewSession, session_id) is None:
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

    async def hang_up(code: int) -> None:
        """Closes this connection from the server side (replaced by a newer one, or the interview ended)."""
        try:
            await websocket.close(code=code)
        except Exception:
            pass

    channel = SpeakerChannel(session_id, speaker, tell, hang_up)
    try:
        await channel.join()
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




# ---------- The saved transcript (Task 8.2.1) ----------


class SegmentOut(BaseModel):
    id: int
    speaker: str  # interviewer | candidate
    text: str
    start_ms: int  # milliseconds since the interview started (Q&A 31)
    end_ms: int


class TranscriptOut(BaseModel):
    session_id: int
    status: str  # scheduled | live | ended
    segments: list[SegmentOut]


def saved_segments(db: Session, session_id: int) -> list[SegmentOut]:
    """Everything said so far, in time order. Overlapping speech stays as two entries (Q&A 36)."""
    rows = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.session_id == session_id)
        .order_by(TranscriptSegment.start_ms, TranscriptSegment.id)
    )
    return [
        SegmentOut(id=row.id, speaker=row.speaker, text=row.text, start_ms=row.start_ms, end_ms=row.end_ms)
        for row in rows
    ]


@pages.get("/interviews/{session_id}/transcript", response_model=TranscriptOut)
def get_transcript(session_id: int, db: Session = Depends(get_db)):
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Interview not found.")
    return TranscriptOut(session_id=session.id, status=session.status, segments=saved_segments(db, session.id))




def transcript_so_far(session_id: int) -> dict:
    with SessionLocal() as db:
        session = db.get(InterviewSession, session_id)
        segments = saved_segments(db, session_id)
        return {"status": session.status, "segments": [segment.model_dump() for segment in segments]}


# ---------- The live transcript for the interviewer's room page (Task 8.2.2) ----------


@router.websocket("/interviews/{session_id}/transcript")
async def live_transcript(websocket: WebSocket, session_id: int):
    """First everything said so far, then every new line as it happens. Interviewers only (N9)."""
    await websocket.accept()
    refused = await run_in_threadpool(interviewer_may_read, await read_sign_in(websocket), session_id)
    if refused:
        await websocket.close(code=refused)
        return

    # Listen first, then read the saved lines: a line saved in between arrives twice (the page keeps
    # one copy, by id) instead of not at all.
    queue = transcript_feed.subscribe(session_id)
    leaving = asyncio.create_task(wait_until_gone(websocket, queue))
    try:
        await websocket.send_json({"type": "history", **await run_in_threadpool(transcript_so_far, session_id)})
        while True:
            next_message = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({next_message, leaving}, return_when=asyncio.FIRST_COMPLETED)
            if leaving in done:
                next_message.cancel()
                break
            await websocket.send_json(next_message.result())
    except (WebSocketDisconnect, RuntimeError):
        pass  # the page closed while we were sending
    finally:
        leaving.cancel()
        transcript_feed.unsubscribe(session_id, queue)


async def wait_until_gone(websocket: WebSocket, queue: asyncio.Queue) -> None:
    """Reads what the page sends (only keep-alive pings) and returns when it disconnects."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        if message.get("text") and '"ping"' in message["text"]:
            queue.put_nowait({"type": "pong"})  # answered through the queue, so only one task sends