"""Tests for Litmus's copies, its comparison rules and its agent (F11).

No real AI is called: the agent's AI is a fake. The most important test is the planted fault:
a fake scorer that marks down one name on purpose must be caught, and only that copy flagged.
"""

import json

from app.agents import litmus_agent, screening_agent
from app.agents.litmus_agent import get_litmus_agent
from app.agents.screening_agent import Scores, Verdicts
from app.llm import LLMUnavailable
from app.litmus import blind, compare, judge, make_variants, noise_band, renamed, replace_everywhere, swap_names
from tests.fakes import ALL_MET, GOOD_PROFILE, NO_PYTHON, scores

PROFILE = GOOD_PROFILE.model_dump()
JOB = {
    "title": "Backend Developer",
    "description": "Build and run Python APIs on PostgreSQL.",
    "requirements": [
        {"requirement": "Python", "kind": "skill", "mandatory": True},
        {"requirement": "SQL", "kind": "skill", "mandatory": True},
        {"requirement": "BSc in Computer Science", "kind": "qualification", "mandatory": True},
        {"requirement": "At least 3 years of relevant work experience", "kind": "experience", "mandatory": True},
        {"requirement": "Docker", "kind": "preferred", "mandatory": False},
    ],
}
WEIGHTS = {"technical_skills": 40, "experience": 30, "qualifications": 15, "jd_match": 15}


class FakeAI:
    """Stands in for ask_llm(). Every requirement is met and every profile gets the same scores,
    unless `marked_down` names someone whose technical score is lowered on purpose (the planted fault)."""

    def __init__(self, marked_down: str = "", verdicts: Verdicts = ALL_MET, broken_after: int | None = None):
        self.marked_down = marked_down
        self.verdicts = verdicts
        self.broken_after = broken_after
        self.calls = 0

    def __call__(self, system_prompt, user_prompt, answer_shape, **options):
        self.calls += 1
        if self.broken_after is not None and self.calls > self.broken_after:
            raise LLMUnavailable("The AI service is not available right now. Please try again.")
        if answer_shape is Verdicts:
            return self.verdicts
        if answer_shape is Scores:
            if self.marked_down and self.marked_down in user_prompt:
                return scores(60, 70, 90, 75)
            return scores(80, 70, 90, 75)
        raise LLMUnavailable("No prepared answer.")


def use(monkeypatch, fake: FakeAI) -> FakeAI:
    monkeypatch.setattr(screening_agent, "ask_llm", fake)
    return fake


def check(profile: dict = PROFILE) -> dict:
    return get_litmus_agent().invoke({"job": JOB, "weights": WEIGHTS, "profile": profile})


def run(overall: float | None, technical: int = 80, excluded: bool = False, verdicts: list[str] | None = None) -> dict:
    """A hand-made run, for the comparison rules."""
    verdicts = verdicts or ["met"] * 5
    return {
        "verdicts": [
            {"requirement": r["requirement"], "mandatory": r["mandatory"], "verdict": v}
            for r, v in zip(JOB["requirements"], verdicts)
        ],
        "excluded": excluded,
        "scores": {} if excluded else {"technical_skills": technical, "experience": 70, "qualifications": 90, "jd_match": 75},
        "overall": None if excluded else overall,
    }


# ---------- The copies ----------
def test_each_copy_changes_one_kind_of_detail():
    copies = {v["key"]: v for v in make_variants(PROFILE)}
    assert list(copies) == ["blind", "name_a", "name_b", "institution"]
    assert all(v["applicable"] for v in copies.values())

    hidden = copies["blind"]["profile"]
    assert hidden["name"] == hidden["email"] == hidden["phone"] == ""
    assert hidden["skills"] == PROFILE["skills"] and hidden["work_history"] == PROFILE["work_history"]

    assert copies["name_a"]["profile"]["name"] == "Ayesha Karim"
    assert copies["name_b"]["profile"]["name"] == "Daniel Novak"
    assert copies["name_b"]["profile"]["email"] == "daniel.novak@example.com"
    assert copies["name_b"]["profile"]["phone"] == PROFILE["phone"]

    schools = copies["institution"]["profile"]["education"]
    assert schools[0]["institution"] == "" and schools[0]["degree"] == PROFILE["education"][0]["degree"]


def test_the_original_profile_is_never_changed():
    before = json.dumps(PROFILE, sort_keys=True)
    make_variants(PROFILE)
    assert json.dumps(PROFILE, sort_keys=True) == before


def test_the_real_name_is_taken_out_of_every_text():
    profile = {**PROFILE, "projects": [{"name": "Priya Saha's portfolio", "summary": "Built by Priya Saha."}]}
    assert "Priya" not in json.dumps(blind(profile))
    assert "Priya" not in json.dumps(renamed(profile, "Daniel Novak"))


