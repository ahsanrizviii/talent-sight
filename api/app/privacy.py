
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import calendar_events
from app.cv_files import delete_cv_file
from app.models import (
    Assessment,
    CalendarEvent,
    Candidate,
    CandidateScore,
    ClaimCheck,
    FaceTemplate,
    IdentityRecord,
    InterviewChatMessage,
    InterviewEvaluation,
    InterviewQuality,
    InterviewScore,
    InterviewSession,
    InviteDelivery,
    JobProfile,
    OnboardingCheck,
    LitmusCheck,
    RequirementVerdict,
    SessionParticipant,
    TranscriptSegment,
    
)
from app.settings import settings

log = logging.getLogger("talentsight.privacy")


def what_is_kept(db: Session, candidate_id: int) -> dict[str, int]:
    """How many rows each table holds about one candidate. Used to show what a delete removes."""
    sessions = select(InterviewSession.id).where(InterviewSession.candidate_id == candidate_id)
    counts = {
        "requirement verdicts": select(func.count()).select_from(RequirementVerdict).where(RequirementVerdict.candidate_id == candidate_id),
        "scores": select(func.count()).select_from(CandidateScore).where(CandidateScore.candidate_id == candidate_id),
        "interviews": select(func.count()).select_from(InterviewSession).where(InterviewSession.candidate_id == candidate_id),
        "participants": select(func.count()).select_from(SessionParticipant).where(SessionParticipant.session_id.in_(sessions)),
        "transcript lines": select(func.count()).select_from(TranscriptSegment).where(TranscriptSegment.session_id.in_(sessions)),
        "calendar entries": select(func.count()).select_from(CalendarEvent).where(CalendarEvent.session_id.in_(sessions)),
        "invitation deliveries": select(func.count()).select_from(InviteDelivery).where(InviteDelivery.session_id.in_(sessions)),
        "answer analyses": select(func.count()).select_from(InterviewEvaluation).where(InterviewEvaluation.session_id.in_(sessions)),
        "assessments": select(func.count()).select_from(Assessment).where(Assessment.candidate_id == candidate_id),
        "chat messages": select(func.count()).select_from(InterviewChatMessage).where(InterviewChatMessage.session_id.in_(sessions)),
        "interview quality reviews": select(func.count()).select_from(InterviewQuality).where(InterviewQuality.session_id.in_(sessions)),
        "interview scores": select(func.count()).select_from(InterviewScore).where(InterviewScore.session_id.in_(sessions)),
        "identity records": select(func.count()).select_from(IdentityRecord).where(IdentityRecord.candidate_id == candidate_id),
        "face templates": select(func.count()).select_from(FaceTemplate).where(FaceTemplate.candidate_id == candidate_id),
        "onboarding checks": select(func.count()).select_from(OnboardingCheck).where(OnboardingCheck.candidate_id == candidate_id),
        "claim checks": select(func.count()).select_from(ClaimCheck).where(ClaimCheck.candidate_id == candidate_id),
        "litmus checks": select(func.count()).select_from(LitmusCheck).where(LitmusCheck.candidate_id == candidate_id),
    }
    return {name: db.scalar(query) for name, query in counts.items()}


def delete_candidate(db: Session, candidate: Candidate) -> None:
    """Removes the candidate and everything about them. Commits."""
    candidate_id = candidate.id
    sessions = db.scalars(select(InterviewSession).where(InterviewSession.candidate_id == candidate_id)).all()
    for session in sessions:
        # The shared calendar entry is outside our database, so the cascade cannot reach it.
        # A failure is logged by calendar_events and does not stop the delete.
        calendar_events.remove(db, session)
    delete_cv_file(candidate.cv_path)
    db.delete(candidate)
    db.commit()
    log.info("candidate deleted", extra={"event": "candidate_deleted", "candidate_id": candidate_id})


def delete_job_candidates(db: Session, job: JobProfile) -> int:
    """Before a job is deleted: removes each of its candidates the same way, then the job's empty
    CV folder. Without this, deleting a job would leave its CV files on the volume."""
    candidates = db.scalars(select(Candidate).where(Candidate.job_profile_id == job.id)).all()
    for candidate in candidates:
        delete_candidate(db, candidate)
    folder = Path(settings.cv_upload_dir) / f"job-{job.id}"
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    return len(candidates)