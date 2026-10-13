"""Tests for live speech to text (Module 8). No real speech service and no real video server are used."""

import pytest
from starlette.websockets import WebSocketDisconnect

from app.routers import transcripts
from app.transcription import chunk_ms
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


class RecordingChannel:
    """Stands in for SpeakerChannel and remembers what reached it."""

    made: list["RecordingChannel"] = []

    def __init__(self, session_id: int, speaker: str):
        self.session_id = session_id
        self.speaker = speaker
        self.audio = b""
        self.closed = False
        RecordingChannel.made.append(self)

    async def add_audio(self, chunk: bytes) -> None:
        self.audio += chunk

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def channels(monkeypatch):
    RecordingChannel.made = []
    monkeypatch.setattr(transcripts, "SpeakerChannel", RecordingChannel)
    return RecordingChannel.made


def closed_with(websocket) -> int:
    """Waits for the server to close the WebSocket and returns the close code."""
    with pytest.raises(WebSocketDisconnect) as closed:
        websocket.receive_json()
    return closed.value.code


# ---------- Task 8.1.1: each speaker's audio on its own connection ----------


def test_audio_pieces_are_checked():
    assert chunk_ms(audio(100)) == 100
    assert chunk_ms(audio(100) + b"\x00") is None  # half a sample
    assert chunk_ms(audio(20)) is None  # too short for the speech service
    assert chunk_ms(audio(1500)) is None  # too long


def test_interviewer_audio_is_labelled_by_the_server(client, auth_headers, channels):
    session_id, _ = live_interview(client, auth_headers)
    with client.websocket_connect(f"/api/ws/interviews/{session_id}/audio") as ws:
        ws.send_json({"token": login_token(auth_headers)})
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(audio())
        ws.send_bytes(audio())
    [channel] = channels
    assert (channel.session_id, channel.speaker) == (session_id, "interviewer")
    assert channel.audio == audio() * 2
    assert channel.closed


def test_candidate_audio_uses_the_invite_link(client, auth_headers, channels):
    session_id, invite = live_interview(client, auth_headers)
    with client.websocket_connect(f"/api/ws/invite/{invite}/audio") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(audio())
    [channel] = channels
    assert (channel.session_id, channel.speaker) == (session_id, "candidate")
    assert channel.audio == audio()


def test_both_speakers_have_separate_channels(client, auth_headers, channels):
    session_id, invite = live_interview(client, auth_headers)
    with client.websocket_connect(f"/api/ws/interviews/{session_id}/audio") as interviewer:
        interviewer.send_json({"token": login_token(auth_headers)})
        interviewer.receive_json()
        with client.websocket_connect(f"/api/ws/invite/{invite}/audio") as candidate:
            candidate.receive_json()
            interviewer.send_bytes(audio(100))
            candidate.send_bytes(audio(200))
    by_speaker = {channel.speaker: channel.audio for channel in channels}
    assert by_speaker == {"interviewer": audio(100), "candidate": audio(200)}


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