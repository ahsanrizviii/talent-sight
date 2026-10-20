"""Tests for the Question Chat Agent (Module 13). The AI is replaced by a fake, so no real model is called."""

import pytest

from app.agents import chat_agent as agent
from app.agents.chat_agent import ChatReply
from app.interview_context import cv_lines
from app.llm import LLMUnavailable

PROFILE = {
    "work_history": [{"title": "Backend Engineer", "company": "Acme", "start": "2021", "end": "present", "summary": "Built payment APIs."}],
    "projects": [{"name": "Ledger", "summary": "A double-entry ledger service."}],
    "education": [{"degree": "BSc in CSE", "institution": "BUET", "year": "2020"}],
    "certifications": ["AWS Certified Developer"],
    "skills": ["Python", "PostgreSQL", "Python"],
    "total_experience_years": 4,
}

TURNS = [
    {"n": 1, "speaker": "interviewer", "text": "Tell me about your work at Acme.", "start_ms": 0, "end_ms": 4000},
    {"n": 2, "speaker": "candidate", "text": "I built the payment APIs in Python.", "start_ms": 5000, "end_ms": 15000},
    {"n": 3, "speaker": "interviewer", "text": "Have you used Kubernetes?", "start_ms": 76000, "end_ms": 80000},
    {"n": 4, "speaker": "candidate", "text": "A little, we ran a few services on it.", "start_ms": 81000, "end_ms": 86000},
]

JOB = {"title": "Backend Developer", "requirements": ["Python", "Kubernetes", "PostgreSQL"]}
COVERAGE = [
    {"requirement": "Python", "status": "mentioned"},
    {"requirement": "Kubernetes", "status": "mentioned"},
    {"requirement": "PostgreSQL", "status": "not_mentioned"},
]

GOOD = {"question": "Which Kubernetes objects did you write yourself?", "why": "Shows hands-on depth.", "source": "T4"}


class FakeAI:
    """Gives the prepared answers in turn (the last one again when they run out) and remembers the prompts."""

    def __init__(self, *answers, broken: bool = False):
        self.answers = list(answers) or [{"reply": "Probe their Kubernetes use.", "suggestions": [GOOD]}]
        self.broken = broken
        self.prompts: list[str] = []

    def __call__(self, system_prompt: str, user_prompt: str, answer_shape):
        assert answer_shape is ChatReply
        self.prompts.append(user_prompt)
        if self.broken:
            raise LLMUnavailable("The AI service is not available right now. Please try again.")
        return ChatReply(**self.answers[min(len(self.prompts), len(self.answers)) - 1])


@pytest.fixture
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(agent, "ask", fake)
    return fake


def use(monkeypatch, fake: FakeAI) -> FakeAI:
    monkeypatch.setattr(agent, "ask", fake)
    return fake


def run(message: str = "What should I ask about Kubernetes?", turns=None, history=None) -> dict:
    return agent.get_chat_agent().invoke({
        "message": message, "history": history or [], "job": JOB, "cv": cv_lines(PROFILE),
        "turns": TURNS if turns is None else turns, "coverage": COVERAGE,
    })


def test_the_cv_becomes_numbered_lines_roles_first():
    lines = cv_lines(PROFILE)
    assert lines[0] == {"id": "C1", "text": "Backend Engineer at Acme (2021 to present): Built payment APIs."}
    assert [line["text"] for line in lines[1:]] == [
        "4 years of work experience in total",
        "Project Ledger: A double-entry ledger service.",
        "Education: BSc in CSE, BUET (2020)",
        "Certification: AWS Certified Developer",
        "Skills: Python, PostgreSQL",  # listed once even though the CV names Python twice
    ]


def test_the_prompt_shows_requirements_cv_and_transcript_with_ids(ai):
    run()
    prompt = ai.prompts[0]
    assert "[R3] PostgreSQL (not mentioned)" in prompt
    assert "[C1] Backend Engineer at Acme" in prompt
    assert "[T4, 01:21] Candidate: A little, we ran a few services on it." in prompt
    assert prompt.endswith("The interviewer now asks: What should I ask about Kubernetes?")


def test_before_the_interview_the_prompt_says_nothing_was_said(ai):
    run(turns=[])
    assert "(nothing said yet)" in ai.prompts[0]


