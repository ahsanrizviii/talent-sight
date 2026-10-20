"""The identity check (Module 13, F7): the photo ID seen at the interview, and face templates with consent.

At the interview the interviewer looks at the candidate's photo ID on camera and ticks "ID checked" and
"the name matches the CV". That human step is the real check. If the candidate agrees, three face
templates (numbers, never pictures) are made from camera frames during the interview. On onboarding
day HR compares a fresh camera frame with them (Task 13.5.3).

Templates are deleted after the onboarding check, after BIOMETRIC_RETENTION_DAYS, on request, and with
the candidate (N19). Logs never contain pictures or templates (N22). A mismatch is a prompt for a person
to review, never an automatic decision.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import face
from app.db import SessionLocal
from app.models import FaceTemplate, IdentityRecord, Interviewer, InterviewSession
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