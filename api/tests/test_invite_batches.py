"""Tests for inviting the top candidates of a job at once: HR gives the first interview day and how
many to invite; everyone gets a free 1-hour slot and an e-mail, sent in the background."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import holiday_calendar
from app.db import SessionLocal
from app.models import Candidate, CandidateScore, InterviewSession, JobProfile
from app.routers import invite_batches
from app.settings import settings

from tests.test_interviews import fake_video_server  # noqa: F401
from tests.test_invite_mail import FakeSMTP, fake_mail_server  # noqa: F401

ZONE = timezone(timedelta(minutes=settings.interview_utc_offset_minutes))


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(invite_batches, "PAUSE_SECONDS", 0)


def make_job_with_ranked(count: int, without_email: tuple[int, ...] = ()) -> tuple[int, list[int]]:
    """A job with `count` screened candidates; candidate 1 has the best score."""
    with SessionLocal() as db:
        job = JobProfile(title="Data Engineer")
        db.add(job)
        db.flush()
        ids = []
        for place in range(1, count + 1):
            email = "" if place in without_email else f"person{place}@example.com"
            candidate = Candidate(job_profile_id=job.id, name=f"Person {place}", email=email, cv_filename="cv.pdf", status="screened")
            db.add(candidate)
            db.flush()
            score = 100 - place
            db.add(CandidateScore(candidate_id=candidate.id, technical_skills=score, experience=score, qualifications=score, jd_match=score, overall=score, justification={}))
            ids.append(candidate.id)
        db.add(Candidate(job_profile_id=job.id, name="Left Out", email="x@example.com", cv_filename="cv.pdf", status="excluded"))
        db.commit()
        return job.id, ids


def next_monday() -> date:
    today = datetime.now(timezone.utc).date()
    return today + timedelta(days=(7 - today.weekday()) or 7)


def invite(client, headers, job_id, top: int, start: date | None = None):
    return client.post(
        f"/api/jobs/{job_id}/invite-top", json={"top": top, "start_date": (start or next_monday()).isoformat()}, headers=headers
    )


def booked() -> list[InterviewSession]:
    with SessionLocal() as db:
        return list(db.scalars(select(InterviewSession).order_by(InterviewSession.scheduled_at)))


def test_the_top_n_are_invited_in_ranking_order(client, auth_headers):
    job, ids = make_job_with_ranked(6)
    response = invite(client, auth_headers, job, 3)
    assert response.status_code == 201
    sessions = booked()
    assert [s.candidate_id for s in sessions] == ids[:3]  # the best-ranked gets the earliest slot
    assert len(FakeSMTP.sent) == 3  # the background task ran
    assert sorted(m["To"] for m in FakeSMTP.sent) == ["person1@example.com", "person2@example.com", "person3@example.com"]
    assert len({s.invite_token for s in sessions}) == 3  # everyone has their own private link


def test_every_interview_is_one_hour_inside_the_hours_and_15_minutes_apart(client, auth_headers):
    job, _ = make_job_with_ranked(5)
    invite(client, auth_headers, job, 5)
    sessions = booked()
    assert {s.duration_minutes for s in sessions} == {60}
    local = [s.scheduled_at.astimezone(ZONE) for s in sessions]
    assert [f"{t:%a %H:%M}" for t in local] == ["Mon 09:00", "Mon 10:15", "Mon 14:00", "Mon 15:15", "Tue 09:00"]
    assert "Duration: 60 minutes" in FakeSMTP.sent[0].get_body(("plain",)).get_content()


def test_weekends_are_skipped(client, auth_headers):
    job, _ = make_job_with_ranked(2)
    saturday = next_monday() - timedelta(days=2)
    invite(client, auth_headers, job, 2, start=saturday)
    days = {s.scheduled_at.astimezone(ZONE).strftime("%a") for s in booked()}
    assert days == {"Mon"}


def test_holidays_from_the_calendar_are_skipped(client, auth_headers):
    job, _ = make_job_with_ranked(1)
    with SessionLocal() as db:
        holiday_calendar.save_many(db, [(next_monday(), "Test holiday")], source="pdf")
    invite(client, auth_headers, job, 1)
    assert booked()[0].scheduled_at.astimezone(ZONE).date() == next_monday() + timedelta(days=1)


def test_a_missing_address_fails_that_one_only(client, auth_headers):
    job, _ = make_job_with_ranked(3, without_email=(2,))
    invite(client, auth_headers, job, 3)
    latest = client.get(f"/api/jobs/{job}/invite-batches/latest", headers=auth_headers).json()
    assert latest["sent"] == 2 and latest["failed"] == 1
    failed = next(d for d in latest["deliveries"] if d["status"] == "failed")
    assert "no e-mail address" in failed["error"]


def test_already_invited_candidates_are_skipped(client, auth_headers):
    job, ids = make_job_with_ranked(3)
    invite(client, auth_headers, job, 1)
    again = invite(client, auth_headers, job, 3).json()
    assert again["skipped"][0]["candidate_id"] == ids[0]
    assert again["skipped"][0]["reason"] == "Already has an interview booked."
    assert [d["candidate_id"] for d in again["batch"]["deliveries"]] == ids[1:]
    starts = [s.scheduled_at for s in booked()]
    assert len(starts) == len(set(starts))  # no clash with the first one


def test_a_day_in_the_past_is_refused(client, auth_headers):
    job, _ = make_job_with_ranked(1)
    yesterday = datetime.now(ZONE).date() - timedelta(days=1)
    response = invite(client, auth_headers, job, 1, start=yesterday)
    assert response.status_code == 422
    assert booked() == []


def test_a_job_with_nobody_screened_says_so(client, auth_headers):
    with SessionLocal() as db:
        job = JobProfile(title="Empty")
        db.add(job)
        db.commit()
        job_id = job.id
    response = invite(client, auth_headers, job_id, 3)
    assert response.status_code == 409
    assert "passed screening" in response.json()["detail"]


def test_a_failed_email_can_be_tried_again(client, auth_headers):
    job, _ = make_job_with_ranked(2)
    FakeSMTP.fail = True
    batch = invite(client, auth_headers, job, 2).json()["batch"]
    assert client.get(f"/api/jobs/{job}/invite-batches/latest", headers=auth_headers).json()["failed"] == 2
    FakeSMTP.fail = False
    client.post(f"/api/jobs/{job}/invite-batches/{batch['id']}/retry", headers=auth_headers)
    assert client.get(f"/api/jobs/{job}/invite-batches/latest", headers=auth_headers).json()["sent"] == 2


def test_inviting_needs_a_login(client):
    assert client.post("/api/jobs/1/invite-top", json={"top": 1, "start_date": "2030-01-07"}).status_code == 401
