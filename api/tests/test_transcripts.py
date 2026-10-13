"""Tests for live speech to text (Module 8). No real speech service and no real video server are used."""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import pytest
from assemblyai.streaming.v3 import RealTimeError, RealTimeEvents, TerminationEvent, TurnEvent, Word
from starlette.websockets import WebSocketDisconnect

from app import speech
from app.db import SessionLocal
from app.models import InterviewSession
from app.routers import transcripts
from app.settings import settings
from app.speech import Heard, SpeechError
from app.speech import SpeechStream as RealSpeechStream
from app.transcription import SpeakerChannel, Timeline, chunk_ms
from tests.fake_speech import FakeSpeechStream
from tests.test_interviews import fake_video_server, in_hours, make_candidate, schedule, stored_session  # noqa: F401


def audio(ms: int = 100) -> bytes:
    """ms milliseconds of 16 kHz, 16-bit audio (32 bytes per millisecond)."""
    return b"\x01\x00" * 16 * ms


def login_token(auth_headers) -> str:
    return auth_headers["Authorization"].split()[1]


def live_interview(client, auth_headers) -> tuple[int, str]:
    """An interview the interviewer has started. Returns its id and the candidate's invite token."""
    session = schedule(client, auth_headers, make_candidate(), in_hours(0.1)).json()
    client.post(f"/api/interviews/{session['id']}/join", headers=auth_headers)
    return session["id"], stored_session(session["id"]).invite_token


class WatchedChannel(SpeakerChannel):
    """The real SpeakerChannel, remembered so the tests can look inside it."""

    made: list["WatchedChannel"] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        WatchedChannel.made.append(self)


@pytest.fixture(autouse=True)
def fake_speech(monkeypatch):
    FakeSpeechStream.reset()
    monkeypatch.setattr(speech, "SpeechStream", FakeSpeechStream)
    return FakeSpeechStream


@pytest.fixture
def channels(monkeypatch):
    WatchedChannel.made = []
    monkeypatch.setattr(transcripts, "SpeakerChannel", WatchedChannel)
    return WatchedChannel.made


def closed_with(websocket) -> int:
    """Waits for the server to close the WebSocket and returns the close code."""
    with pytest.raises(WebSocketDisconnect) as closed:
        while True:
            websocket.receive_json()
    return closed.value.code


def settle(websocket) -> list[dict]:
    """Waits until the server has handled everything sent so far (messages are handled in order).
    Returns the status messages that arrived on the way."""
    websocket.send_json({"type": "ping"})
    received = []
    while (message := websocket.receive_json()) != {"type": "pong"}:
        received.append(message)
    return received


def signed_in(websocket, auth_headers):
    """Signs the interviewer in on a freshly opened audio WebSocket."""
    websocket.send_json({"token": login_token(auth_headers)})
    assert websocket.receive_json() == {"type": "ready"}
    return websocket


# ---------- Task 8.1.1: each speaker's audio on its own connection ----------


def test_audio_pieces_are_checked():
    assert chunk_ms(audio(100)) == 100
    assert chunk_ms(audio(100) + b"\x00") is None  # half a sample
    assert chunk_ms(audio(20)) is None  # too short for the speech service
    assert chunk_ms(audio(1500)) is None  # too long


def test_interviewer_audio_is_labelled_by_the_server(client, auth_headers, channels):
    session_id, _ = live_interview(client, auth_headers)
    with client.websocket_connect(f"/api/ws/interviews/{session_id}/audio") as ws:
        signed_in(ws, auth_headers)
        ws.send_bytes(audio())
        ws.send_bytes(audio())
        settle(ws)
    [channel] = channels
    assert (channel.session_id, channel.speaker) == (session_id, "interviewer")
    assert channel.audio_ms == 200


def test_candidate_audio_uses_the_invite_link(client, auth_headers, channels):
    session_id, invite = live_interview(client, auth_headers)
    with client.websocket_connect(f"/api/ws/invite/{invite}/audio") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(audio())
        settle(ws)
    [channel] = channels
    assert (channel.session_id, channel.speaker) == (session_id, "candidate")
    assert channel.audio_ms == 100


def test_interviewer_door_needs_a_valid_login(client, auth_headers, channels):
    session_id, invite = live_interview(client, auth_headers)
    for first_message in ({}, {"token": "not-a-token"}, {"token": invite}):  # the invite link is not a login
        with client.websocket_connect(f"/api/ws/interviews/{session_id}/audio") as ws:
            ws.send_json(first_message)
            assert closed_with(ws) == transcripts.NOT_SIGNED_IN
    assert channels == []


