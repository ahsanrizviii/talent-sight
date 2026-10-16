"""Tests for the Assessment Agent (Module 10). The AI is replaced by a fake, so no real model is called."""

import pytest

from app.agents import assessment_agent as agent
from app.agents.assessment_agent import Findings
from app.llm import LLMUnavailable

JOB = {"title": "Backend Developer"}

VERDICTS = [
    {"requirement": "Python", "kind": "skill", "mandatory": True, "verdict": "met", "explanation": "Four years of Python at Acme."},
    {"requirement": "PostgreSQL", "kind": "skill", "mandatory": True, "verdict": "partially_met", "explanation": "MySQL only."},
    {"requirement": "Docker", "kind": "preferred", "mandatory": False, "verdict": "met", "explanation": "Dockerised two services."},
    {"requirement": "Kubernetes", "kind": "preferred", "mandatory": False, "verdict": "unmet", "explanation": "Not mentioned."},
]


def dimension(key: str, label: str, score: float, weight: int) -> dict:
    return {"dimension": key, "label": label, "score": score, "weight": weight, "justification": f"{label} from the CV."}


CV_SCORE = {
    "overall": 72.5,
    "dimensions": [
        dimension("technical_skills", "Technical skills", 80, 40),
        dimension("experience", "Relevant experience", 70, 30),
        dimension("qualifications", "Qualifications", 60, 15),
        dimension("jd_match", "Job description match", 70, 15),
    ],
}


def coverage(number: int, requirement: str, status: str, pairs: list[int], best) -> dict:
    mandatory = number <= 2
    kind = "skill" if mandatory else "preferred"
    return {"number": number, "requirement": requirement, "kind": kind, "mandatory": mandatory,
            "pairs": pairs, "best_score": best, "status": status}


ANALYSIS = {
    "pairs": [
        {"id": 1, "kind": "small_talk", "question": "Can you hear me?", "overall": None, "evidence": None, "start_ms": 0},
        {"id": 2, "kind": "job_related", "question": "What is a Python generator?", "overall": 85,
         "evidence": {"turn": 4, "start_ms": 15_000, "quote": "yields values one at a time"}, "start_ms": 10_000},
        {"id": 3, "kind": "job_related", "question": "How do you index a PostgreSQL table?", "overall": 40,
         "evidence": {"turn": 6, "start_ms": 44_000, "quote": "With CREATE INDEX"}, "start_ms": 40_000},
    ],
    "coverage": [
        coverage(1, "Python", "explored", [2], 85),
        coverage(2, "PostgreSQL", "weak", [3], 40),
        coverage(3, "Docker", "not_explored", [], None),
        coverage(4, "Kubernetes", "not_explored", [], None),
    ],
    "summary": {"average": 62},
}

GOOD = {
    "summary": {"text": "Solid Python, weak on PostgreSQL.", "evidence": ["Q2", "C2"]},
    "strengths": [{"text": "Explains Python generators clearly.", "evidence": ["Q2", "R1"]}],
    "weaknesses": [{"text": "PostgreSQL indexing answer was thin.", "evidence": ["Q3"]}],
    "follow_ups": [{"text": "Ask about Docker in the next round.", "evidence": ["C3", "R3"]}],
}


class FakeAI:
    """Answers like the model would, one prepared answer per question, and remembers the questions."""

    def __init__(self, answers=None, broken: bool = False):
        self.answers = list(answers or [GOOD])
        self.broken = broken
        self.prompts: list[str] = []

    def __call__(self, system_prompt: str, user_prompt: str, answer_shape):
        assert answer_shape is Findings
        self.prompts.append(user_prompt)
        if self.broken:
            raise LLMUnavailable("The AI service is not available right now. Please try again.")
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return Findings(**answer)


@pytest.fixture
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(agent, "ask", fake)
    return fake


def run(cv_score=None, analysis=None) -> dict:
    return agent.get_assessment_agent().invoke({
        "job": JOB,
        "verdicts": VERDICTS,
        "cv_score": cv_score or CV_SCORE,
        "analysis": analysis or ANALYSIS,
    })


# ---------- Evidence and gaps (plain code) ----------


def test_every_fact_gets_an_evidence_id(ai):
    ids = [item["id"] for item in run()["evidence"]]
    assert ids == ["R1", "R2", "R3", "R4", "S1", "S2", "S3", "S4", "Q2", "Q3", "C1", "C2", "C3", "C4"]


def test_small_talk_is_never_evidence(ai):
    result = run()
    assert "Q1" not in [item["id"] for item in result["evidence"]]
    assert "Can you hear me" not in ai.prompts[0]


def test_interview_evidence_carries_the_quote_and_time(ai):
    answer = next(item for item in run()["evidence"] if item["id"] == "Q2")
    assert answer["source"] == "interview" and answer["at"] == "00:15"
    assert answer["text"] == 'Answer scored 85/100. "yields values one at a time"'


def test_each_requirement_line_joins_the_cv_and_the_interview(ai):
    postgres = run()["requirements"][1]
    assert (postgres["n"], postgres["cv"], postgres["interview"], postgres["best_score"], postgres["pairs"]) == (
        2, "partially_met", "weak", 40, [3],
    )


