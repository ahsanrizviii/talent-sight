"""Tests for running the CV claim check in the background and reading it back (Module 13, F8).

The agent's AI is a fake (see test_claim_agent.py), so no real model is ever called.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import claim_check
from app.agents import claim_agent
from app.db import SessionLocal
from app.models import Assessment, Candidate, ClaimCheck, InterviewEvaluation, InterviewSession, JobProfile
from tests.test_claim_agent import PROFILE, TURNS, FakeAI


@pytest.fixture(autouse=True)
def fake_ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(claim_agent, "ask", fake)
    return fake


def candidate(screened: bool = True, analysis: str | None = "done") -> int:
    """A screened candidate with a CV profile and an analysed interview (each can be left out)."""
    with SessionLocal() as db:
        job = JobProfile(title="Backend Developer", required_skills=["Python", "PostgreSQL"], preferred_skills=["Docker"])
        db.add(job)
        db.flush()
        person = Candidate(
            job_profile_id=job.id, name="Maya Rahman", cv_filename="cv.pdf",
            status="screened" if screened else "uploaded", profile=PROFILE if screened else {},
        )
        db.add(person)
        db.flush()
        now = datetime.now(timezone.utc)
        session = InterviewSession(
            candidate_id=person.id, scheduled_at=now, invite_token=f"token-{person.id}", invite_expires_at=now, status="ended", started_at=now,
        )
        db.add(session)
        db.flush()
        if analysis:
            db.add(InterviewEvaluation(session_id=session.id, status=analysis, result={"turns": TURNS, "pairs": []}, finished_at=now))
        db.commit()
        return person.id


def start(client, headers, candidate_id: int):
    return client.post(f"/api/candidates/{candidate_id}/claim-check", headers=headers)


def read(client, headers, candidate_id: int):
    return client.get(f"/api/candidates/{candidate_id}/claim-check", headers=headers).json()


def test_the_check_answers_at_once_and_runs_in_the_background(client, auth_headers):
    candidate_id = candidate()
    started = start(client, auth_headers, candidate_id)
    assert started.status_code == 202
    assert started.json()["status"] == "running" and started.json()["step"] == claim_check.FIRST_STEP

    done = read(client, auth_headers, candidate_id)  # the background work has finished by now
    assert done["status"] == "done" and done["error"] == "" and done["outdated"] is False
    assert [c["status"] for c in done["claims"]][:3] == ["contradicted", "unsubstantiated", "not_discussed"]
    assert done["summary"]["claims"] == 6 and done["summary"]["follow_ups"] == 3
    # Only the turns the claims point to are kept, and only the candidate's own.
    assert {t["n"] for t in done["turns"]} <= {2, 4, 6}


def test_nothing_is_there_before_anyone_asks(client, auth_headers):
    assert read(client, auth_headers, candidate()) is None


def test_the_check_needs_a_screened_cv(client, auth_headers):
    response = start(client, auth_headers, candidate(screened=False))
    assert response.status_code == 400 and response.json()["detail"] == claim_check.NOT_SCREENED


def test_the_check_needs_analysed_interview_answers(client, auth_headers):
    for analysis in (None, "running", "failed"):
        response = start(client, auth_headers, candidate(analysis=analysis))
        assert response.status_code == 400 and response.json()["detail"] == claim_check.NOT_ANALYSED


def test_the_check_never_touches_the_score_or_the_assessment(client, auth_headers):
    candidate_id = candidate()
    start(client, auth_headers, candidate_id)
    with SessionLocal() as db:
        assert db.scalar(select(Assessment).where(Assessment.candidate_id == candidate_id)) is None
        assert db.get(Candidate, candidate_id).status == "screened"


def test_checking_again_replaces_the_old_result(client, auth_headers, fake_ai):
    candidate_id = candidate()
    start(client, auth_headers, candidate_id)
    fake_ai.says = {k: {**v, "status": "not_discussed", "turn": 0, "quote": ""} for k, v in fake_ai.says.items()}
    start(client, auth_headers, candidate_id)
    done = read(client, auth_headers, candidate_id)
    assert done["summary"]["not_discussed"] == 6
    with SessionLocal() as db:
        assert len(db.scalars(select(ClaimCheck).where(ClaimCheck.candidate_id == candidate_id)).all()) == 1


def test_a_failed_ai_is_shown_as_a_failed_check(client, auth_headers, fake_ai):
    fake_ai.broken = True
    candidate_id = candidate()
    start(client, auth_headers, candidate_id)
    done = read(client, auth_headers, candidate_id)
    assert done["status"] == "failed" and "not available" in done["error"] and done["claims"] == []


def test_a_running_check_cannot_be_started_twice(client, auth_headers):
    candidate_id = candidate()
    with SessionLocal() as db:
        db.add(ClaimCheck(candidate_id=candidate_id, status="running"))
        db.commit()
    assert start(client, auth_headers, candidate_id).status_code == 409


def test_the_check_is_outdated_when_the_answers_are_analysed_again(client, auth_headers):
    candidate_id = candidate()
    start(client, auth_headers, candidate_id)
    with SessionLocal() as db:
        evaluation = db.scalar(select(InterviewEvaluation).join(InterviewSession).where(InterviewSession.candidate_id == candidate_id))
        evaluation.finished_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        db.commit()
    assert read(client, auth_headers, candidate_id)["outdated"] is True


def test_a_check_cut_off_by_a_restart_is_marked_failed(client, auth_headers):
    candidate_id = candidate()
    with SessionLocal() as db:
        db.add(ClaimCheck(candidate_id=candidate_id, status="running", step="Comparing"))
        db.commit()
    claim_check.mark_interrupted_checks()
    done = read(client, auth_headers, candidate_id)
    assert done["status"] == "failed" and done["error"] == claim_check.INTERRUPTED


def test_an_unknown_candidate_is_not_found(client, auth_headers):
    assert start(client, auth_headers, 9999).status_code == 404
    assert client.get("/api/candidates/9999/claim-check", headers=auth_headers).status_code == 404


def test_the_check_needs_a_login(client):
    assert client.post("/api/candidates/1/claim-check").status_code == 401
    assert client.get("/api/candidates/1/claim-check").status_code == 401