"""Tests for deleting a candidate and everything about them (Task 11.1.1, N19).

The calendar is a fake (see test_calendar.py), so no real Google Calendar is touched.
"""

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    Assessment,
    CalendarEvent,
    Candidate,
    CandidateScore,
    ClaimCheck,
    InterviewEvaluation,
    InterviewSession,
    InviteBatch,
    InviteDelivery,
    JobProfile,
    RequirementVerdict,
    SessionParticipant,
    TranscriptSegment,
)
from app.privacy import what_is_kept
from app.settings import settings
from scripts import delete_candidate as script
from tests.test_calendar import google  # noqa: F401  (the fake Google Calendar)


def full_candidate(name: str = "Maya Rahman", job_id: int | None = None) -> tuple[int, Path]:
    """A candidate with a CV file and one row in every table that can hold data about them."""
    with SessionLocal() as db:
        if job_id is None:
            job = JobProfile(title="Backend Developer")
            db.add(job)
            db.flush()
            job_id = job.id
        cv = Path(settings.cv_upload_dir) / f"job-{job_id}" / f"{name.split()[0].lower()}.pdf"
        cv.parent.mkdir(parents=True, exist_ok=True)
        cv.write_bytes(b"%PDF-1.4 test")
        person = Candidate(job_profile_id=job_id, name=name, email="maya@example.com", cv_filename="cv.pdf", cv_path=str(cv), status="screened")
        db.add(person)
        db.flush()
        now = datetime.now(timezone.utc)
        session = InterviewSession(
            candidate_id=person.id, scheduled_at=now, invite_token=f"token-{person.id}", invite_expires_at=now, status="ended", started_at=now,
        )
        db.add(session)
        db.add(RequirementVerdict(candidate_id=person.id, requirement="Python", kind="skill", mandatory=True, verdict="met"))
        db.add(CandidateScore(candidate_id=person.id, technical_skills=80, experience=70, qualifications=60, jd_match=70, overall=72.5))
        db.add(Assessment(candidate_id=person.id, status="done", overall_position="possible_fit", report={"candidate": {"name": name}}))
        batch = InviteBatch(job_profile_id=job_id, total=1)
        db.add(batch)
        db.flush()
        db.add(SessionParticipant(session_id=session.id, role="candidate", identity=f"candidate-{person.id}", joined_at=now))
        db.add(TranscriptSegment(session_id=session.id, speaker="candidate", text="I use Python every day.", start_ms=0, end_ms=900))
        db.add(CalendarEvent(session_id=session.id, event_id=f"event-{person.id}", calendar_id="primary"))
        db.add(InviteDelivery(batch_id=batch.id, session_id=session.id, status="sent"))
        db.add(InterviewEvaluation(session_id=session.id, status="done", result={"pairs": []}))
        db.add(ClaimCheck(candidate_id=person.id, session_id=session.id, status="done", result={"claims": []}))
        db.commit()
        return person.id, cv


def kept(candidate_id: int) -> dict[str, int]:
    with SessionLocal() as db:
        return what_is_kept(db, candidate_id)


def test_the_fixture_really_fills_every_table(client):
    candidate_id, _ = full_candidate()
    assert all(count == 1 for count in kept(candidate_id).values()), kept(candidate_id)


def test_deleting_a_candidate_leaves_nothing_behind(client, auth_headers):
    candidate_id, cv = full_candidate()
    other_id, other_cv = full_candidate(name="Arif Hossain")

    assert client.delete(f"/api/candidates/{candidate_id}", headers=auth_headers).status_code == 204
    assert all(count == 0 for count in kept(candidate_id).values()), kept(candidate_id)
    assert not cv.exists()
    with SessionLocal() as db:
        assert db.get(Candidate, candidate_id) is None
    # Nobody else is touched.
    assert all(count == 1 for count in kept(other_id).values())
    assert other_cv.exists()


def test_the_google_calendar_entry_is_removed_too(client, auth_headers, google):
    candidate_id, _ = full_candidate()
    google.entries[f"event-{candidate_id}"] = {"summary": "Interview: Maya Rahman for Backend Developer"}
    client.delete(f"/api/candidates/{candidate_id}", headers=auth_headers)
    assert f"event-{candidate_id}" not in google.entries  # the name no longer sits on the shared calendar
    assert ("DELETE", f"https://www.googleapis.com/calendar/v3/calendars/primary/events/event-{candidate_id}", None) in google.calls


def test_deleting_a_job_removes_its_candidates_cv_files(client, auth_headers):
    first, first_cv = full_candidate()
    with SessionLocal() as db:
        job_id = db.get(Candidate, first).job_profile_id
    second, second_cv = full_candidate(name="Arif Hossain", job_id=job_id)

    assert client.delete(f"/api/jobs/{job_id}", headers=auth_headers).status_code == 204
    assert not first_cv.exists() and not second_cv.exists()
    assert not first_cv.parent.exists()  # the job's empty CV folder is gone as well
    with SessionLocal() as db:
        assert db.scalars(select(Candidate)).all() == []


def test_the_admin_script_only_shows_without_yes(client, capsys):
    candidate_id, cv = full_candidate()
    assert script.main([str(candidate_id)]) == 0
    printed = capsys.readouterr().out
    assert "transcript lines: 1" in printed and "Nothing was deleted" in printed
    assert kept(candidate_id)["interviews"] == 1 and cv.exists()


def test_the_admin_script_deletes_with_yes(client, capsys):
    candidate_id, cv = full_candidate()
    assert script.main([str(candidate_id), "--yes"]) == 0
    assert f"Candidate {candidate_id} and all their data were deleted." in capsys.readouterr().out
    assert all(count == 0 for count in kept(candidate_id).values())
    assert not cv.exists()


def test_the_admin_script_refuses_an_unknown_candidate(client, capsys):
    assert script.main(["999999", "--yes"]) == 1
    assert "There is no candidate 999999." in capsys.readouterr().out