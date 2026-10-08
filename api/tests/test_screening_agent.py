"""Tests for the Screening Agent, step by step. FakeLLM replaces the real language model."""
from app.agents.screening_agent import get_screening_agent
from app.llm import LLMUnavailable
from tests.fakes import EMPTY_PROFILE, GOOD_PROFILE, use_fake_llm

JOB = {
    "title": "Backend Developer",
    "description": "Python APIs",
    "requirements": [
        {"requirement": "Python", "kind": "skill", "mandatory": True},
        {"requirement": "Docker", "kind": "preferred", "mandatory": False},
    ],
}


def run_agent(cv_text: str = "Priya Saha. Python, FastAPI, PostgreSQL.") -> dict:
    return get_screening_agent().invoke({"cv_text": cv_text, "job": JOB})


def test_profile_is_extracted_from_the_cv(monkeypatch):
    fake = use_fake_llm(monkeypatch, [GOOD_PROFILE], [])
    result = run_agent()
    assert result["profile"]["name"] == "Priya Saha"
    assert "Python, FastAPI, PostgreSQL" in fake.prompts[0]


def test_bad_profile_is_extracted_again_with_feedback(monkeypatch):
    fake = use_fake_llm(monkeypatch, [EMPTY_PROFILE, GOOD_PROFILE], [])
    result = run_agent()
    assert result["profile"]["skills"] == ["Python", "FastAPI", "PostgreSQL"]
    # the retry edge passed the problem back
    assert "The profile is empty" in fake.prompts[1]


def test_gives_up_after_two_bad_profiles(monkeypatch):
    use_fake_llm(monkeypatch, [EMPTY_PROFILE, EMPTY_PROFILE], [])
    assert run_agent()["error"] == (
        "The AI could not read a usable profile from this CV."
    )


def test_ai_failure_becomes_an_error_state(monkeypatch):
    use_fake_llm(
        monkeypatch,
        [LLMUnavailable("The AI service is not available right now.")],
        [],
    )
    assert run_agent()["error"] == "The AI service is not available right now."


def test_long_cv_is_cut_before_it_reaches_the_ai(monkeypatch):
    fake = use_fake_llm(monkeypatch, [GOOD_PROFILE], [])
    run_agent("word " * 10000)
    assert len(fake.prompts[0]) < 8100


from app.agents.screening_agent import Verdict, Verdicts, requirements_of  # noqa: E402
from app.models import JobProfile  # noqa: E402
from tests.test_jobs import JOB as JOB_FORM  # noqa: E402


def verdicts(*answers: str) -> Verdicts:
    return Verdicts(
        verdicts=[
            Verdict(number=n, verdict=a, explanation="From the CV.")
            for n, a in enumerate(answers, start=1)
        ]
    )


def test_every_requirement_gets_a_verdict(monkeypatch):
    use_fake_llm(monkeypatch, [GOOD_PROFILE], [verdicts("met", "partially_met")])
    result = run_agent()
    assert [
        (v["requirement"], v["verdict"], v["mandatory"]) for v in result["verdicts"]
    ] == [
        ("Python", "met", True),
        ("Docker", "partially_met", False),
    ]


def test_skipped_requirement_is_asked_again(monkeypatch):
    fake = use_fake_llm(
        monkeypatch,
        [GOOD_PROFILE],
        [verdicts("met"), verdicts("met", "met")],
    )
    assert len(run_agent()["verdicts"]) == 2
    assert fake.prompts[1] == fake.prompts[2]


def test_requirements_come_from_the_job_profile():
    job = JobProfile(**JOB_FORM)
    assert [
        (r["requirement"], r["kind"], r["mandatory"]) for r in requirements_of(job)
    ] == [
        ("Python", "skill", True),
        ("SQL", "skill", True),
        (
            "Bachelor's degree in Computer Science or equivalent experience",
            "qualification",
            True,
        ),
        ("At least 3 years of relevant work experience", "experience", True),
        ("Docker", "preferred", False),
    ]