def test_gaps_are_found_by_code_with_must_haves_first(ai):
    gaps = run()["gaps"]
    assert [(g["requirement"], g["kind"], g["evidence"]) for g in gaps] == [
        ("PostgreSQL", "no_evidence", ["R2", "C2"]),
        ("Docker", "cv_only", ["R3", "C3"]),
        ("Kubernetes", "no_evidence", ["R4", "C4"]),
    ]


def test_a_cv_claim_with_a_weak_interview_answer_is_a_gap(ai):
    weak_python = {**ANALYSIS, "coverage": [coverage(1, "Python", "weak", [2], 45)] + ANALYSIS["coverage"][1:]}
    gap = run(analysis=weak_python)["gaps"][0]
    assert (gap["requirement"], gap["kind"], gap["evidence"]) == ("Python", "weak_in_interview", ["R1", "C1", "Q2"])


# ---------- The position (plain code) ----------


def test_the_position_is_a_weighted_total_of_four_parts(ai):
    result = run()
    parts = {c["key"]: (c["score"], c["weight"], c["contribution"]) for c in result["components"]}
    assert parts == {
        "cv_score": (72.5, 30, 21.8),
        "requirements": (62.5, 15, 9.4),
        "answers": (62.0, 40, 24.8),
        "coverage": (37.5, 15, 5.6),
    }
    position = result["position"]
    assert (position["code"], position["label"], position["overall"]) == ("possible_fit", "Possible fit", 61.6)
    assert result["components"][2]["evidence"] == ["Q2", "Q3"]


def test_a_must_have_without_evidence_keeps_the_candidate_from_strong_fit(ai):
    position = run(cv_score={**CV_SCORE, "overall": 95}, analysis={**ANALYSIS, "summary": {"average": 95}})["position"]
    assert position["overall"] == 81.5
    assert position["code"] == "possible_fit"
    assert position["reasons"][-1] == "Lowered to a possible fit: no solid evidence for the must-have PostgreSQL."
    assert position["evidence"] == ["R2", "C2"]


def test_a_part_with_nothing_to_measure_shares_its_weight(ai):
    no_answers = {**ANALYSIS, "summary": {"average": None}}
    result = run(analysis=no_answers)
    assert [c["key"] for c in result["components"]] == ["cv_score", "requirements", "coverage"]
    # (72.5 * 30 + 62.5 * 15 + 37.5 * 15) / 60
    assert result["position"]["overall"] == 61.3


# ---------- The findings (AI, checked by code) ----------


def test_findings_keep_only_real_evidence(monkeypatch):
    messy = {
        **GOOD,
        "strengths": [
            {"text": "Explains generators.", "evidence": ["[q2]", "X9", "Q2"]},  # written oddly, made up, repeated
            {"text": "Knows everything.", "evidence": ["Z1"]},  # nothing real behind it
        ],
    }
    monkeypatch.setattr(agent, "ask", FakeAI([messy]))
    findings = run()["findings"]
    assert findings["strengths"] == [{"text": "Explains generators.", "evidence": ["Q2"]}]


def test_untraceable_findings_are_asked_for_again(monkeypatch):
    nothing_real = {**GOOD, "strengths": [{"text": "Great.", "evidence": ["X1"]}], "weaknesses": []}
    fake = FakeAI([nothing_real, GOOD])
    monkeypatch.setattr(agent, "ask", fake)
    result = run()
    assert len(fake.prompts) == 2
    assert result["findings"]["strengths"][0]["evidence"] == ["Q2", "R1"]


def test_twice_untraceable_stops_with_a_clear_message(monkeypatch):
    nothing_real = {**GOOD, "strengths": [{"text": "Great.", "evidence": []}], "weaknesses": []}
    monkeypatch.setattr(agent, "ask", FakeAI([nothing_real]))
    result = run()
    assert result["error"] == "The AI's findings could not be traced to the CV or the interview. Please try again."
    assert "findings" not in result


def test_a_summary_without_evidence_is_made_from_the_numbers(monkeypatch):
    monkeypatch.setattr(agent, "ask", FakeAI([{**GOOD, "summary": {"text": "Nice person.", "evidence": []}}]))
    summary = run()["findings"]["summary"]
    assert summary["text"] == "Possible fit: weighted total 61.6 out of 100."
    assert summary["evidence"] == ["S1", "R1", "Q2", "C1"]


def test_the_ai_is_told_the_position_and_the_gaps(ai):
    run()
    prompt = ai.prompts[0]
    assert "Position (decided by code): Possible fit, weighted total 61.6/100." in prompt
    assert "[R2, C2]" in prompt and "[Q2] (Interview, 00:15)" in prompt


def test_an_ai_failure_stops_with_a_clear_message(monkeypatch):
    monkeypatch.setattr(agent, "ask", FakeAI(broken=True))
    result = run()
    assert result["error"] == "The AI service is not available right now. Please try again."
    assert "position" in result  # the plain-code steps before it still ran


def test_the_report_has_every_part(ai):
    report = agent.report_of(run())
    assert set(report) == {
        "position", "components", "requirements", "gaps", "summary",
        "strengths", "weaknesses", "follow_ups", "evidence",
    }