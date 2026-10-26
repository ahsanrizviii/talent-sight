"""Tests for the LiveKit room service (Task 7.1.1). They need no running LiveKit server."""

import json

import jwt
import pytest

from app import livekit_service
from app.settings import settings

SECRET = "test-secret-that-is-at-least-32-characters-long"


@pytest.fixture
def livekit_keys(monkeypatch):
    monkeypatch.setattr(settings, "livekit_api_key", "test-key")
    monkeypatch.setattr(settings, "livekit_api_secret", SECRET)


def decode(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=["HS256"])


def test_room_name_is_one_room_per_interview():
    assert livekit_service.room_name(7) == "interview-7"


def test_token_opens_only_its_own_room(livekit_keys):
    claims = decode(livekit_service.join_token(7, "candidate-3", "Maya Rahman", "candidate"))
    assert claims["sub"] == "candidate-3"
    assert claims["name"] == "Maya Rahman"
    assert claims["video"]["room"] == "interview-7"
    assert claims["video"]["roomJoin"] is True
    assert claims["video"].get("roomAdmin") is not True  # nobody can manage other rooms
    assert json.loads(claims["metadata"]) == {"role": "candidate"}


def test_token_is_short_lived(livekit_keys):
    claims = decode(livekit_service.join_token(1, "interviewer-1", "Interviewer", "interviewer"))
    assert claims["exp"] - claims["nbf"] == livekit_service.TOKEN_MINUTES * 60


def test_token_for_a_different_secret_is_rejected(livekit_keys):
    token = livekit_service.join_token(1, "interviewer-1", "Interviewer", "interviewer")
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, "another-secret-that-is-also-32-characters-long", algorithms=["HS256"])


def test_missing_keys_give_a_clear_error(monkeypatch):
    monkeypatch.setattr(settings, "livekit_api_key", "")
    with pytest.raises(livekit_service.LiveKitError, match="keys are not set"):
        livekit_service.join_token(1, "x", "X", "candidate")


def test_unreachable_server_gives_a_safe_message(livekit_keys, monkeypatch):
    monkeypatch.setattr(settings, "livekit_server_url", "http://127.0.0.1:1")
    with pytest.raises(livekit_service.LiveKitError, match="not reachable"):
        livekit_service.ensure_room(1)


def test_closing_a_room_never_raises(livekit_keys, monkeypatch):
    monkeypatch.setattr(settings, "livekit_server_url", "http://127.0.0.1:1")
    livekit_service.close_room(1)  # must simply returns