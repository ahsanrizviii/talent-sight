"""Tests for the Interview Quality Agent and its API (Module 13, F10). The AI is a fake."""

from datetime import datetime, timezone

import pytest

from app import agent_runs
from app.agents import quality_agent as agent
from app.agents.quality_agent import Review
from app.db import SessionLocal
from app.llm import LLMUnavailable
from app.models import Candidate, InterviewEvaluation, InterviewQuality, InterviewSession, JobProfile

JOB = {"title": "Backend Developer", "requirements": ["Python", "PostgreSQL", "Docker"]}

TURNS = [
    {"n": 1, "speaker": "interviewer", "text": "Hi Maya, how are you today?", "start_ms": 0, "end_ms": 3000},
    {"n": 2, "speaker": "candidate", "text": "I'm fine, thank you.", "start_ms": 3500, "end_ms": 5000},
    {"n": 3, "speaker": "interviewer", "text": "Tell me about the payment APIs you built in Python.", "start_ms": 6000, "end_ms": 10000},
    {"n": 4, "speaker": "candidate", "text": "I designed the refund flow in FastAPI and moved the slow parts to Celery workers, which cut the response time in half.", "start_ms": 11000, "end_ms": 41000},
    {"n": 5, "speaker": "interviewer", "text": "You know PostgreSQL, right?", "start_ms": 42000, "end_ms": 44000},
    {"n": 6, "speaker": "candidate", "text": "Yes.", "start_ms": 45000, "end_ms": 46000},
]


def scores(*values: int) -> dict:
    return {name: {"score": value, "justification": "-"} for name, value in zip(("relevance", "accuracy", "completeness", "articulation"), values)}


PAIRS = [
    {"id": 1, "question": "How are you today?", "turns": [1, 2], "answer_turns": [2], "follow_ups": [], "start_ms": 0,
     "kind": "small_talk", "requirements": [], "scores": {}, "overall": None},
    {"id": 2, "question": "Tell me about the payment APIs you built in Python.", "turns": [3, 4], "answer_turns": [4],
     "follow_ups": ["What did you move to Celery?"], "start_ms": 6000, "kind": "job_related", "requirements": [1],
     "scores": scores(85, 80, 75, 80), "overall": 80},
    {"id": 3, "question": "You know PostgreSQL, right?", "turns": [5, 6], "answer_turns": [6], "follow_ups": [], "start_ms": 42000,
     "kind": "job_related", "requirements": [2], "scores": scores(40, 50, 20, 60), "overall": 42.5},
]

COVERAGE = [
    {"number": 1, "requirement": "Python", "kind": "skill", "mandatory": True, "pairs": [2], "best_score": 80, "status": "explored"},
    {"number": 2, "requirement": "PostgreSQL", "kind": "skill", "mandatory": True, "pairs": [3], "best_score": 42.5, "status": "weak"},
    {"number": 3, "requirement": "Docker", "kind": "skill", "mandatory": False, "pairs": [], "best_score": None, "status": "not_explored"},
]

GOOD_REVIEW = {
    "summary": "A short, friendly interview. PostgreSQL was asked as a yes/no question.",
    "questions": [{"id": 2, "kind": "open", "note": "Invites detail."}, {"id": 3, "kind": "leading", "note": "Suggests the answer."}],
    "recommendations": [
        {"text": "Ask an open question about PostgreSQL instead of a yes/no one.", "turn": 5},
        {"text": "Leave time for Docker, which was not explored.", "turn": 0},
    ],
}


class FakeAI:
    """Gives the prepared answers in turn (the last one again when they run out) and remembers the prompts."""

    def __init__(self, *answers, broken: bool = False):
        self.answers = list(answers) or [GOOD_REVIEW]
        self.broken = broken
        self.prompts: list[str] = []

    def __call__(self, system_prompt: str, user_prompt: str, answer_shape):
        assert answer_shape is Review
        self.prompts.append(user_prompt)
        if self.broken:
            raise LLMUnavailable("The AI service is not available right now. Please try again.")
        return Review(**self.answers[min(len(self.prompts), len(self.answers)) - 1])


