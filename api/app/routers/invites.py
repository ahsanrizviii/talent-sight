from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import session_from_invite
from app.models import InterviewSession

router = APIRouter(prefix="/api/invite", tags=["candidate"])

class InviteInfo(BaseModel):
    
    session_id: int
    scheduled_at: datetime
    status: str

@router.get("/{invite_token}", response_model=InviteInfo)
def invite_info(session: InterviewSession = Depends(session_from_invite)):
    return InviteInfo(
        session_id=session.id,
        scheduled_at=session.scheduled_at,
        status=session.status,
    )