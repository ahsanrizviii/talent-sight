"""Tests for inviting the top candidates of a job at once (plan, then send in the background)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Candidate, CandidateScore, InterviewSession, JobProfile
from app.routers import invite_batches
from app.settings import settings

from tests.test_interviews import fake_video_server  # noqa: F401
from tests.test_invite_mail import FakeSMTP, fake_mail_server  # noqa: F401


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


def next_monday() -> str:
    today = datetime.now(timezone.utc).date()
    return (today + timedelta(days=(7 - today.weekday()) or 7)).isoformat()


def plan(client, headers, job_id, **body):
    return client.post(f"/api/jobs/{job_id}/invite-plan", json={"start_date": next_monday(), **body}, headers=headers)


def test_top_n_gets_the_best_ranked_in_order(client, auth_headers):
    job, ids = make_job_with_ranked(6)
    body = plan(client, auth_headers, job, top=3).json()
    assert body["ranked_total"] == 6 and body["asked"] == 3
    assert [s["candidate_id"] for s in body["slots"]] == ids[:3]
    times = [s["scheduled_at"] for s in body["slots"]]
    assert times == sorted(times)  # the best candidate gets the earliest slot


def test_hand_picked_people_are_planned_in_my_order(client, auth_headers):
    """"I want this person first": the order HR gives decides who gets the earliest slot."""
    job, ids = make_job_with_ranked(5)
    body = plan(client, auth_headers, job, candidate_ids=[ids[3], ids[0], ids[4]]).json()
    assert [s["candidate_id"] for s in body["slots"]] == [ids[3], ids[0], ids[4]]
    times = [s["scheduled_at"] for s in body["slots"]]
    assert times == sorted(times)


def test_choose_one_way_only(client, auth_headers):
    job, ids = make_job_with_ranked(3)
    assert plan(client, auth_headers, job).status_code == 422
    assert plan(client, auth_headers, job, top=2, candidate_ids=[ids[0]]).status_code == 422


def test_only_screened_people_of_this_job_can_be_picked(client, auth_headers):
    job, ids = make_job_with_ranked(2)
    other_job, other_ids = make_job_with_ranked(1)
    assert plan(client, auth_headers, job, candidate_ids=[other_ids[0]]).status_code == 422
    assert plan(client, auth_headers, job, candidate_ids=[ids[0], ids[0]]).status_code == 422


def test_a_batch_can_have_its_own_interview_length(client, auth_headers):
    job, ids = make_job_with_ranked(3)
    body = plan(client, auth_headers, job, top=3, duration_minutes=45).json()
    assert body["rules"]["interview_minutes"] == 45
    times = [datetime.fromisoformat(s["scheduled_at"]) for s in body["slots"]]
    assert times[1] - times[0] == timedelta(minutes=45 + 15)  # 45 minutes + the 15-minute gap
    items = [{"candidate_id": s["candidate_id"], "scheduled_at": s["scheduled_at"]} for s in body["slots"]]
    client.post(f"/api/jobs/{job}/invite-batches", json={"items": items, "duration_minutes": 45}, headers=auth_headers)
    with SessionLocal() as db:
        assert {s.duration_minutes for s in db.scalars(select(InterviewSession))} == {45}
    assert "Duration: 45 minutes" in FakeSMTP.sent[0].get_body(("plain",)).get_content()


def test_planning_saves_nothing(client, auth_headers):
    job, _ = make_job_with_ranked(3)
    plan(client, auth_headers, job, top=3)
    with SessionLocal() as db:
        assert db.scalars(select(InterviewSession)).all() == []
    assert FakeSMTP.sent == []


def test_sending_books_everyone_and_emails_them(client, auth_headers):
    job, ids = make_job_with_ranked(4)
    slots = plan(client, auth_headers, job, top=4).json()["slots"]
    items = [{"candidate_id": s["candidate_id"], "scheduled_at": s["scheduled_at"]} for s in slots]
    response = client.post(f"/api/jobs/{job}/invite-batches", json={"items": items}, headers=auth_headers)
    assert response.status_code == 201
    assert len(FakeSMTP.sent) == 4  # the background task ran
    assert sorted(m["To"] for m in FakeSMTP.sent) == sorted(f"person{i}@example.com" for i in range(1, 5))
    latest = client.get(f"/api/jobs/{job}/invite-batches/latest", headers=auth_headers).json()
    assert latest["total"] == 4 and latest["sent"] == 4 and latest["failed"] == 0
    with SessionLocal() as db:
        tokens = {s.invite_token for s in db.scalars(select(InterviewSession))}
    assert len(tokens) == 4  # everyone has their own private link


def test_a_missing_address_fails_that_one_only(client, auth_headers):
    job, ids = make_job_with_ranked(3, without_email=(2,))
    slots = plan(client, auth_headers, job, top=3).json()["slots"]
    assert [s["email_ok"] for s in slots] == [True, False, True]
    items = [{"candidate_id": s["candidate_id"], "scheduled_at": s["scheduled_at"]} for s in slots]
    client.post(f"/api/jobs/{job}/invite-batches", json={"items": items}, headers=auth_headers)
    latest = client.get(f"/api/jobs/{job}/invite-batches/latest", headers=auth_headers).json()
    assert latest["sent"] == 2 and latest["failed"] == 1
    failed = next(d for d in latest["deliveries"] if d["status"] == "failed")
    assert "no e-mail address" in failed["error"]


def test_already_invited_candidates_are_skipped(client, auth_headers):
    job, ids = make_job_with_ranked(3)
    slots = plan(client, auth_headers, job, top=1).json()["slots"]
    client.post(f"/api/jobs/{job}/invite-batches", json={"items": [{"candidate_id": slots[0]["candidate_id"], "scheduled_at": slots[0]["scheduled_at"]}]}, headers=auth_headers)
    again = plan(client, auth_headers, job, top=3).json()
    assert [s["candidate_id"] for s in again["slots"]] == ids[1:]
    assert again["skipped"][0]["candidate_id"] == ids[0]
    assert again["skipped"][0]["reason"] == "Already has an interview booked."
    assert again["slots"][0]["scheduled_at"] != slots[0]["scheduled_at"]  # no clash with the first one


def test_an_out_of_date_plan_sends_nothing(client, auth_headers):
    job, ids = make_job_with_ranked(2)
    slots = plan(client, auth_headers, job, top=2).json()["slots"]
    same_time = [{"candidate_id": s["candidate_id"], "scheduled_at": slots[0]["scheduled_at"]} for s in slots]
    response = client.post(f"/api/jobs/{job}/invite-batches", json={"items": same_time}, headers=auth_headers)
    assert response.status_code == 409
    assert "clashes" in response.json()["detail"]
    with SessionLocal() as db:
        assert db.scalars(select(InterviewSession)).all() == []
    assert FakeSMTP.sent == []


def test_a_weekend_time_is_refused(client, auth_headers):
    job, ids = make_job_with_ranked(1)
    saturday = datetime.fromisoformat(next_monday()) + timedelta(days=5, hours=4)  # 10:00 in Dhaka
    item = {"candidate_id": ids[0], "scheduled_at": saturday.replace(tzinfo=timezone.utc).isoformat()}
    response = client.post(f"/api/jobs/{job}/invite-batches", json={"items": [item]}, headers=auth_headers)
    assert response.status_code == 409
    assert "not a working day" in response.json()["detail"]


def test_holidays_are_avoided(client, auth_headers):
    job, _ = make_job_with_ranked(1)
    client.post("/api/holidays", json={"holidays": [{"day": next_monday(), "name": "Test holiday"}]}, headers=auth_headers)
    slot = plan(client, auth_headers, job, top=1).json()["slots"][0]
    local = datetime.fromisoformat(slot["scheduled_at"]).astimezone(timezone(timedelta(minutes=settings.interview_utc_offset_minutes)))
    assert local.date().isoformat() != next_monday()


def test_a_failed_email_can_be_tried_again(client, auth_headers):
    job, _ = make_job_with_ranked(2)
    slots = plan(client, auth_headers, job, top=2).json()["slots"]
    items = [{"candidate_id": s["candidate_id"], "scheduled_at": s["scheduled_at"]} for s in slots]
    FakeSMTP.fail = True
    batch = client.post(f"/api/jobs/{job}/invite-batches", json={"items": items}, headers=auth_headers).json()
    assert client.get(f"/api/jobs/{job}/invite-batches/latest", headers=auth_headers).json()["failed"] == 2
    FakeSMTP.fail = False
    client.post(f"/api/jobs/{job}/invite-batches/{batch['id']}/retry", headers=auth_headers)
    assert client.get(f"/api/jobs/{job}/invite-batches/latest", headers=auth_headers).json()["sent"] == 2


def test_the_rules_are_shown(client, auth_headers):
    job, _ = make_job_with_ranked(1)
    rules = client.get(f"/api/jobs/{job}/invite-plan/rules", headers=auth_headers).json()
    assert rules["windows"] == ["09:00-12:00", "14:00-17:00"]
    assert rules["work_days"] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    assert rules["slots_per_day"] == 4


def test_inviting_needs_a_login(client):
    assert client.post("/api/jobs/1/invite-plan", json={"top": 1}).status_code == 401
    assert client.post("/api/jobs/1/invite-batches", json={"items": []}).status_code == 401
