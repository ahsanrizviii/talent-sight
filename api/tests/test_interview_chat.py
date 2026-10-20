"""Tests for the question chat API in the interview room (Module 13). The AI is a fake."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.agents import chat_agent
from app.db import SessionLocal
from app.models import Candidate, InterviewChatMessage, InterviewEvaluation, InterviewSession, JobProfile, TranscriptSegment
from tests.test_chat_agent import PROFILE, FakeAI

ASK = {"question": "Which Kubernetes objects did you write yourself?", "why": "Shows hands-on depth.", "source": "T2"}


@pytest.fixture(autouse=True)
def fake_ai(monkeypatch):
    fake = FakeAI({"reply": "Probe their Kubernetes use.", "suggestions": [ASK]})
    monkeypatch.setattr(chat_agent, "ask", fake)
    return fake


def interview(status: str = "live", said: bool = True) -> int:
    with SessionLocal() as db:
        job = JobProfile(title="Backend Developer", required_skills=["Python", "Kubernetes"])
        db.add(job)
        db.flush()
        person = Candidate(job_profile_id=job.id, name="Maya Rahman", cv_filename="cv.pdf", status="screened", profile=PROFILE)
        db.add(person)
        db.flush()
        now = datetime.now(timezone.utc)
        session = InterviewSession(candidate_id=person.id, scheduled_at=now, invite_token=f"token-{person.id}", invite_expires_at=now, status=status)
        db.add(session)
        db.flush()
        if said:
            db.add(TranscriptSegment(session_id=session.id, speaker="interviewer", text="Have you used Kubernetes?", start_ms=0, end_ms=2000))
            db.add(TranscriptSegment(session_id=session.id, speaker="candidate", text="A little, we ran a few services on it.", start_ms=3000, end_ms=8000))
        db.commit()
        return session.id


def send(client, headers, session_id: int, message: str = "What should I ask about Kubernetes?"):
    return client.post(f"/api/interviews/{session_id}/chat", headers=headers, json={"message": message})


def test_a_message_gets_a_reply_with_sourced_suggestions(client, auth_headers):
    session_id = interview()
    response = send(client, auth_headers, session_id)
    assert response.status_code == 200
    body = response.json()
    assert body["question"]["role"] == "interviewer" and body["question"]["text"] == "What should I ask about Kubernetes?"
    assert body["answer"]["role"] == "assistant" and body["answer"]["text"] == "Probe their Kubernetes use."
    [suggestion] = body["answer"]["suggestions"]
    assert suggestion["question"] == ASK["question"]
    assert suggestion["source"] == {
        "id": "T2", "kind": "transcript", "text": "A little, we ran a few services on it.", "turn": 2, "at": "00:03", "speaker": "candidate",
    }


def test_the_live_transcript_and_the_cv_are_in_the_prompt(client, auth_headers, fake_ai):
    send(client, auth_headers, interview())
    prompt = fake_ai.prompts[0]
    assert "[T2, 00:03] Candidate: A little, we ran a few services on it." in prompt
    assert "[C1] Backend Engineer at Acme" in prompt
    assert "[R2] Kubernetes (mentioned)" in prompt


def test_after_the_analysis_its_coverage_is_used(client, auth_headers, fake_ai):
    session_id = interview(status="ended")
    with SessionLocal() as db:
        coverage = [{"requirement": "Python", "status": "not_explored"}, {"requirement": "Kubernetes", "status": "weak"}]
        db.add(InterviewEvaluation(session_id=session_id, status="done", result={"coverage": coverage}, finished_at=datetime.now(timezone.utc)))
        db.commit()
    send(client, auth_headers, session_id)
    assert "[R1] Python (not explored)" in fake_ai.prompts[0] and "[R2] Kubernetes (weak)" in fake_ai.prompts[0]


def test_before_the_interview_it_works_from_the_cv(client, auth_headers, fake_ai):
    fake_ai.answers = [{"reply": "Start with their payments work.", "suggestions": [{"question": "What did the payment APIs do?", "why": "-", "source": "C1"}]}]
    assert send(client, auth_headers, interview(status="scheduled", said=False)).status_code == 200
    assert "(nothing said yet)" in fake_ai.prompts[0]


def test_the_chat_is_kept_per_interview_oldest_first(client, auth_headers, fake_ai):
    session_id, other = interview(), interview()
    send(client, auth_headers, session_id, "First?")
    send(client, auth_headers, session_id, "Second?")
    send(client, auth_headers, other, "Elsewhere?")
    chat = client.get(f"/api/interviews/{session_id}/chat", headers=auth_headers).json()
    assert [(m["role"], m["text"]) for m in chat][::2] == [("interviewer", "First?"), ("interviewer", "Second?")]
    assert len(chat) == 4
    assert "Interviewer: First?" in fake_ai.prompts[1]  # the second message sees the first


def test_an_unavailable_ai_gives_a_clear_error_and_saves_nothing(client, auth_headers, fake_ai):
    fake_ai.broken = True
    session_id = interview()
    response = send(client, auth_headers, session_id)
    assert response.status_code == 503 and "not available" in response.json()["detail"]
    with SessionLocal() as db:
        assert db.scalars(select(InterviewChatMessage)).all() == []


@pytest.mark.parametrize("message", ["", "   ", "x" * 1001])
def test_empty_or_very_long_messages_are_refused(client, auth_headers, message):
    assert send(client, auth_headers, interview(), message).status_code == 422


def test_an_unknown_interview_is_not_found(client, auth_headers):
    assert send(client, auth_headers, 9999).status_code == 404
    assert client.get("/api/interviews/9999/chat", headers=auth_headers).status_code == 404


def test_the_chat_needs_an_interviewer_login(client):
    assert client.post("/api/interviews/1/chat", json={"message": "Hi"}).status_code == 401
    assert client.get("/api/interviews/1/chat").status_code == 401


def test_logs_never_contain_what_was_typed(client, auth_headers, caplog):
    send(client, auth_headers, interview(), "Secret wording about Kubernetes")
    assert "Secret wording" not in caplog.text