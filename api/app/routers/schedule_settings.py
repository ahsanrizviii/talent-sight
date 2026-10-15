"""Settings page: when interviews may be booked (length, gap, hours, working days)."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import planner, schedule_rules
from app.db import get_db
from app.deps import current_interviewer

router = APIRouter(prefix="/api/schedule-rules", tags=["schedule"], dependencies=[Depends(current_interviewer)])


class Block(BaseModel):
    start: str = Field(pattern=r"^\d{2}:\d{2}$")  # "09:00"
    end: str = Field(pattern=r"^\d{2}:\d{2}$")  # "12:00"


class RulesIn(BaseModel):
    interview_minutes: int = Field(ge=10, le=240)
    gap_minutes: int = Field(ge=0, le=120)
    windows: list[Block] = Field(min_length=1, max_length=6)
    work_days: list[str] = Field(min_length=1, max_length=7)


class RulesOut(RulesIn):
    slots_per_day: int


def to_out(rules: planner.Rules) -> RulesOut:
    info = rules.describe()
    return RulesOut(
        interview_minutes=info["interview_minutes"],
        gap_minutes=info["gap_minutes"],
        windows=[Block(start=start.strftime("%H:%M"), end=end.strftime("%H:%M")) for start, end in rules.windows],
        work_days=info["work_days"],
        slots_per_day=info["slots_per_day"],
    )


@router.get("", response_model=RulesOut)
def read_rules(db: Session = Depends(get_db)):
    try:
        return to_out(schedule_rules.current(db))
    except planner.PlanError as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem))


@router.put("", response_model=RulesOut)
def save_rules(body: RulesIn, db: Session = Depends(get_db)):
    """Saves new rules. Interviews already booked keep their own time and length."""
    try:
        rules = schedule_rules.save(
            db,
            body.interview_minutes,
            body.gap_minutes,
            ",".join(f"{block.start}-{block.end}" for block in body.windows),
            ",".join(body.work_days),
        )
    except planner.PlanError as problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(problem))
    return to_out(rules)