def test_wrong_or_ended_interviews_are_refused(client, auth_headers, channels):
    session_id, invite = live_interview(client, auth_headers)
    with client.websocket_connect("/api/ws/invite/not-a-real-link/audio") as ws:
        assert closed_with(ws) == transcripts.NOT_FOUND
    with client.websocket_connect("/api/ws/interviews/999999/audio") as ws:
        ws.send_json({"token": login_token(auth_headers)})
        assert closed_with(ws) == transcripts.NOT_FOUND

    client.post(f"/api/interviews/{session_id}/end", headers=auth_headers)
    with client.websocket_connect(f"/api/ws/invite/{invite}/audio") as ws:
        assert closed_with(ws) == transcripts.NOT_FOUND
    with client.websocket_connect(f"/api/ws/interviews/{session_id}/audio") as ws:
        ws.send_json({"token": login_token(auth_headers)})
        assert closed_with(ws) == transcripts.NOT_FOUND
    assert channels == []


# ---------- Task 8.1.2: one speech stream per speaker ----------


def segments_logged(caplog) -> list[dict]:
    """The 'speech segment' log lines: who spoke, when (ms since the start) and how many words."""
    found = []
    for record in caplog.records:
        if getattr(record, "event", "") == "speech_segment":
            start, end = map(int, re.findall(r"\d+", record.getMessage())[:2])
            found.append({"speaker": record.speaker, "start_ms": start, "end_ms": end, "words": record.count})
    return found


def test_each_speaker_has_their_own_speech_stream(client, auth_headers, channels, caplog):
    caplog.set_level(logging.INFO)
    FakeSpeechStream.script = ["Tell me about yourself", "I build APIs in Python every day"]
    session_id, invite = live_interview(client, auth_headers)
    with client.websocket_connect(f"/api/ws/interviews/{session_id}/audio") as interviewer:
        signed_in(interviewer, auth_headers)
        with client.websocket_connect(f"/api/ws/invite/{invite}/audio") as candidate:
            candidate.receive_json()
            for _ in range(10):
                interviewer.send_bytes(audio())  # 1 s from the interviewer: the first sentence
            settle(interviewer)
            for _ in range(10):
                candidate.send_bytes(audio())  # then 1 s from the candidate: the second
            settle(candidate)

    assert [stream.audio_ms for stream in FakeSpeechStream.made] == [1000, 1000]
    assert all(stream.stopped for stream in FakeSpeechStream.made)  # closed politely when the browser left
    assert [(s["speaker"], s["words"]) for s in segments_logged(caplog)] == [("interviewer", 4), ("candidate", 7)]
    assert "Python" not in caplog.text  # what people say is never written to the log


def test_times_are_counted_from_the_interview_start(client, auth_headers, channels, caplog):
    caplog.set_level(logging.INFO)
    session_id, _ = live_interview(client, auth_headers)
    with SessionLocal() as db:  # pretend the interview started a minute ago
        db.get(InterviewSession, session_id).started_at = datetime.now(timezone.utc) - timedelta(seconds=60)
        db.commit()
    with client.websocket_connect(f"/api/ws/interviews/{session_id}/audio") as ws:
        signed_in(ws, auth_headers)
        for _ in range(10):
            ws.send_bytes(audio())
        settle(ws)
    [segment] = segments_logged(caplog)
    assert 58_000 <= segment["start_ms"] <= 62_000  # about 60 s after the start (the test sends audio fast)
    assert segment["end_ms"] >= segment["start_ms"]


def test_without_a_speech_key_the_call_goes_on(client, auth_headers, monkeypatch, channels):
    monkeypatch.setattr(speech, "SpeechStream", RealSpeechStream)  # the real one, but with no key (conftest)
    session_id, _ = live_interview(client, auth_headers)
    with client.websocket_connect(f"/api/ws/interviews/{session_id}/audio") as ws:
        signed_in(ws, auth_headers)
        ws.send_bytes(audio())
        assert ws.receive_json() == {"type": "status", "state": "unavailable"}
        ws.send_bytes(audio())  # the connection stays open; the audio is simply not used
        settle(ws)
    assert channels[0].unavailable


def test_the_timeline_follows_the_clock_across_pauses():
    timeline = Timeline()
    timeline.add(100, received_ms=10_100)  # audio 0-100 ms was heard at clock 10 000-10 100
    timeline.add(100, received_ms=10_200)
    timeline.add(100, received_ms=15_300)  # nothing for 5 s (muted), then audio 200-300 ms
    assert timeline.clock_at(50) == 10_050
    assert timeline.clock_at(150) == 10_150
    assert timeline.clock_at(250) == 15_250  # after the pause, the clock moved on but the audio did not


