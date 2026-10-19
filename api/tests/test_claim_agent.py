"""Tests for the Claim Check Agent (Module 13, F8). The AI is replaced by a fake, so no real model is called.

The embeddings are the fake word-count vectors from conftest.py, so turns that share words with a
claim rank first.
"""

import pytest

from app.agents import claim_agent as agent
from app.agents.claim_agent import ClaimJudgements
from app.llm import LLMUnavailable

JOB = {"title": "Backend Developer", "requirements": ["Python", "PostgreSQL", "Go", "Docker"]}

PROFILE = {
    "work_history": [
        {"title": "Backend Engineer", "company": "Acme", "start": "2021", "end": "present", "summary": "Built payment APIs in Python."},
    ],
    "projects": [{"name": "Ledger", "summary": "A double-entry ledger service."}],
    "certifications": ["AWS Certified Developer"],
    "skills": ["Python", "PostgreSQL", "Google Analytics", "Photoshop", "Python"],
    "total_experience_years": 4,
}

TURNS = [
    {"n": 1, "speaker": "interviewer", "text": "Tell me about your work at Acme.", "start_ms": 0, "end_ms": 4000},
    {"n": 2, "speaker": "candidate", "text": "At Acme I built the payment APIs in Python with FastAPI and Celery.", "start_ms": 5000, "end_ms": 15000},
    {"n": 3, "speaker": "interviewer", "text": "And PostgreSQL?", "start_ms": 16000, "end_ms": 18000},
    {"n": 4, "speaker": "candidate", "text": "Honestly I have only used MySQL, never PostgreSQL.", "start_ms": 19000, "end_ms": 25000},
    {"n": 5, "speaker": "interviewer", "text": "How many years have you worked?", "start_ms": 26000, "end_ms": 28000},
    {"n": 6, "speaker": "candidate", "text": "About four years in total, all of it backend work.", "start_ms": 29000, "end_ms": 34000},
]

# What the fake AI says about each claim id (the ids are fixed by list_claims, see the first test).
SAYS = {
    "K1": {"status": "supported", "turn": 2, "quote": "I built the payment APIs in Python", "note": "Described the payment APIs.", "follow_up": ""},
    "K2": {"status": "supported", "turn": 6, "quote": "About four years in total", "note": "Confirmed four years.", "follow_up": ""},
    "K3": {"status": "not_discussed", "turn": 0, "quote": "", "note": "Not talked about.", "follow_up": "Ask about the Ledger project."},
    "K4": {"status": "unsubstantiated", "turn": 2, "quote": "with FastAPI and Celery", "note": "Only named tools.", "follow_up": "Ask what AWS services they used."},
    "K5": {"status": "supported", "turn": 2, "quote": "in Python with FastAPI", "note": "Uses Python daily.", "follow_up": ""},
    "K6": {"status": "contradicted", "turn": 4, "quote": "never PostgreSQL", "note": "Said they only used MySQL.", "follow_up": "Ask where they used PostgreSQL."},
}


class FakeAI:
    """Answers like the model would, from a table of claim id -> answer, and remembers the questions."""

    def __init__(self, says=None, broken: bool = False):
        self.says = dict(SAYS if says is None else says)
        self.broken = broken
        self.prompts: list[str] = []

    def __call__(self, system_prompt: str, user_prompt: str, answer_shape):
        assert answer_shape is ClaimJudgements
        self.prompts.append(user_prompt)
        if self.broken:
            raise LLMUnavailable("The AI service is not available right now. Please try again.")
        asked = [cid for cid in self.says if f"[{cid}] CV claim" in user_prompt]
        return ClaimJudgements(claims=[{"id": cid, **self.says[cid]} for cid in asked])


@pytest.fixture
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(agent, "ask", fake)
    return fake


def run(profile=None, turns=None) -> dict:
    return agent.get_claim_agent().invoke({"job": JOB, "profile": PROFILE if profile is None else profile, "turns": TURNS if turns is None else turns})


def by_id(state: dict) -> dict:
    return {claim["id"]: claim for claim in state["results"]}


def test_claims_are_listed_roles_first_and_only_the_skills_the_job_asks_for():
    claims = agent.list_claims({"job": JOB, "profile": PROFILE})["claims"]
    assert [(c["id"], c["kind"]) for c in claims] == [
        ("K1", "role"), ("K2", "experience"), ("K3", "project"), ("K4", "certification"), ("K5", "skill"), ("K6", "skill"),
    ]
    assert claims[0]["claim"] == "Backend Engineer at Acme (2021 to present): Built payment APIs in Python."
    skills = [c["claim"] for c in claims if c["kind"] == "skill"]
    # Python once (listed twice in the CV); "Go" in the job must not pull in "Google Analytics"
    assert skills == ["Skill: Python", "Skill: PostgreSQL"]


