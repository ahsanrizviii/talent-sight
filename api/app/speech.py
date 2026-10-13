"""The speech service: AssemblyAI streaming speech to text (Module 8, Task 8.1.2).

The WBS planned Google Speech-to-Text; AssemblyAI is used instead, because Google Cloud billing
needs a credit card (see the Module 8 story). This file is the ONLY place that knows about
AssemblyAI: the rest of the app, and the tests, only see plain `Heard` results.

One SpeechStream = one AssemblyAI session = one speaker. Audio goes in as 16 kHz, 16-bit pieces;
recognised words come back as "turns" (one sentence or so), first as a live preview and then final.
"""

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from assemblyai.streaming.v3 import (
    AsyncRealTimeTranscriber,
    Encoding,
    RealTimeError,
    RealTimeEvents,
    RealTimeParameters,
    RealTimeTranscriberOptions,
    TerminationEvent,
    TurnEvent,
)

from app.settings import settings

log = logging.getLogger("talentsight")

SAMPLE_RATE = 16_000  # what the browser sends: 16 000 samples a second, one channel, 16 bits
CONNECT_SECONDS = 5.0  # how long to wait for the speech service to answer
STOP_SECONDS = 5.0  # when stopping, how long to wait for the last words
LASTING_ERRORS = {4001, 4002, 4003}  # wrong key, no credit left, paid-only feature: retrying will not help


@dataclass
class Heard:
    """What the speech service recognised in one turn of speech."""

    turn: int  # the turn's number in this stream; the same turn can come again, improved
    text: str
    start_ms: int  # where the turn starts and ends in the audio sent to THIS stream
    end_ms: int
    final: bool  # True = the speaker finished the turn; False = a live preview while they speak


class SpeechError(Exception):
    """The speech service cannot be used right now. The message is safe to log (no audio, no words)."""


class SpeechNotSetUp(SpeechError):
    """A setting is missing or wrong, so trying again will not help until .env is fixed."""


OnHeard = Callable[[Heard], Awaitable[None]]
OnClosed = Callable[[str], Awaitable[None]]


class SpeechStream:
    """One streaming session with AssemblyAI.

    on_heard(heard) is called for every preview and every final turn.
    on_closed(reason) is called if the session ends by itself (network, time limit, service error);
    it is NOT called after our own stop().
    """

    def __init__(self, on_heard: OnHeard, on_closed: OnClosed):
        self.on_heard = on_heard
        self.on_closed = on_closed
        self.client: AsyncRealTimeTranscriber | None = None
        self.started = False
        self.stopping = False
        self.problem = ""
        self.problem_code: int | None = None

    async def start(self) -> None:
        """Opens the session. Raises SpeechError if that is not possible."""
        if not settings.assemblyai_api_key:
            raise SpeechNotSetUp("Speech-to-text is not set up: ASSEMBLYAI_API_KEY is empty.")
        try:
            parameters = RealTimeParameters(
                speech_model=settings.stt_model,
                encoding=Encoding.pcm_s16le,
                sample_rate=SAMPLE_RATE,
            )
        except ValueError:
            raise SpeechNotSetUp(f"STT_MODEL '{settings.stt_model}' is not a streaming model AssemblyAI knows.")

        self.client = AsyncRealTimeTranscriber(
            RealTimeTranscriberOptions(
                api_key=settings.assemblyai_api_key,
                api_host=settings.stt_host,
                connect_timeout=CONNECT_SECONDS,
                terminate_timeout=STOP_SECONDS,
            )
        )
        self.client.on(RealTimeEvents.Turn, self._turn)
        self.client.on(RealTimeEvents.Error, self._error)
        self.client.on(RealTimeEvents.Termination, self._terminated)

        # A refused or failed connection does not raise: the library reports it through _error.
        await self.client.connect(parameters)
        if self.problem:
            if self.problem_code in LASTING_ERRORS:
                raise SpeechNotSetUp(self.problem)
            raise SpeechError(self.problem)
        self.started = True

    async def send(self, chunk: bytes) -> None:
        if self.client is not None and self.started:
            await self.client.stream(chunk)  # silently ignored once the session has closed

    async def stop(self) -> None:
        """Ends the session politely: the service sends the last words first, then we close."""
        self.stopping = True
        if self.client is None:
            return
        try:
            await self.client.disconnect(terminate=True)
        except Exception as error:  # closing must never break the interview
            log.warning("speech stream did not close cleanly", exc_info=error, extra={"event": "speech_stop_failed"})

    # ---------- What AssemblyAI sends back ----------

    async def _turn(self, client, event: TurnEvent) -> None:
        text = event.transcript.strip()
        if not text:
            return
        start_ms = event.words[0].start if event.words else 0
        end_ms = event.words[-1].end if event.words else start_ms
        await self.on_heard(Heard(event.turn_order, text, start_ms, end_ms, event.end_of_turn))

    async def _error(self, client, error: RealTimeError) -> None:
        self.problem = f"{error} (code {error.code})" if error.code else str(error)
        self.problem_code = error.code
        if self.started and not self.stopping:
            await self.on_closed(self.problem)

    async def _terminated(self, client, event: TerminationEvent) -> None:
        if self.started and not self.stopping and not self.problem:
            await self.on_closed("The speech service ended the session.")