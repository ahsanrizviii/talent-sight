"""Tests for running the consolidated assessment in the background and reading it back (Task 10.1.2).

The agent's AI is a fake (see test_assessment_agent.py), so no real model is ever called.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import assessment
from app.agents import assessment_agent
from app.db import SessionLocal
from app.models import (
    Assessment,
    Candidate,
    CandidateScore,
    InterviewEvaluation,
    InterviewSession,
    JobProfile,
    RequirementVerdict,
)
from tests.test_assessment_agent import ANALYSIS, VERDICTS, FakeAI


@pytest.fixture(autouse=True)
def fake_ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(assessment_agent, "ask", fake)
    return fake


def candidate(scored: bool = True, analysis: str | None = "done", name: str = "Maya Rahman") -> int:
    """A screened candidate with verdicts, a CV score and an analysed interview (each can be left out)."""
    with SessionLocal() as db:
        job = db.scalar(select(JobProfile).where(JobProfile.title == "Backend Developer"))
        if job is None:
            job = JobProfile(title="Backend Developer", required_skills=["Python", "PostgreSQL"], preferred_skills=["Docker", "Kubernetes"])
            db.add(job)
            db.flush()
        person = Candidate(job_profile_id=job.id, name=name, cv_filename="cv.pdf", status="screened" if scored else "uploaded")
        db.add(person)
        db.flush()
        if scored:
            for verdict in VERDICTS:
                db.add(RequirementVerdict(candidate_id=person.id, **verdict))
            db.add(CandidateScore(
                candidate_id=person.id, technical_skills=80, experience=70, qualifications=60, jd_match=70, overall=72.5,
                justification={"technical_skills": "Python and Docker."},
            ))
        now = datetime.now(timezone.utc)
        session = InterviewSession(
            candidate_id=person.id, scheduled_at=now, invite_token=f"token-{person.id}",
            invite_expires_at=now, status="ended", started_at=now,
        )
        db.add(session)
        db.flush()
        if analysis:
            db.add(InterviewEvaluation(session_id=session.id, status=analysis, result=ANALYSIS if analysis == "done" else {}, finished_at=now))
        db.commit()
        return person.id


def assess(client, headers, candidate_id: int):
    return client.post(f"/api/candidates/{candidate_id}/assessment", headers=headers)


def read(client, headers, candidate_id: int) -> dict | None:
    return client.get(f"/api/candidates/{candidate_id}/assessment", headers=headers).json()


def test_the_assessment_answers_at_once_and_runs_in_the_background(client, auth_headers):
    candidate_id = candidate()
    started = assess(client, auth_headers, candidate_id)
    assert started.status_code == 202
    assert started.json()["status"] == "running" and started.json()["step"] == assessment.FIRST_STEP

    done = read(client, auth_headers, candidate_id)  # the background work has finished by now
    assert done["status"] == "done" and done["error"] == "" and done["outdated"] is False
    report = done["report"]
    assert report["candidate"]["name"] == "Maya Rahman" and report["job"]["title"] == "Backend Developer"
    assert report["position"]["code"] == "possible_fit" and report["position"]["overall"] == 61.6
    assert [c["key"] for c in report["components"]] == ["cv_score", "requirements", "answers", "coverage"]
    assert report["strengths"][0]["evidence"] == ["Q2", "R1"]
    assert report["interview"]["session_id"] and done["seconds"] is not None
    with SessionLocal() as db:
        assert db.scalar(select(Assessment.overall_position)) == "possible_fit"


def test_the_cv_score_uses_the_jobs_weights(client, auth_headers, fake_ai):
    candidate_id = candidate()
    assess(client, auth_headers, candidate_id)
    assert "[S1] (CV) CV score, Technical skills: 80/100: Python and Docker." in fake_ai.prompts[0]


def test_nothing_is_there_before_anyone_asks(client, auth_headers):
    assert read(client, auth_headers, candidate()) is None


def test_the_candidate_must_be_screened_and_scored(client, auth_headers):
    refused = assess(client, auth_headers, candidate(scored=False))
    assert refused.status_code == 400 and refused.json()["detail"] == assessment.NOT_SCORED


def test_the_interview_answers_must_be_analysed(client, auth_headers):
    for analysis in (None, "failed", "running"):
        refused = assess(client, auth_headers, candidate(analysis=analysis))
        assert refused.status_code == 400 and refused.json()["detail"] == assessment.NOT_ANALYSED
    assert assess(client, auth_headers, 999999).status_code == 404


def test_one_assessment_at_a_time(client, auth_headers, monkeypatch):
    monkeypatch.setattr(assessment, "run_assessment", lambda assessment_id: None)  # keep it "running"
    candidate_id = candidate()
    assert assess(client, auth_headers, candidate_id).status_code == 202
    again = assess(client, auth_headers, candidate_id)
    assert again.status_code == 409 and again.json()["detail"] == "This candidate is already being assessed."


def test_assessing_again_replaces_the_old_report(client, auth_headers, monkeypatch):
    candidate_id = candidate()
    assess(client, auth_headers, candidate_id)
    better = {**ANALYSIS, "summary": {"average": 95}}
    with SessionLocal() as db:
        db.scalar(select(InterviewEvaluation)).result = better
        db.commit()
    assess(client, auth_headers, candidate_id)
    assert read(client, auth_headers, candidate_id)["report"]["position"]["overall"] == 74.8
    with SessionLocal() as db:
        assert len(db.scalars(select(Assessment)).all()) == 1  # still one row per candidate


def test_progress_is_shown_step_by_step(client, auth_headers, monkeypatch):
    steps: list[str] = []
    monkeypatch.setattr(assessment, "set_step", lambda assessment_id, step: steps.append(step))
    assess(client, auth_headers, candidate())
    assert steps == list(assessment.NEXT_STEP.values())


def test_an_ai_failure_is_stored_with_its_message(client, auth_headers, monkeypatch):
    monkeypatch.setattr(assessment_agent, "ask", FakeAI(broken=True))
    candidate_id = candidate()
    assess(client, auth_headers, candidate_id)
    failed = read(client, auth_headers, candidate_id)
    assert failed["status"] == "failed"
    assert failed["error"] == "The AI service is not available right now. Please try again."
    assert failed["report"] == {}


def test_a_crash_never_leaves_the_assessment_running(client, auth_headers, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(assessment_agent, "ask", broken)
    candidate_id = candidate()
    assess(client, auth_headers, candidate_id)
    assert read(client, auth_headers, candidate_id)["error"] == assessment.CRASHED


def test_a_restart_marks_an_unfinished_assessment_as_failed(client, auth_headers, monkeypatch):
    monkeypatch.setattr(assessment, "run_assessment", lambda assessment_id: None)
    candidate_id = candidate()
    assess(client, auth_headers, candidate_id)
    assessment.mark_interrupted_assessments()
    row = read(client, auth_headers, candidate_id)
    assert row["status"] == "failed" and row["error"] == assessment.INTERRUPTED


def test_a_newer_answer_analysis_marks_the_report_outdated(client, auth_headers):
    candidate_id = candidate()
    assess(client, auth_headers, candidate_id)
    with SessionLocal() as db:
        db.scalar(select(InterviewEvaluation)).finished_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        db.commit()
    assert read(client, auth_headers, candidate_id)["outdated"] is True


def test_the_assessment_is_for_interviewers_only(client, auth_headers):
    candidate_id = candidate()
    assert client.post(f"/api/candidates/{candidate_id}/assessment").status_code == 401
    assert client.get(f"/api/candidates/{candidate_id}/assessment").status_code == 401
    with SessionLocal() as db:
        invite = db.scalar(select(InterviewSession.invite_token))
    # The candidate's private link is no key to their own assessment (N9).
    headers = {"Authorization": f"Bearer {invite}"}
    assert client.get(f"/api/candidates/{candidate_id}/assessment", headers=headers).status_code == 401


def test_deleting_the_candidate_deletes_the_assessment(client, auth_headers):
    candidate_id = candidate()
    assess(client, auth_headers, candidate_id)
    assert client.delete(f"/api/candidates/{candidate_id}", headers=auth_headers).status_code == 204
    with SessionLocal() as db:
        assert db.scalars(select(Assessment)).all() == []  # N19