def test_at_most_twelve_claims_are_checked():
    many = {**PROFILE, "certifications": [f"Certificate {n}" for n in range(20)]}
    assert len(agent.list_claims({"job": JOB, "profile": many})["claims"]) == agent.MAX_CLAIMS


def test_a_cv_without_claims_stops_with_a_clear_error(ai):
    state = run(profile={"skills": ["Photoshop"]})
    assert "no claims to check" in state["error"]
    assert ai.prompts == []


def test_an_interview_where_the_candidate_says_nothing_stops_with_a_clear_error(ai):
    state = run(turns=[t for t in TURNS if t["speaker"] == "interviewer"])
    assert "says nothing" in state["error"]


def test_a_turn_naming_the_company_is_always_shown():
    claims = agent.list_claims({"job": JOB, "profile": PROFILE})["claims"]
    found = agent.find_mentions({"claims": claims, "turns": TURNS})["claims"]
    assert 2 in found[0]["turns"]  # "At Acme I built ..."
    assert all(n in (2, 4, 6) for claim in found for n in claim["turns"])  # candidate turns only


def test_every_claim_gets_one_of_four_statuses_with_flags_first(ai):
    state = run()
    results = state["results"]
    assert [r["status"] for r in results] == ["contradicted", "unsubstantiated", "not_discussed", "supported", "supported", "supported"]
    assert state["summary"] == {"contradicted": 1, "unsubstantiated": 1, "not_discussed": 1, "supported": 3, "claims": 6, "follow_ups": 3}
    flag = by_id(state)["K6"]
    assert flag["label"] == "Possible contradiction"
    assert flag["evidence"] == {"turn": 4, "start_ms": 19000, "at": "00:19", "quote": "never PostgreSQL"}
    assert flag["follow_up"] == "Ask where they used PostgreSQL."


def test_a_backed_up_claim_has_no_follow_up_and_a_not_discussed_claim_has_no_evidence(ai):
    found = by_id(run())
    assert found["K1"]["follow_up"] == "" and found["K1"]["evidence"]["turn"] == 2
    assert found["K3"]["evidence"] is None and found["K3"]["follow_up"] == "Ask about the Ledger project."


def test_the_prompt_shows_each_turn_with_the_question_before_it(ai):
    run()
    assert "Question before it: And PostgreSQL?" in ai.prompts[0]
    assert "[turn 4, 00:19] Candidate: Honestly I have only used MySQL" in ai.prompts[0]


def test_words_the_candidate_did_not_say_are_replaced_by_their_own_words(monkeypatch):
    says = {**SAYS, "K2": {**SAYS["K2"], "quote": "Exactly four years and two months"}}
    monkeypatch.setattr(agent, "ask", FakeAI(says))
    evidence = by_id(run())["K2"]["evidence"]
    assert evidence["turn"] == 6 and evidence["quote"] == "About four years in total, all of it backend work."


def test_a_flag_without_proof_is_asked_again_once_then_shown_as_not_discussed(monkeypatch):
    says = {**SAYS, "K6": {**SAYS["K6"], "turn": 99, "quote": "I lied about PostgreSQL"}}
    fake = FakeAI(says)
    monkeypatch.setattr(agent, "ask", fake)
    state = run()
    assert len(fake.prompts) == 2  # all claims once, then only the unproven one
    assert "[K6] CV claim" in fake.prompts[1] and "[K1] CV claim" not in fake.prompts[1]
    flag = by_id(state)["K6"]
    assert flag["status"] == "not_discussed" and flag["evidence"] is None
    assert flag["follow_up"] == "Ask where they used PostgreSQL."


def test_a_claim_the_ai_skipped_is_not_discussed_with_a_plain_follow_up(monkeypatch):
    says = {k: v for k, v in SAYS.items() if k != "K4"}
    monkeypatch.setattr(agent, "ask", FakeAI(says))
    skipped = by_id(run())["K4"]
    assert skipped["status"] == "not_discussed"
    assert skipped["follow_up"] == "Ask the candidate to walk you through this: Certification: AWS Certified Developer."


def test_an_unavailable_ai_gives_an_error_state_not_a_crash(monkeypatch):
    monkeypatch.setattr(agent, "ask", FakeAI(broken=True))
    state = run()
    assert state["error"] == "The AI service is not available right now. Please try again."
    assert "results" not in state