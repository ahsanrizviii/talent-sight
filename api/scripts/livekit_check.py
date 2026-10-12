"""Checks that the API can reach the LiveKit server, create a room and make a token.

Run:  docker compose exec api python -m scripts.livekit_check
"""

import jwt

from app import livekit_service
from app.settings import settings

SESSION_ID = 0  # a throw-away room that is deleted again at the end

livekit_service.ensure_room(SESSION_ID)
print(f"room {livekit_service.room_name(SESSION_ID)}: created")

token = livekit_service.join_token(SESSION_ID, "check-user", "Check User", "interviewer")
claims = jwt.decode(token, settings.livekit_api_secret, algorithms=["HS256"])
print("token for", claims["sub"], "room", claims["video"]["room"], "valid for", claims["exp"] - claims["nbf"], "seconds")

livekit_service.close_room(SESSION_ID)
print("room deleted. LiveKit is ready.")