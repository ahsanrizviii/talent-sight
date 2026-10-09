"""Prepared AI answers for the screening tests. FakeLLM replaces the real language model."""

from app.agents import screening_agent
from app.agents.screening_agent import CVProfile, Scores, Verdict, Verdicts
from app.llm import LLMUnavailable

GOOD_PROFILE = CVProfile(
    name="Priya Saha",
    email="priya@example.com",
    phone="+880 1700-000019",
    education=[{"degree": "BSc in Computer Science", "institution": "Example University", "year": "2022"}],
    work_history=[{"title": "Software Engineer", "company": "Example Tech", "start": "2023", "end": "present", "summary": "Built APIs."}],
    skills=["Python", "FastAPI", "PostgreSQL"],
    certifications=[],
    projects=[],
    total_experience_years=3,
)
EMPTY_PROFILE = GOOD_PROFILE.model_copy(update={"skills": [], "work_history": [], "education": []})

# The test JOB has 5 requirements: Python, SQL, a degree, 3+ years (all mandatory) and Docker (preferred)
ALL_MET = Verdicts(verdicts=[Verdict(number=n, verdict="met", explanation="Shown in the CV.") for n in range(1, 6)])
NO_PYTHON = Verdicts(
    verdicts=[Verdict(number=1, verdict="unmet", explanation="Python is not mentioned.")]
    + [Verdict(number=n, verdict="met", explanation="Shown in the CV.") for n in range(2, 6)]
)


def scores(technical: int, experience: int, qualifications: int, jd_match: int) -> Scores:
    """Four dimension scores, each with a short justification (Module 6)."""
    return Scores(
        technical_skills={"score": technical, "justification": "Python, FastAPI and PostgreSQL in the CV."},
        experience={"score": experience, "justification": "3 years as a backend engineer."},
        qualifications={"score": qualifications, "justification": "BSc in Computer Science."},
        jd_match={"score": jd_match, "justification": "Most key terms of the job description appear."},
    )


GOOD_SCORES = scores(80, 70, 90, 75)


class FakeLLM:
    """Stands in for ask_llm(): returns the next prepared answer for each answer shape.

    When no scores were prepared, every scored candidate gets GOOD_SCORES.
    Any other question with no prepared answer fails like an unavailable AI.
    """

    def __init__(self, profiles: list, verdicts: list, score_answers: list | None = None):
        self.answers = {CVProfile: list(profiles), Verdicts: list(verdicts), Scores: list(score_answers or [])}
        self.prompts: list[str] = []

    def __call__(self, system_prompt, user_prompt, answer_shape, **options):
        self.prompts.append(user_prompt)
        prepared = self.answers[answer_shape]
        if prepared:
            answer = prepared.pop(0)
        elif answer_shape is Scores:
            answer = GOOD_SCORES
        else:  # nothing prepared for this question: the agent stops with an error state
            raise LLMUnavailable("No prepared answer.")
        if isinstance(answer, Exception):
            raise answer
        return answer


def use_fake_llm(monkeypatch, profiles: list, verdicts: list, score_answers: list | None = None) -> FakeLLM:
    fake = FakeLLM(profiles, verdicts, score_answers)
    monkeypatch.setattr(screening_agent, "ask_llm", fake)
    return fake