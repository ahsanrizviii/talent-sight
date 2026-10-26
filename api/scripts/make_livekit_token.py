import sys

from livekit import api

from app.settings import settings

ROOM = "prototype-room"

identity = sys.argv[1] if len(sys.argv) > 1 else "tab-1"

token = (
    api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
    .with_identity(identity)
    .with_grants(api.VideoGrants(room_join=True, room=ROOM))
)

print(token.to_jwt())