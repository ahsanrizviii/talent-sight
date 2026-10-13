
import asyncio
import bisect
import logging
import time
from typing import Awaitable, Callable

from app import speech, transcript_feed
from app.db import SessionLocal
from app.models import InterviewSession, TranscriptSegment
from app.speech import SAMPLE_RATE, Heard

log = logging.getLogger("talentsight")

BYTES_PER_MS = SAMPLE_RATE * 2 // 1000  # 16-bit mono: 32 bytes = 1 millisecond of audio

# The speech service accepts pieces of 50 ms to 1 s. The browser sends 100 ms pieces.
MIN_CHUNK_MS = 50
MAX_CHUNK_MS = 1000

Tell = Callable[[dict], Awaitable[None]]  # sends a short message back to the speaker's browser
HangUp = Callable[[int], Awaitable[None]]  # closes the speaker's WebSocket with a close code


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

def save_segment(session_id: int, speaker: str, text: str, start_ms: int, end_ms: int, segment_id: int | None) -> int:
    """Saves one finished turn and returns its id. With segment_id, that row is updated instead:
    the speech service sometimes sends the same turn again, with punctuation and capitals added."""
    with SessionLocal() as db:
        segment = db.get(TranscriptSegment, segment_id) if segment_id else None
        if segment is None:
            segment = TranscriptSegment(session_id=session_id, speaker=speaker)
            db.add(segment)
        segment.text = text
        segment.start_ms = start_ms
        segment.end_ms = end_ms
        db.commit()
        return segment.id

# ---------- Who is connected right now ----------

# Close codes for the browser (4000-4999 are free for applications).
REPLACED = 4409  # the same person connected again (a refresh, a second tab): the newer connection wins
INTERVIEW_ENDED = 4410  # the interviewer ended the interview

# One channel per speaker per interview: {(interview id, "interviewer" or "candidate"): channel}
live_channels: dict[tuple[int, str], "SpeakerChannel"] = {}

# After a failed start, wait this long before trying again (seconds); the last value repeats.
RETRY_WAIT_SECONDS = (1, 2, 4, 8, 10)


def end_interview(session_id: int) -> None:
    """The interviewer ended the interview: stop listening to everyone in it.

    Called from the normal (non-async) end endpoint, so it hands the work to each channel's
    event loop and does not wait. Each channel still finishes its last sentence before closing.
    """
    transcript_feed.publish(session_id, {"type": "ended"})
    for (channel_session, _), channel in list(live_channels.items()):
        if channel_session == session_id:
            try:
                asyncio.run_coroutine_threadsafe(channel.hang_up(INTERVIEW_ENDED), channel.loop)
            except RuntimeError:  # that event loop has already stopped
                live_channels.pop((channel.session_id, channel.speaker), None)