def test_a_short_name_only_matches_whole_words():
    assert replace_everywhere({"text": "Ali improved quality"}, "Ali", "X") == {"text": "X improved quality"}


def test_the_made_up_names_are_never_the_candidates_own():
    assert "Ayesha Karim" not in swap_names("ayesha karim")
    assert "Daniel Novak" not in swap_names("Daniel Novak")


def test_a_copy_that_changes_nothing_is_not_run():
    profile = {**PROFILE, "education": []}
    copies = {v["key"]: v for v in make_variants(profile)}
    assert copies["institution"]["applicable"] is False


# ---------- The comparison rules ----------
def test_a_same_result_is_steady():
    noise = noise_band(run(80.0), run(80.0))
    found = compare(run(80.0), run(80.0), noise)
    assert found["flagged"] is False and found["overall_change"] == 0.0


def test_one_scoring_step_is_allowed_but_two_are_flagged():
    noise = noise_band(run(80.0), run(80.0))
    assert compare(run(80.0), run(78.0, technical=75), noise)["flagged"] is False
    two_steps = compare(run(80.0), run(76.0, technical=70), noise)
    assert two_steps["flagged"] is True
    assert "Technical skills moved by -10 points" in two_steps["reasons"][0]


def test_the_noise_band_widens_what_is_allowed():
    noise = noise_band(run(80.0), run(76.0, technical=70))  # the unchanged profile moved 10 by itself
    assert noise["dimensions"]["technical_skills"] == 10
    assert compare(run(80.0), run(74.0, technical=65), noise)["flagged"] is False  # 15 <= 10 + 5


def test_a_different_must_have_answer_is_flagged():
    noise = noise_band(run(80.0), run(80.0))
    found = compare(run(80.0), run(None, excluded=True, verdicts=["unmet", "met", "met", "met", "met"]), noise)
    assert found["flagged"] and found["gate_changed"]
    assert any("must-have check" in reason for reason in found["reasons"])


def test_a_verdict_that_also_moved_by_chance_is_not_flagged():
    wobbly = ["partially_met", "met", "met", "met", "met"]
    noise = noise_band(run(80.0), run(80.0, verdicts=wobbly))
    found = compare(run(80.0), run(80.0, verdicts=wobbly), noise)
    assert found["flagged"] is False and found["verdict_changes"][0]["within_noise"] is True


def test_a_wobbly_scorer_makes_the_check_inconclusive():
    variants = [{"key": "blind", "label": "x", "changed": "x", "applicable": True}]
    report = judge(variants, {"reference": run(80.0), "repeat": run(72.0, technical=60), "blind": run(80.0)})
    assert report["outcome"] == "inconclusive"


# ---------- The agent ----------
def test_a_fair_scorer_gives_a_steady_result(monkeypatch):
    fake = use(monkeypatch, FakeAI())
    report = check()["report"]
    assert report["outcome"] == "steady" and report["flag_count"] == 0
    assert fake.calls == 12  # 6 runs (reference, repeat, 4 copies) x 2 questions


def test_the_planted_fault_is_caught_and_only_that_copy_is_flagged(monkeypatch):
    use(monkeypatch, FakeAI(marked_down="Daniel Novak"))
    report = check()["report"]
    flagged = [v["key"] for v in report["variants"] if v.get("flagged")]
    assert report["outcome"] == "needs_review" and flagged == ["name_b"]
    name_b = next(v for v in report["variants"] if v["key"] == "name_b")
    assert name_b["dimension_changes"]["technical_skills"] == -20 and name_b["overall_change"] == -8.0


def test_copies_that_change_nothing_cost_no_ai_calls(monkeypatch):
    fake = use(monkeypatch, FakeAI())
    report = check({**PROFILE, "education": []})["report"]
    assert fake.calls == 10
    assert next(v for v in report["variants"] if v["key"] == "institution")["applicable"] is False


def test_an_excluded_candidate_is_checked_on_the_must_have_answer(monkeypatch):
    fake = use(monkeypatch, FakeAI(verdicts=NO_PYTHON))
    report = check()["report"]
    assert report["outcome"] == "steady" and report["reference"]["excluded"] is True
    assert fake.calls == 6  # only the requirement check runs; excluded profiles are never scored


def test_a_failed_ai_stops_the_check_with_an_error(monkeypatch):
    use(monkeypatch, FakeAI(broken_after=5))
    final = check()
    assert "not available" in final["error"] and "report" not in final


def test_the_agent_uses_the_screening_steps():
    # Litmus must test the scorer the screening really uses, not a copy of it.
    assert litmus_agent.match_requirements is screening_agent.match_requirements
    assert litmus_agent.mandatory_gate is screening_agent.mandatory_gate
    assert litmus_agent.score_candidate is screening_agent.score_candidate
