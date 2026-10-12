import asyncio
import json
import logging
from datetime import timedelta

from livekit import api

from app.settings import settings

log = logging.getLogger("talentsight")

TOKEN_MINUTES = 120  # how long one join token works
EMPTY_ROOM_SECONDS = 600  # LiveKit closes a room that stays empty for 10 minutes
SERVER_TIMEOUT_SECONDS = 10


class LiveKitError(Exception):
    """The video server could not be reached or is not set up. The message is safe to show."""


def room_name(session_id: int) -> str:
    return f"interview-{session_id}"


def _check_keys() -> None:
    if not settings.livekit_api_key or not settings.livekit_api_secret:
        raise LiveKitError("The video server keys are not set. Check LIVEKIT_API_KEY and LIVEKIT_API_SECRET in .env.")


def join_token(session_id: int, identity: str, name: str, role: str) -> str:
    """A signed token that lets exactly one person join exactly one room.

    identity is unique inside the room: joining again with the same identity replaces the
    old connection, which is what we want after a refresh or a lost connection.
    """
    _check_keys()
    return (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(name)
        .with_metadata(json.dumps({"role": role}))
        .with_ttl(timedelta(minutes=TOKEN_MINUTES))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name(session_id),
                can_publish=True,
                can_subscribe=True,
                can_publish_data=False,
            )
        )
        .to_jwt()
    )


async def _create_room(session_id: int) -> None:
    client = api.LiveKitAPI(settings.livekit_server_url, settings.livekit_api_key, settings.livekit_api_secret)
    try:
        # Creating a room that already exists simply returns it, so this is safe to repeat.
        await asyncio.wait_for(
            client.room.create_room(
                api.CreateRoomRequest(
                    name=room_name(session_id),
                    empty_timeout=EMPTY_ROOM_SECONDS,
                    max_participants=2,
                )
            ),
            SERVER_TIMEOUT_SECONDS,
        )
    finally:
        await client.aclose()


async def _delete_room(session_id: int) -> None:
    client = api.LiveKitAPI(settings.livekit_server_url, settings.livekit_api_key, settings.livekit_api_secret)
    try:
        await asyncio.wait_for(
            client.room.delete_room(api.DeleteRoomRequest(room=room_name(session_id))),
            SERVER_TIMEOUT_SECONDS,
        )
    finally:
        await client.aclose()


def ensure_room(session_id: int) -> None:
    """Makes sure the room exists, limited to two people. Raises LiveKitError if it cannot."""
    _check_keys()
    try:
        asyncio.run(_create_room(session_id))
    except Exception as error:
        log.error("livekit create room failed", exc_info=error, extra={"event": "livekit_room_failed", "session_id": session_id})
        raise LiveKitError("The video server is not reachable right now. Please try again in a moment.") from error


def close_room(session_id: int) -> None:
    """Removes the room and disconnects everyone in it. Never raises: the interview is over anyway."""
    if not settings.livekit_api_key or not settings.livekit_api_secret:
        return
    try:
        asyncio.run(_delete_room(session_id))
    except Exception as error:
        # A room that does not exist (nobody ever joined) also lands here. That is fine.
        log.info("livekit close room skipped", extra={"event": "livekit_close_skipped", "session_id": session_id, "reason": str(error)[:120]})