class SpeakerChannel:
    """The audio of one speaker in one interview, from the moment their browser connects."""

    def __init__(self, session_id: int, speaker: str, tell: Tell, hang_up: HangUp):
        self.session_id = session_id
        self.speaker = speaker  # "interviewer" or "candidate", decided by the server
        self.tell = tell
        self.hang_up = hang_up
        self.loop = asyncio.get_running_loop()
        self.stream: speech.SpeechStream | None = None
        self.timeline = Timeline()
        self.not_set_up = False  # a setting is missing: no point trying again
        self.failures = 0  # failed starts in a row
        self.retry_at = 0.0  # after a failure, do not try again before this time (seconds)
        self.streams_opened = 0
        self.started_ms: int | None = None  # the interview's start, the zero point of every timestamp
        self.audio_ms = 0  # how much audio has arrived; only a number, the audio itself is not kept
        self.saved_turns: dict[int, int] = {}  # turn number in the current stream -> saved segment id

    async def join(self) -> None:
        """Becomes THE channel of this speaker. An older connection of the same person is closed."""
        key = (self.session_id, self.speaker)
        older = live_channels.get(key)
        live_channels[key] = self
        log.info(
            "audio stream opened",
            extra={"event": "audio_opened", "session_id": self.session_id, "speaker": self.speaker},
        )
        if older is not None:
            await older.hang_up(REPLACED)

    async def add_audio(self, chunk: bytes) -> None:
        ms = chunk_ms(chunk)
        if ms is None:
            return  # a broken piece is skipped; the next one is fine again
        if self.stream is None and not self.not_set_up and time.monotonic() >= self.retry_at:
            await self.open_stream()
        if self.stream is None:
            return  # no speech service at the moment: this piece is dropped, the call goes on
        self.timeline.add(ms, now_ms())
        self.audio_ms += ms
        await self.stream.send(chunk)

    async def open_stream(self) -> None:
        """Opens a speech stream: the first one, or a new one after the last one closed (Task 8.1.3)."""
        stream = speech.SpeechStream(self.heard, self.stream_closed)
        try:
            await stream.start()
        except speech.SpeechError as error:
            self.failures += 1
            self.not_set_up = isinstance(error, speech.SpeechNotSetUp)
            wait = RETRY_WAIT_SECONDS[min(self.failures, len(RETRY_WAIT_SECONDS)) - 1]
            self.retry_at = time.monotonic() + wait
            log.warning(
                f"speech stream could not start: {error}" + ("" if self.not_set_up else f" (trying again in {wait} s)"),
                extra={"event": "speech_unavailable", "session_id": self.session_id, "speaker": self.speaker},
            )
            if self.failures == 1:  # tell the browser once, not on every retry
                await self.tell({"type": "status", "state": "unavailable"})
            return
        self.stream = stream
        self.timeline = Timeline()  # every new stream counts its audio from zero; the clock keeps the times continuous
        self.saved_turns = {}  # ...and numbers its turns from zero
        self.failures = 0
        self.streams_opened += 1
        if self.streams_opened > 1:
            log.info(
                "speech stream restarted",
                extra={"event": "speech_restarted", "session_id": self.session_id, "speaker": self.speaker, "count": self.streams_opened},
            )
        await self.tell({"type": "status", "state": "listening"})

    async def stream_closed(self, reason: str) -> None:
        """The speech service ended the stream by itself (time limit, network, error).

        Nothing is lost: every final turn is already handled. The next audio piece opens a new stream.
        """
        self.stream = None
        self.show_preview("")
        log.warning(
            f"speech stream closed: {reason}",
            extra={"event": "speech_closed", "session_id": self.session_id, "speaker": self.speaker},
        )

    async def heard(self, heard: Heard) -> None:
        start_ms, end_ms = await self.interview_times(heard)
        if not heard.final:
            # Words still being spoken: shown live to the interviewer (Task 8.2.2), never saved.
            self.show_preview(heard.text, start_ms)
            return
        # Saved at once (Task 8.2.1). Everything is transcribed, small talk too (Q&A 16).
        segment_id = await asyncio.to_thread(
            save_segment, self.session_id, self.speaker, heard.text, start_ms, end_ms, self.saved_turns.get(heard.turn)
        )
        self.saved_turns[heard.turn] = segment_id
        segment = {"id": segment_id, "speaker": self.speaker, "text": heard.text, "start_ms": start_ms, "end_ms": end_ms}
        transcript_feed.publish(self.session_id, {"type": "segment", "segment": segment})
        log.info(
            f"speech segment {start_ms}-{end_ms} ms",
            extra={
                "event": "speech_segment",
                "session_id": self.session_id,
                "speaker": self.speaker,
                "count": len(heard.text.split()),  # how many words; the words themselves are not logged
            },
        )

    def show_preview(self, text: str, start_ms: int = 0) -> None:
        """The grey 'still speaking' line on the interviewer's page. An empty text removes it."""
        message = {"type": "partial", "speaker": self.speaker, "text": text, "start_ms": start_ms}
        transcript_feed.publish(self.session_id, message)

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
        """The browser left (or was disconnected). Finishes the last sentence, then forgets this channel."""
        if live_channels.get((self.session_id, self.speaker)) is self:
            del live_channels[(self.session_id, self.speaker)]
        stream, self.stream = self.stream, None
        if stream is not None:
            await stream.stop()  # waits for the last words, so the end of a sentence is not lost
            self.show_preview("")
        log.info(
            "audio stream closed",
            extra={
                "event": "audio_closed",
                "session_id": self.session_id,
                "speaker": self.speaker,
                "seconds": round(self.audio_ms / 1000, 1),
            },
        )