@pytest.fixture(autouse=True)
def fake_ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(agent, "ask", fake)
    return fake


def run_agent(turns=None, others=None) -> dict:
    return agent.get_quality_agent().invoke(
        {"job": JOB, "turns": TURNS if turns is None else turns, "pairs": PAIRS, "coverage": COVERAGE, "others": others or []}
    )


def analysed_interview(job_id: int | None = None, analysed: bool = True) -> int:
    """An ended interview whose answers were analysed (Module 9). Returns the interview's id."""
    with SessionLocal() as db:
        if job_id is None:
            job = JobProfile(title="Backend Developer", required_skills=["Python", "PostgreSQL"], preferred_skills=["Docker"])
            db.add(job)
            db.flush()
            job_id = job.id
        person = Candidate(job_profile_id=job_id, name="Maya Rahman", cv_filename="cv.pdf", status="screened", profile={})
        db.add(person)
        db.flush()
        now = datetime.now(timezone.utc)
        session = InterviewSession(
            candidate_id=person.id, scheduled_at=now, invite_token=f"token-{person.id}", invite_expires_at=now, status="ended", started_at=now,
        )
        db.add(session)
        db.flush()
        if analysed:
            db.add(InterviewEvaluation(session_id=session.id, status="done", result={"turns": TURNS, "pairs": PAIRS, "coverage": COVERAGE}, finished_at=now))
        db.commit()
        return session.id


def job_of(session_id: int) -> int:
    with SessionLocal() as db:
        return db.get(Candidate, db.get(InterviewSession, session_id).candidate_id).job_profile_id


# ---------- the agent ----------
def test_the_measures_come_from_plain_code():
    assert run_agent()["measures"] == {
        "minutes": 0.8, "interviewer_talk_pct": 22, "questions": 2, "small_talk": 1, "follow_ups": 1,
        "longest_answer_s": 30, "average_answer_s": 11, "requirements": 3, "explored": 1, "weak": 1,
        "not_explored": 1, "coverage_pct": 33,
    }


def test_a_personal_question_from_the_interviewer_is_flagged():
    turns = TURNS + [{"n": 7, "speaker": "interviewer", "text": "Are you married?", "start_ms": 47000, "end_ms": 48000}]
    assert run_agent(turns=turns)["personal"] == [{"turn": 7, "at": "00:47", "text": "Are you married?"}]


def test_each_job_question_gets_its_kind():
    questions = run_agent()["questions"]
    assert [(q["id"], q["kind"], q["label"], q["at"]) for q in questions] == [(2, "open", "Open", "00:06"), (3, "leading", "Leading", "00:42")]


def test_a_question_the_ai_skipped_is_shown_as_not_rated(monkeypatch):
    monkeypatch.setattr(agent, "ask", FakeAI({**GOOD_REVIEW, "questions": GOOD_REVIEW["questions"][:1]}))
    assert run_agent()["questions"][1]["label"] == "Not rated"


def test_recommendations_point_to_a_turn_or_the_whole_interview():
    assert run_agent()["recommendations"] == [
        {"text": "Ask an open question about PostgreSQL instead of a yes/no one.", "turn": 5, "at": "00:42"},
        {"text": "Leave time for Docker, which was not explored.", "turn": None, "at": None},
    ]


def test_a_recommendation_about_a_missing_turn_is_sent_back_once(monkeypatch):
    bad = {**GOOD_REVIEW, "recommendations": [{"text": "Slow down at the end.", "turn": 99}]}
    fake = FakeAI(bad, GOOD_REVIEW)
    monkeypatch.setattr(agent, "ask", fake)
    state = run_agent()
    assert len(fake.prompts) == 2 and "does not exist" in fake.prompts[1]
    assert len(state["recommendations"]) == 2


