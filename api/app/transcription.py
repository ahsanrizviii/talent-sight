import asyncio
import bisect
import logging
import time
from typing import Awaitable, Callable

from app import speech
from app.db import SessionLocal
from app.models import InterviewSession
from app.speech import SAMPLE_RATE, Heard

log = logging.getLogger("talentsight")

BYTES_PER_MS = SAMPLE_RATE * 2 // 1000  # 16-bit mono: 32 bytes = 1 millisecond of audio

# The speech service accepts pieces of 50 ms to 1 s. The browser sends 100 ms pieces.
MIN_CHUNK_MS = 50
MAX_CHUNK_MS = 1000

Tell = Callable[[dict], Awaitable[None]]  # sends a short message back to the speaker's browser


def chunk_ms(chunk: bytes) -> int | None:
    """How many milliseconds of audio a piece holds, or None if it is not a valid piece."""
    if len(chunk) % 2:  # half a sample: not 16-bit audio
        return None
    ms = len(chunk) // BYTES_PER_MS
    if not MIN_CHUNK_MS <= ms <= MAX_CHUNK_MS:
        return None
    return ms


def now_ms() -> int:
    return int(time.time() * 1000)


class Timeline:
    """Turns a position in the audio we sent ("3.2 s into this stream") into a clock time.

    The speech service only counts the audio it received. When nothing is sent for a while
    (the speaker is muted, the network hiccups), the stream's count stops but the clock goes on.
    So whenever a piece arrives later than expected, we write down a new "anchor":
    "audio position X was heard at clock time Y". Both speakers then share the real clock.
    """

    GAP_MS = 400  # a piece this much later than expected means there was a pause

    def __init__(self):
        self.audio_ms = 0  # how much audio this stream has received so far
        self.anchors: list[tuple[int, int]] = []  # (audio position, clock time), oldest first

    def add(self, piece_ms: int, received_ms: int) -> None:
        """A piece of piece_ms milliseconds has just arrived (it ends now, so it started piece_ms ago)."""
        started_ms = received_ms - piece_ms
        if not self.anchors or started_ms - self.expected_clock() > self.GAP_MS:
            self.anchors.append((self.audio_ms, started_ms))
        self.audio_ms += piece_ms

    def expected_clock(self) -> int:
        audio, clock = self.anchors[-1]
        return clock + (self.audio_ms - audio)

    def clock_at(self, audio_ms: int) -> int:
        positions = [audio for audio, _ in self.anchors]
        audio, clock = self.anchors[max(0, bisect.bisect_right(positions, audio_ms) - 1)]
        return clock + (audio_ms - audio)


def interview_start_ms(session_id: int) -> int | None:
    """When the interview started (the interviewer's first join), as a clock time, or None if not yet."""
    with SessionLocal() as db:
        session = db.get(InterviewSession, session_id)
        if session is None or session.started_at is None:
            return None
        return int(session.started_at.timestamp() * 1000)


class SpeakerChannel:
    """The audio of one speaker in one interview, from the moment their browser connects."""

    def __init__(self, session_id: int, speaker: str, tell: Tell):
        self.session_id = session_id
        self.speaker = speaker  # "interviewer" or "candidate", decided by the server
        self.tell = tell
        self.stream: speech.SpeechStream | None = None
        self.timeline = Timeline()
        self.unavailable = False  # the speech service could not be used
        self.started_ms: int | None = None  # the interview's start, the zero point of every timestamp
        self.audio_ms = 0  # how much audio has arrived; only a number, the audio itself is not kept
        log.info(
            "audio stream opened",
            extra={"event": "audio_opened", "session_id": session_id, "speaker": speaker},
        )

    async def add_audio(self, chunk: bytes) -> None:
        ms = chunk_ms(chunk)
        if ms is None:
            return  # a broken piece is skipped; the next one is fine again
        if self.stream is None and not self.unavailable:
            await self.open_stream()
        if self.stream is None:
            return
        self.timeline.add(ms, now_ms())
        self.audio_ms += ms
        await self.stream.send(chunk)

    async def open_stream(self) -> None:
        stream = speech.SpeechStream(self.heard, self.stream_closed)
        try:
            await stream.start()
        except speech.SpeechError as error:
            self.unavailable = True
            log.warning(
                f"speech stream could not start: {error}",
                extra={"event": "speech_unavailable", "session_id": self.session_id, "speaker": self.speaker},
            )
            await self.tell({"type": "status", "state": "unavailable"})
            return
        self.stream = stream
        self.timeline = Timeline()  # every new stream counts its audio from zero
        await self.tell({"type": "status", "state": "listening"})

    async def stream_closed(self, reason: str) -> None:
        """The speech service ended the stream by itself."""
        self.stream = None
        self.unavailable = True
        log.warning(
            f"speech stream closed: {reason}",
            extra={"event": "speech_closed", "session_id": self.session_id, "speaker": self.speaker},
        )
        await self.tell({"type": "status", "state": "unavailable"})

    async def heard(self, heard: Heard) -> None:
        if not heard.final:
            return  # live previews are shown to the interviewer later (Task 8.2.2)
        start_ms, end_ms = await self.interview_times(heard)
        log.info(
            f"speech segment {start_ms}-{end_ms} ms",
            extra={
                "event": "speech_segment",
                "session_id": self.session_id,
                "speaker": self.speaker,
                "count": len(heard.text.split()),  # how many words; the words themselves are not logged
            },
        )

    async def interview_times(self, heard: Heard) -> tuple[int, int]:
        """Start and end of a turn in milliseconds since the interview started (Q&A 31)."""
        if self.started_ms is None:
            self.started_ms = await asyncio.to_thread(interview_start_ms, self.session_id)
        zero = self.started_ms if self.started_ms is not None else now_ms()
        if not self.timeline.anchors:  # nothing sent yet (only possible with a misbehaving service)
            return 0, 0
        start_ms = max(0, self.timeline.clock_at(heard.start_ms) - zero)
        end_ms = max(start_ms, self.timeline.clock_at(heard.end_ms) - zero)
        return start_ms, end_ms

    async def close(self) -> None:
        if self.stream is not None:
            await self.stream.stop()  # waits for the last words, so the end of a sentence is not lost
            self.stream = None
        log.info(
            "audio stream closed",
            extra={
                "event": "audio_closed",
                "session_id": self.session_id,
                "speaker": self.speaker,
                "seconds": round(self.audio_ms / 1000, 1),
            },
        )