def test_an_older_turn_about_the_same_thing_is_shown(ai):
    filler = [{"n": n, "speaker": "candidate" if n % 2 else "interviewer", "text": f"Small talk number {n}.", "start_ms": n * 1000, "end_ms": n * 1000 + 500}
              for n in range(2, 30)]
    turns = [{"n": 1, "speaker": "candidate", "text": "I led the Kafka migration at Acme.", "start_ms": 0, "end_ms": 900}] + filler
    run("How do I check the Kafka migration they led?", turns=turns)
    assert "[T1, 00:00] Candidate: I led the Kafka migration" in ai.prompts[0]
    assert "[T2," not in ai.prompts[0]  # an unrelated old turn stays out


def test_a_good_suggestion_keeps_its_source(ai):
    state = run()
    assert state["reply"] == "Probe their Kubernetes use."
    assert state["suggestions"] == [{
        "question": GOOD["question"], "why": "Shows hands-on depth.",
        "source": {"id": "T4", "kind": "transcript", "text": "A little, we ran a few services on it.", "turn": 4, "at": "01:21", "speaker": "candidate"},
    }]


def test_a_cv_or_requirement_source_is_shown_too(monkeypatch):
    use(monkeypatch, FakeAI({"reply": "Two ideas.", "suggestions": [
        {"question": "Walk me through the Ledger design.", "why": "Depth.", "source": "C3"},
        {"question": "How have you used PostgreSQL indexes?", "why": "Not covered yet.", "source": "requirement R3"},
    ]}))
    sources = [s["source"] for s in run()["suggestions"]]
    assert sources == [
        {"id": "C3", "kind": "cv", "text": "Project Ledger: A double-entry ledger service."},
        {"id": "R3", "kind": "requirement", "text": "PostgreSQL"},
    ]


def test_a_suggestion_without_a_real_source_is_sent_back_once_then_dropped(monkeypatch):
    bad = {"question": "What is your favourite framework?", "why": "Curious.", "source": "T99"}
    fake = use(monkeypatch, FakeAI({"reply": "Try these.", "suggestions": [GOOD, bad]}))
    state = run()
    assert len(fake.prompts) == 2
    assert "does not name a line you were shown" in fake.prompts[1]
    assert [s["question"] for s in state["suggestions"]] == [GOOD["question"]]


def test_a_personal_question_is_replaced_after_one_retry(monkeypatch):
    personal = {"question": "Are you married or planning to have children?", "why": "Availability.", "source": "C1"}
    fake = use(monkeypatch, FakeAI({"reply": "Ask this.", "suggestions": [personal]}, {"reply": "Ask this instead.", "suggestions": [GOOD]}))
    state = run()
    assert "personal matter" in fake.prompts[1]
    assert state["reply"] == "Ask this instead."
    assert [s["question"] for s in state["suggestions"]] == [GOOD["question"]]


def test_a_personal_question_never_reaches_the_screen(monkeypatch):
    personal = {"question": "How old are you?", "why": "-", "source": "C1"}
    use(monkeypatch, FakeAI({"reply": "Ask this.", "suggestions": [personal]}))
    assert run()["suggestions"] == []


def test_technical_words_that_look_personal_are_allowed(monkeypatch):
    fine = {"question": "How do you handle a race condition in the payment API's health check?", "why": "-", "source": "C1"}
    use(monkeypatch, FakeAI({"reply": "One idea.", "suggestions": [fine]}))
    assert len(run()["suggestions"]) == 1


def test_at_most_three_suggestions_and_no_duplicates(monkeypatch):
    many = [{"question": f"Question {n}?", "why": "-", "source": "C1"} for n in (1, 1, 2, 3, 4)]
    use(monkeypatch, FakeAI({"reply": "Several.", "suggestions": many}))
    assert [s["question"] for s in run()["suggestions"]] == ["Question 1?", "Question 2?", "Question 3?"]


def test_earlier_messages_are_shown_so_a_follow_up_makes_sense(ai):
    history = [
        {"role": "interviewer", "text": "What about Python?", "suggestions": []},
        {"role": "assistant", "text": "Ask about their APIs.", "suggestions": [{"question": "How did you test the payment APIs?"}]},
    ]
    run("And a harder one?", history=history)
    assert "Interviewer: What about Python?" in ai.prompts[0]
    assert "Suggested: How did you test the payment APIs?" in ai.prompts[0]


def test_an_unavailable_ai_gives_an_error_state_not_a_crash(monkeypatch):
    use(monkeypatch, FakeAI(broken=True))
    state = run()
    assert state["error"] == "The AI service is not available right now. Please try again."
    assert "reply" not in state