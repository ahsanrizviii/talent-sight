from datetime import datetime, timedelta, timezone
import jwt
from pwdlib import PasswordHash
from app.settings import settings

password_hasher = PasswordHash.recommended()

def hash_password(password: str) -> str:
    return password_hasher.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)

def create_access_token(interviewer_id: int) -> str:

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(interviewer_id),  # sub = "subject": who the token belongs to
        "role": "interviewer",
        "iat": now,  # issued at
        "exp": now + timedelta(minutes=settings.jwt_minutes),  # expires at
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

def read_access_token(token: str) -> dict:

    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])