"""Tests for running the answer analysis in the background and reading it back (Task 9.2.2).

The agent's AI is a fake (see test_evaluation_agent.py), so no real model is ever called.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app import evaluation
from app.agents import evaluation_agent
from app.db import SessionLocal
from app.models import Candidate, InterviewEvaluation, InterviewSession, JobProfile, TranscriptSegment
from tests.test_evaluation_agent import REFERENCE, TRANSCRIPT, FakeAI


@pytest.fixture(autouse=True)
def fake_ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(evaluation_agent, "ask", fake)
    monkeypatch.setattr(evaluation_agent, "find_references", lambda question: [REFERENCE])
    return fake


def interview(status: str = "ended", lines=TRANSCRIPT) -> int:
    """A candidate for a job with three requirements, and their interview with a saved transcript."""
    with SessionLocal() as db:
        job = JobProfile(title="Backend Developer", required_skills=["Python", "PostgreSQL"], preferred_skills=["Kubernetes"])
        db.add(job)
        db.flush()
        candidate = Candidate(job_profile_id=job.id, name="Maya Rahman", cv_filename="cv.pdf", status="screened")
        db.add(candidate)
        db.flush()
        now = datetime.now(timezone.utc)
        session = InterviewSession(
            candidate_id=candidate.id, scheduled_at=now, invite_token=f"token-{candidate.id}",
            invite_expires_at=now, status=status, started_at=now,
        )
        db.add(session)
        db.flush()
        for line in lines:
            db.add(TranscriptSegment(session_id=session.id, **line))
        db.commit()
        return session.id


def analyse(client, headers, session_id: int):
    return client.post(f"/api/interviews/{session_id}/evaluation", headers=headers)


def read(client, headers, session_id: int) -> dict | None:
    return client.get(f"/api/interviews/{session_id}/evaluation", headers=headers).json()


def test_the_analysis_answers_at_once_and_runs_in_the_background(client, auth_headers):
    session_id = interview()
    started = analyse(client, auth_headers, session_id)
    assert started.status_code == 202
    assert started.json()["status"] == "running" and started.json()["step"] == evaluation.FIRST_STEP

    done = read(client, auth_headers, session_id)  # the background work has finished by now
    assert done["status"] == "done" and done["step"] == "" and done["error"] == ""
    assert [p["question"] for p in done["pairs"]] == [
        "Hi Maya, can you hear me?",
        "What is a Python generator?",
        "When would you use a generator?",
        "How do you index a PostgreSQL table?",
    ]
    assert [c["status"] for c in done["coverage"]] == ["explored", "explored", "not_explored"]
    assert done["summary"] == {
        "pairs": 4, "job_related": 3, "small_talk": 1, "scored": 3,
        "average": 80, "not_explored": 1, "weak": 0,
    }
    assert len(done["turns"]) == 8 and done["seconds"] is not None


def test_nothing_is_there_before_anyone_asks(client, auth_headers):
    assert read(client, auth_headers, interview()) is None


def test_only_an_ended_interview_with_a_transcript_can_be_analysed(client, auth_headers):
    live = analyse(client, auth_headers, interview(status="live"))
    assert live.status_code == 400 and live.json()["detail"] == "Analyse the answers after the interview has ended."
    silent = analyse(client, auth_headers, interview(lines=[]))
    assert silent.status_code == 400 and silent.json()["detail"] == "This interview has no transcript to analyse."
    assert analyse(client, auth_headers, 999999).status_code == 404


def test_one_analysis_at_a_time(client, auth_headers, monkeypatch):
    monkeypatch.setattr(evaluation, "run_evaluation", lambda evaluation_id: None)  # keep it "running"
    session_id = interview()
    assert analyse(client, auth_headers, session_id).status_code == 202
    again = analyse(client, auth_headers, session_id)
    assert again.status_code == 409 and again.json()["detail"] == "The answers are already being analysed."


def test_running_it_again_replaces_the_old_result(client, auth_headers, fake_ai):
    session_id = interview()
    analyse(client, auth_headers, session_id)
    fake_ai.kinds = {1: "small_talk", 4: "small_talk"}
    analyse(client, auth_headers, session_id)
    second = read(client, auth_headers, session_id)
    assert second["summary"]["small_talk"] == 2
    with SessionLocal() as db:
        assert len(db.scalars(select(InterviewEvaluation)).all()) == 1  # still one row per interview


def test_progress_is_shown_step_by_step(client, auth_headers, monkeypatch):
    steps: list[str] = []
    monkeypatch.setattr(evaluation, "set_step", lambda evaluation_id, step: steps.append(step))
    analyse(client, auth_headers, interview())
    assert steps == list(evaluation.NEXT_STEP.values())


def test_an_ai_failure_is_stored_with_its_message(client, auth_headers, monkeypatch):
    monkeypatch.setattr(evaluation_agent, "ask", FakeAI(broken={evaluation_agent.Segmentation}))
    session_id = interview()
    analyse(client, auth_headers, session_id)
    failed = read(client, auth_headers, session_id)
    assert failed["status"] == "failed"
    assert failed["error"] == "The AI service is not available right now. Please try again."
    assert failed["pairs"] == []


def test_a_crash_never_leaves_the_analysis_running(client, auth_headers, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(evaluation_agent, "ask", broken)
    session_id = interview()
    analyse(client, auth_headers, session_id)
    assert read(client, auth_headers, session_id)["error"] == evaluation.CRASHED


def test_a_restart_marks_an_unfinished_analysis_as_failed(client, auth_headers, monkeypatch):
    monkeypatch.setattr(evaluation, "run_evaluation", lambda evaluation_id: None)
    session_id = interview()
    analyse(client, auth_headers, session_id)
    evaluation.mark_interrupted_evaluations()
    row = read(client, auth_headers, session_id)
    assert row["status"] == "failed" and row["error"] == evaluation.INTERRUPTED


def test_the_analysis_is_for_interviewers_only(client, auth_headers):
    session_id = interview()
    assert client.post(f"/api/interviews/{session_id}/evaluation").status_code == 401
    assert client.get(f"/api/interviews/{session_id}/evaluation").status_code == 401
    with SessionLocal() as db:
        invite = db.get(InterviewSession, session_id).invite_token
    # The candidate's private link is no key to their own scores (N9).
    assert client.get(f"/api/interviews/{session_id}/evaluation", headers={"Authorization": f"Bearer {invite}"}).status_code == 401


def test_deleting_the_candidate_deletes_the_analysis(client, auth_headers):
    session_id = interview()
    analyse(client, auth_headers, session_id)
    with SessionLocal() as db:
        candidate_id = db.get(InterviewSession, session_id).candidate_id
    assert client.delete(f"/api/candidates/{candidate_id}", headers=auth_headers).status_code == 204
    with SessionLocal() as db:
        assert db.scalars(select(InterviewEvaluation)).all() == []  # N19