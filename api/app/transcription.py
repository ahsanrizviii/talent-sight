"""Live speech to text for the interview (Module 8).

Each person's browser sends ONLY its own microphone, over its own WebSocket (routers/transcripts.py).
So every piece of audio already belongs to one known speaker, and no AI has to guess who spoke (Q&A 4).

One SpeakerChannel = one speaker in one interview. The audio only passes through memory:
it is never written to a file or to the database (Q&A 7, N16).
"""

import logging

log = logging.getLogger("talentsight")

# The browser sends 16 000 samples a second, one channel, 16 bits (2 bytes) per sample.
SAMPLE_RATE = 16_000
BYTES_PER_MS = SAMPLE_RATE * 2 // 1000  # 32 bytes = 1 millisecond of audio

# The speech service accepts pieces of 50 ms to 1 s. The browser sends 100 ms pieces.
MIN_CHUNK_MS = 50
MAX_CHUNK_MS = 1000


def chunk_ms(chunk: bytes) -> int | None:
    """How many milliseconds of audio a piece holds, or None if it is not a valid piece."""
    if len(chunk) % 2:  # half a sample: not 16-bit audio
        return None
    ms = len(chunk) // BYTES_PER_MS
    if not MIN_CHUNK_MS <= ms <= MAX_CHUNK_MS:
        return None
    return ms


class SpeakerChannel:
    """The audio of one speaker in one interview, from the moment their browser connects."""

    def __init__(self, session_id: int, speaker: str):
        self.session_id = session_id
        self.speaker = speaker  # "interviewer" or "candidate", decided by the server
        self.audio_ms = 0  # how much audio has arrived; only a number, the audio itself is not kept
        log.info(
            "audio stream opened",
            extra={"event": "audio_opened", "session_id": session_id, "speaker": speaker},
        )

    async def add_audio(self, chunk: bytes) -> None:
        ms = chunk_ms(chunk)
        if ms is None:
            return  # a broken piece is skipped; the next one is fine again
        self.audio_ms += ms

    async def close(self) -> None:
        log.info(
            "audio stream closed",
            extra={
                "event": "audio_closed",
                "session_id": self.session_id,
                "speaker": self.speaker,
                "seconds": round(self.audio_ms / 1000, 1),
            },
        )