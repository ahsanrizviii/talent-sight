"""The setup check page (UI): is e-mail, the public link, video and Calendar really working?"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app import invite_mail, readiness
from app.deps import current_interviewer

router = APIRouter(prefix="/api/setup", tags=["setup"], dependencies=[Depends(current_interviewer)])


class CheckOut(BaseModel):
    key: str
    label: str
    ok: bool
    detail: str
    fix: str
    optional: bool


class TestMailIn(BaseModel):
    to: str = Field(min_length=3, max_length=255)


class TestMailOut(BaseModel):
    sent: bool
    error: str = ""


@router.get("/checks", response_model=list[CheckOut])
def checks(probe: bool = Query(True)):
    """probe=false only reads the settings (instant); probe=true really connects to each service."""
    return readiness.run_checks(probe)


@router.post("/test-email", response_model=TestMailOut)
def test_email(body: TestMailIn):
    """Sends one test message, so the team can see it arrives."""
    error = invite_mail.send_test(body.to)
    return TestMailOut(sent=error == "", error=error)
