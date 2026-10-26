"""Tests for the Interview Scoring Agent and its API (Module 13, F9). The AI is a fake."""

import pytest

from app import agent_runs
from app.agents import interview_score_agent as agent
from app.agents.interview_score_agent import InterviewScores
from app.llm import LLMUnavailable
from tests.test_interview_quality import COVERAGE, JOB, PAIRS, TURNS, analysed_interview

GOOD = {"scores": [
    {"dimension": "technical", "score": 70, "reason": "Explained the refund flow.", "turn": 4},
    {"dimension": "problem_solving", "score": 66, "reason": "Moved slow work to Celery.", "turn": 4},
    {"dimension": "depth", "score": 60, "reason": "One project in detail.", "turn": 4},
    {"dimension": "relevance", "score": 75, "reason": "Answers stayed on topic.", "turn": 6},
    {"dimension": "communication", "score": 80, "reason": "Clear and short.", "turn": 4},
]}


class FakeAI:
    def __init__(self, *answers, broken: bool = False):
        self.answers = list(answers) or [GOOD]
        self.broken = broken
        self.prompts: list[str] = []

    def __call__(self, system_prompt: str, user_prompt: str, answer_shape):
        assert answer_shape is InterviewScores
        self.prompts.append(user_prompt)
        if self.broken:
            raise LLMUnavailable("The AI service is not available right now. Please try again.")
        return InterviewScores(**self.answers[min(len(self.prompts), len(self.answers)) - 1])


@pytest.fixture(autouse=True)
def fake_ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(agent, "ask", fake)
    return fake


def run_agent(pairs=None) -> dict:
    return agent.get_interview_score_agent().invoke({"job": JOB, "turns": TURNS, "pairs": PAIRS if pairs is None else pairs, "coverage": COVERAGE})


def with_part(key: str, **change) -> dict:
    return {"scores": [{**item, **change} if item["dimension"] == key else item for item in GOOD["scores"]]}


def test_six_parts_with_fixed_weights_and_a_plain_code_total():
    state = run_agent()
    parts = {d["key"]: d for d in state["dimensions"]}
    assert [d["key"] for d in state["dimensions"]] == ["technical", "problem_solving", "depth", "relevance", "communication", "alignment"]
    assert sum(d["weight"] for d in state["dimensions"]) == 100
    assert parts["problem_solving"]["score"] == 65  # steps of 5
    assert state["overall"] == 67.8  # (70*25 + 65*20 + 60*15 + 75*15 + 80*10 + 60*15) / 100
    assert state["answers"] == 2


def test_alignment_comes_from_coverage_with_required_ones_counting_double():
    alignment = run_agent()["dimensions"][-1]
    assert alignment["by"] == "code" and alignment["score"] == 60  # (2*100 + 2*50 + 1*0) / 5
    assert alignment["reason"] == "1 of 3 requirements explored and 1 weakly; required ones count double."


def test_each_ai_part_shows_the_answer_it_rests_on():
    technical = run_agent()["dimensions"][0]
    assert technical["by"] == "ai"
    assert technical["evidence"] == {"turn": 4, "at": "00:11", "text": TURNS[3]["text"]}


def test_a_part_resting_on_small_talk_is_sent_back_once(monkeypatch):
    fake = FakeAI(with_part("technical", turn=2), GOOD)
    monkeypatch.setattr(agent, "ask", fake)
    state = run_agent()
    assert len(fake.prompts) == 2 and "name the candidate turn" in fake.prompts[1]
    assert state["dimensions"][0]["evidence"]["turn"] == 4


def test_a_part_still_without_proof_keeps_its_score_without_a_quote(monkeypatch):
    monkeypatch.setattr(agent, "ask", FakeAI(with_part("technical", turn=2)))
    technical = run_agent()["dimensions"][0]
    assert technical["score"] == 70 and technical["evidence"] is None


def test_a_missing_part_after_the_second_try_is_an_error(monkeypatch):
    missing = {"scores": [item for item in GOOD["scores"] if item["dimension"] != "communication"]}
    monkeypatch.setattr(agent, "ask", FakeAI(missing))
    assert "did not score every part" in run_agent()["error"]


def test_an_interview_without_answered_job_questions_is_not_scored(fake_ai):
    assert "no answered job questions" in run_agent(pairs=[PAIRS[0]])["error"]
    assert fake_ai.prompts == []


def test_an_unavailable_ai_gives_an_error_state(monkeypatch):
    monkeypatch.setattr(agent, "ask", FakeAI(broken=True))
    assert run_agent()["error"] == "The AI service is not available right now. Please try again."


def test_the_score_runs_in_the_background_and_is_kept(client, auth_headers):
    session_id = analysed_interview()
    assert client.post(f"/api/interviews/{session_id}/interview-score", headers=auth_headers).status_code == 202
    done = client.get(f"/api/interviews/{session_id}/interview-score", headers=auth_headers).json()
    assert done["status"] == "done" and done["result"]["overall"] == 67.8
    assert len(done["result"]["dimensions"]) == 6


def test_the_score_needs_analysed_answers(client, auth_headers):
    response = client.post(f"/api/interviews/{analysed_interview(analysed=False)}/interview-score", headers=auth_headers)
    assert response.status_code == 400 and response.json()["detail"] == agent_runs.NOT_ANALYSED


def test_unknown_interviews_and_missing_logins_are_refused(client, auth_headers):
    assert client.get("/api/interviews/9999/interview-score", headers=auth_headers).status_code == 404
    assert client.post("/api/interviews/1/interview-score").status_code == 401