def test_other_interviews_for_the_job_are_averaged():
    others = [
        {"interviewer_talk_pct": 40, "questions": 6, "follow_ups": 3, "coverage_pct": 80, "minutes": 30},
        {"interviewer_talk_pct": 60, "questions": 4, "follow_ups": 1, "coverage_pct": 60, "minutes": 20},
    ]
    compare = run_agent(others=others)["compare"]
    assert compare == {"interviews": 2, "average": {"interviewer_talk_pct": 50.0, "questions": 5.0, "follow_ups": 2.0, "coverage_pct": 70.0, "minutes": 25.0}}


def test_an_empty_transcript_stops_with_a_clear_error(fake_ai):
    assert "no transcript" in run_agent(turns=[])["error"]
    assert fake_ai.prompts == []


def test_an_unavailable_ai_gives_an_error_state(monkeypatch):
    monkeypatch.setattr(agent, "ask", FakeAI(broken=True))
    assert run_agent()["error"] == "The AI service is not available right now. Please try again."


# ---------- the API ----------
def test_the_review_runs_in_the_background_and_is_kept(client, auth_headers):
    session_id = analysed_interview()
    started = client.post(f"/api/interviews/{session_id}/quality", headers=auth_headers)
    assert started.status_code == 202 and started.json()["status"] == "running"
    done = client.get(f"/api/interviews/{session_id}/quality", headers=auth_headers).json()
    assert done["status"] == "done" and done["outdated"] is False
    assert done["result"]["measures"]["questions"] == 2
    assert done["result"]["kinds"] == {"open": 1, "leading": 1}


def test_a_second_interview_for_the_job_is_compared_with_the_first(client, auth_headers):
    first = analysed_interview()
    second = analysed_interview(job_id=job_of(first))
    client.post(f"/api/interviews/{first}/quality", headers=auth_headers)
    client.post(f"/api/interviews/{second}/quality", headers=auth_headers)
    compare = client.get(f"/api/interviews/{second}/quality", headers=auth_headers).json()["result"]["compare"]
    assert compare["interviews"] == 1 and compare["average"]["questions"] == 2.0


def test_the_review_needs_analysed_answers(client, auth_headers):
    response = client.post(f"/api/interviews/{analysed_interview(analysed=False)}/quality", headers=auth_headers)
    assert response.status_code == 400 and response.json()["detail"] == agent_runs.NOT_ANALYSED


def test_nothing_is_there_before_anyone_asks(client, auth_headers):
    assert client.get(f"/api/interviews/{analysed_interview()}/quality", headers=auth_headers).json() is None


def test_a_failed_ai_is_shown_as_a_failed_review(client, auth_headers, fake_ai):
    fake_ai.broken = True
    session_id = analysed_interview()
    client.post(f"/api/interviews/{session_id}/quality", headers=auth_headers)
    done = client.get(f"/api/interviews/{session_id}/quality", headers=auth_headers).json()
    assert done["status"] == "failed" and "not available" in done["error"]


def test_a_review_cut_off_by_a_restart_is_marked_failed(client, auth_headers):
    session_id = analysed_interview()
    with SessionLocal() as db:
        db.add(InterviewQuality(session_id=session_id, status="running", step="Reviewing"))
        db.commit()
    assert client.post(f"/api/interviews/{session_id}/quality", headers=auth_headers).status_code == 409
    agent_runs.mark_interrupted(InterviewQuality)
    done = client.get(f"/api/interviews/{session_id}/quality", headers=auth_headers).json()
    assert done["status"] == "failed" and done["error"] == agent_runs.INTERRUPTED


def test_unknown_interviews_and_missing_logins_are_refused(client, auth_headers):
    assert client.post("/api/interviews/9999/quality", headers=auth_headers).status_code == 404
    assert client.get("/api/interviews/1/quality").status_code == 401