import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import face
from app.db import SessionLocal
from app.models import Candidate, FaceTemplate, IdentityRecord, Interviewer, InterviewSession, OnboardingCheck
from app.settings import settings


log = logging.getLogger("talentsight.identity")

TEMPLATES_PER_INTERVIEW = 3
NO_CONSENT = "Face matching was not agreed to, so no picture is used."


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def keep_until() -> datetime:
    return utcnow() + timedelta(days=settings.biometric_retention_days)


def purge_expired(db: Session) -> int:
    """Deletes every template past its retention date."""
    removed = db.execute(delete(FaceTemplate).where(FaceTemplate.expires_at < utcnow())).rowcount or 0
    db.commit()
    if removed:
        log.info("expired face templates deleted", extra={"event": "face_templates_expired", "count": removed})
    return removed


def purge_expired_at_start() -> None:
    with SessionLocal() as db:
        purge_expired(db)


def record_of(db: Session, session_id: int) -> IdentityRecord | None:
    return db.scalar(select(IdentityRecord).where(IdentityRecord.session_id == session_id))


def record_for(db: Session, session: InterviewSession) -> IdentityRecord:
    record = record_of(db, session.id)
    if record is None:
        record = IdentityRecord(session_id=session.id, candidate_id=session.candidate_id)
        db.add(record)
        db.flush()
    return record


def templates_of_session(db: Session, session_id: int) -> int:
    return db.scalar(select(func.count()).select_from(FaceTemplate).where(FaceTemplate.session_id == session_id)) or 0


def templates_on_file(db: Session, candidate_id: int) -> list[FaceTemplate]:
    return list(db.scalars(
        select(FaceTemplate).where(FaceTemplate.candidate_id == candidate_id, FaceTemplate.expires_at >= utcnow())
    ))


def delete_templates(db: Session, candidate_id: int) -> int:
    removed = db.execute(delete(FaceTemplate).where(FaceTemplate.candidate_id == candidate_id)).rowcount or 0
    db.commit()
    log.info("face templates deleted", extra={"event": "face_templates_deleted", "candidate_id": candidate_id, "count": removed})
    return removed


def set_consent(db: Session, session: InterviewSession, consent: bool) -> IdentityRecord:
    record = record_for(db, session)
    record.consent, record.consent_at = consent, utcnow()
    if not consent:  # saying no later removes what was already made
        db.execute(delete(FaceTemplate).where(FaceTemplate.session_id == session.id))
    db.commit()
    log.info("face matching consent", extra={"event": "face_consent_given" if consent else "face_consent_refused", "session_id": session.id})
    return record


def add_frame(db: Session, session: InterviewSession, image: str) -> int:
    """Makes one template from one camera frame. Returns how many this interview now has (at most 3)."""
    record = record_of(db, session.id)
    if record is None or not record.consent:
        raise HTTPException(status.HTTP_403_FORBIDDEN, NO_CONSENT)
    count = templates_of_session(db, session.id)
    if count >= TEMPLATES_PER_INTERVIEW:
        return count
    try:
        found = face.read_face(image)
    except face.FaceError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except face.FaceUnavailable as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    db.add(FaceTemplate(candidate_id=session.candidate_id, session_id=session.id, slot=count + 1, vector=found.template, expires_at=keep_until()))
    db.commit()
    log.info("face template kept", extra={"event": "face_template_kept", "session_id": session.id, "count": count + 1})
    return count + 1


def set_id_check(db: Session, session: InterviewSession, interviewer: Interviewer, id_checked: bool, name_matches: bool) -> IdentityRecord:
    record = record_for(db, session)
    record.id_checked, record.name_matches = id_checked, id_checked and name_matches
    record.checked_by, record.checked_at = interviewer.email, utcnow()
    db.commit()
    return record


def state_of(db: Session, session: InterviewSession) -> dict:
    record = record_of(db, session.id)
    id_checked = bool(record and record.id_checked)
    name_matches = bool(record and record.name_matches)
    return {
        "session_id": session.id,
        "consent": record.consent if record else None,
        "templates": templates_of_session(db, session.id),
        "id_checked": id_checked,
        "name_matches": name_matches,
        "checked_by": record.checked_by if record else "",
        "checked_at": record.checked_at if record else None,
        # confirmed | name_mismatch | not_checked
        "state": "confirmed" if id_checked and name_matches else "name_mismatch" if id_checked else "not_checked",
        "retention_days": settings.biometric_retention_days,
    }




# ---------- the onboarding-day check (Task 13.5.3) ----------
DIRECTIONS = ("left", "right")
CHALLENGE_SECONDS = 120   # the two pictures must be taken within this time
SAME_PERSON_AT = 0.30     # the front and turned pictures must clearly show one person
START_AGAIN = "The check has expired. Start the onboarding check again."


def pick_direction() -> str:
    """Left or right at random, so a recorded video cannot know which way to turn."""
    return secrets.choice(DIRECTIONS)


def check_of(db: Session, candidate_id: int) -> OnboardingCheck | None:
    return db.scalar(select(OnboardingCheck).where(OnboardingCheck.candidate_id == candidate_id))


