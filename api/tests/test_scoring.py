"""Tests for candidate scoring (Module 6). FakeLLM replaces the real language model."""

from tests.fakes import GOOD_PROFILE, scores, use_fake_llm
from tests.test_screening_agent import run_agent, verdicts


def test_passing_candidate_gets_four_scores_with_justifications(monkeypatch):
    use_fake_llm(monkeypatch, [GOOD_PROFILE], [verdicts("met", "met")], [scores(80, 70, 90, 75)])
    result = run_agent()
    assert {d: s["score"] for d, s in result["scores"].items()} == {
        "technical_skills": 80,
        "experience": 70,
        "qualifications": 90,
        "jd_match": 75,
    }
    assert result["scores"]["experience"]["justification"] == "3 years as a backend engineer."


def test_excluded_candidate_is_not_scored(monkeypatch):
    fake = use_fake_llm(monkeypatch, [GOOD_PROFILE], [verdicts("unmet", "met")])
    result = run_agent()
    assert "scores" not in result
    assert len(fake.prompts) == 2  # profile + matching; no scoring call


def test_score_outside_0_to_100_is_asked_again(monkeypatch):
    use_fake_llm(monkeypatch, [GOOD_PROFILE], [verdicts("met", "met")], [scores(150, 70, 90, 75), scores(80, 70, 90, 75)])
    assert run_agent()["scores"]["technical_skills"]["score"] == 80