# ---------- The AssemblyAI wrapper (speech.py), with a pretend AssemblyAI client ----------


class FakeAssemblyAI:
    """Stands in for AssemblyAI's AsyncRealTimeTranscriber."""

    last: "FakeAssemblyAI"
    refuse = False

    def __init__(self, options):
        self.options = options
        self.handlers = {}
        self.sent: list[bytes] = []
        self.terminated = False
        FakeAssemblyAI.last = self

    def on(self, event, handler):
        self.handlers[event] = handler

    async def connect(self, parameters):
        self.parameters = parameters
        if FakeAssemblyAI.refuse:
            await self.handlers[RealTimeEvents.Error](self, RealTimeError("Not Authorized", 4001))

    async def stream(self, chunk):
        self.sent.append(chunk)

    async def disconnect(self, terminate=False):
        self.terminated = terminate

    async def say(self, text: str, final: bool, turn: int = 0):
        words = [Word(start=1000 + 300 * i, end=1250 + 300 * i, confidence=0.9, text=w, word_is_final=final) for i, w in enumerate(text.split())]
        event = TurnEvent(
            type="Turn", turn_order=turn, turn_is_formatted=final, end_of_turn=final,
            transcript=text, end_of_turn_confidence=0.9, words=words,
        )
        await self.handlers[RealTimeEvents.Turn](self, event)


@pytest.fixture
def assemblyai(monkeypatch):
    FakeAssemblyAI.refuse = False
    monkeypatch.setattr(speech, "AsyncRealTimeTranscriber", FakeAssemblyAI)
    monkeypatch.setattr(settings, "assemblyai_api_key", "test-key")
    return FakeAssemblyAI


def run(coroutine):
    return asyncio.run(coroutine)


def test_the_stream_asks_for_16khz_audio_with_our_settings(assemblyai):
    stream = RealSpeechStream(on_heard=None, on_closed=None)
    run(stream.start())
    client = assemblyai.last
    assert client.options.api_key == "test-key"
    assert client.options.api_host == settings.stt_host
    assert client.parameters.sample_rate == 16000
    assert str(client.parameters.encoding) == "pcm_s16le"
    assert str(client.parameters.speech_model) == settings.stt_model
    run(stream.send(audio()))
    assert client.sent == [audio()]


def test_turns_become_heard_results(assemblyai):
    heard: list[Heard] = []

    async def on_heard(result):
        heard.append(result)

    async def scenario():
        stream = RealSpeechStream(on_heard, on_closed=None)
        await stream.start()
        await assemblyai.last.say("i build", final=False)
        await assemblyai.last.say("I build APIs.", final=True)
        await assemblyai.last.say("   ", final=False)  # nothing recognised: ignored

    run(scenario())
    assert heard == [
        Heard(turn=0, text="i build", start_ms=1000, end_ms=1550, final=False),
        Heard(turn=0, text="I build APIs.", start_ms=1000, end_ms=1850, final=True),
    ]


def test_a_refused_connection_raises_a_clear_error(assemblyai):
    assemblyai.refuse = True
    with pytest.raises(SpeechError, match="Not Authorized"):
        run(RealSpeechStream(on_heard=None, on_closed=None).start())


def test_a_missing_key_raises_a_clear_error(assemblyai, monkeypatch):
    monkeypatch.setattr(settings, "assemblyai_api_key", "")
    with pytest.raises(SpeechError, match="ASSEMBLYAI_API_KEY"):
        run(RealSpeechStream(on_heard=None, on_closed=None).start())


def test_closing_by_itself_is_reported_but_our_stop_is_not(assemblyai):
    reasons: list[str] = []

    async def on_closed(reason):
        reasons.append(reason)

    async def scenario():
        first = RealSpeechStream(on_heard=None, on_closed=on_closed)
        await first.start()
        await assemblyai.last.handlers[RealTimeEvents.Error](assemblyai.last, RealTimeError("Session Expired", 4008))
        second = RealSpeechStream(on_heard=None, on_closed=on_closed)
        await second.start()
        await second.stop()
        await assemblyai.last.handlers[RealTimeEvents.Termination](assemblyai.last, TerminationEvent())
        return assemblyai.last

    client = run(scenario())
    assert reasons == ["Session Expired (code 4008)"]
    assert client.terminated  # stop() asks the service to finish the last words first