def start_check(db: Session, candidate: Candidate, interviewer: Interviewer, original_id_checked: bool) -> OnboardingCheck:
    if not original_id_checked:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Check the new hire's original photo ID first, in person or on a live call.")
    row = check_of(db, candidate.id)
    if row is None:
        row = OnboardingCheck(candidate_id=candidate.id)
        db.add(row)
    row.status, row.direction = "waiting", pick_direction()
    row.challenge_until = utcnow() + timedelta(seconds=CHALLENGE_SECONDS)
    row.original_id_checked, row.checked_by, row.checked_at = True, interviewer.email, None
    row.outcome, row.best_score = "", None
    row.decision, row.decision_note, row.decided_by, row.decided_at = "", "", "", None
    db.commit()
    db.refresh(row)
    return row


def read_or_refuse(image: str) -> face.Face:
    try:
        return face.read_face(image)
    except face.FaceError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except face.FaceUnavailable as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error


def finish_check(db: Session, candidate: Candidate, front_image: str, turned_image: str) -> OnboardingCheck:
    """Checks the head turn, then compares the face with the interview's templates.

    A failed head turn or an unusable picture answers 422 and keeps the same challenge, so HR can
    simply take the two pictures again. The pictures are never stored.
    """
    row = check_of(db, candidate.id)
    if row is None or row.status != "waiting" or row.challenge_until is None or row.challenge_until < utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, START_AGAIN)

    templates = templates_on_file(db, candidate.id)
    best = None
    if not templates:
        outcome = "no_templates"
    else:
        front, turned = read_or_refuse(front_image), read_or_refuse(turned_image)
        if abs(front.turn) >= face.FACING_BELOW:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "In the first picture, the new hire must look straight at the camera.")
        wanted = 1 if row.direction == "left" else -1
        if turned.turn * wanted < face.TURNED_AT:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"The head turn was not seen. Ask them to turn their head to their {row.direction} and try again.")
        if face.similarity(front.template, turned.template) < SAME_PERSON_AT:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The two pictures do not show the same person. Take them again.")
        best = max(face.similarity(front.template, template.vector) for template in templates)
        outcome = "match" if best >= face.MATCH_AT else "low_confidence"

    row.status, row.outcome, row.checked_at = "done", outcome, utcnow()
    row.best_score = round(best, 3) if best is not None else None
    row.direction, row.challenge_until = "", None
    db.commit()
    log.info("onboarding check done", extra={"event": f"onboarding_{outcome}", "candidate_id": candidate.id})
    if outcome == "match":
        delete_templates(db, candidate.id)  # the check is done, so the templates are no longer needed
    db.refresh(row)
    return row


def decide(db: Session, candidate: Candidate, interviewer: Interviewer, decision: str, note: str) -> OnboardingCheck:
    """A person's decision on a check that was not a match. Nothing is ever decided automatically."""
    row = check_of(db, candidate.id)
    if row is None or row.status != "done":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Run the onboarding check first.")
    if row.outcome == "match":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to review: the face matched.")
    row.decision, row.decision_note = decision, " ".join(note.split())
    row.decided_by, row.decided_at = interviewer.email, utcnow()
    db.commit()
    delete_templates(db, candidate.id)  # the check is finished either way
    db.refresh(row)
    return row


def onboarding_state(db: Session, candidate: Candidate) -> dict:
    row = check_of(db, candidate.id)
    check = None
    if row is not None:
        check = {
            "status": row.status,
            "original_id_checked": row.original_id_checked,
            "outcome": row.outcome,
            "best_score": row.best_score,
            "needs_review": row.status == "done" and row.outcome != "match" and not row.decision,
            "decision": row.decision,
            "decision_note": row.decision_note,
            "decided_by": row.decided_by,
            "decided_at": row.decided_at,
            "checked_by": row.checked_by,
            "checked_at": row.checked_at,
        }
    # What is on file, so the onboarding tab can say it before anyone starts the camera.
    templates = templates_on_file(db, candidate.id)
    taken = max((t.created_at for t in templates), default=None)
    expires = min((t.expires_at for t in templates), default=None)
    source = db.get(InterviewSession, templates[-1].session_id) if templates else None
    held = db.scalar(
        select(func.count()).select_from(InterviewSession).where(
            InterviewSession.candidate_id == candidate.id,
            InterviewSession.status == "ended",
            InterviewSession.started_at.is_not(None),
        )
    )
    latest_record = db.scalar(
        select(IdentityRecord).where(IdentityRecord.candidate_id == candidate.id).order_by(IdentityRecord.id.desc()).limit(1)
    )
    return {
        "templates_on_file": len(templates),
        "templates_taken_at": taken,
        "templates_expire_at": expires,
        "templates_interview_at": (source.started_at or source.scheduled_at) if source else None,
        "interview_held": bool(held),
        "consent": latest_record.consent if latest_record else None,
        "retention_days": settings.biometric_retention_days,
        "check": check,
    }