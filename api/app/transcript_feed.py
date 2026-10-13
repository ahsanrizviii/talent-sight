"""Pushes the transcript to the interviewer's room page while the interview runs (Module 8, Task 8.2.2).

Only the interviewer's page subscribes: routers/transcripts.py checks the login first.
The candidate's page never receives the transcript (N9).

Messages:
  {"type": "partial", "speaker": ..., "text": ..., "start_ms": ...}   words still being spoken (not saved)
  {"type": "segment", "segment": {id, speaker, text, start_ms, end_ms}} a finished, saved turn
  {"type": "ended"}                                                    the interviewer ended the interview
"""

import asyncio

# For each interview, the open interviewer pages: (their event loop, their message queue)
listeners: dict[int, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}


def subscribe(session_id: int) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    listeners.setdefault(session_id, set()).add((asyncio.get_running_loop(), queue))
    return queue


def unsubscribe(session_id: int, queue: asyncio.Queue) -> None:
    pages = listeners.get(session_id, set())
    for entry in [entry for entry in pages if entry[1] is queue]:
        pages.discard(entry)
    if not pages:
        listeners.pop(session_id, None)


def publish(session_id: int, message: dict) -> None:
    """Sends a message to every interviewer page of this interview. Safe to call from any thread."""
    for loop, queue in list(listeners.get(session_id, ())):
        try:
            loop.call_soon_threadsafe(queue.put_nowait, message)
        except RuntimeError:  # that page's event loop has stopped
            unsubscribe(session_id, queue)