"""Prepared AI answers for the screening tests. FakeLLM replaces the real language model."""
from app.agents import screening_agent
from app.agents.screening_agent import CVProfile, Verdict, Verdicts
from app.llm import LLMUnavailable

GOOD_PROFILE = CVProfile(
    name="Priya Saha",
    email="priya@example.com",
    phone="+880 1700-000019",
    education=[
        {
            "degree": "BSc in Computer Science",
            "institution": "Example University",
            "year": "2022",
        }
    ],
    work_history=[
        {
            "title": "Software Engineer",
            "company": "Example Tech",
            "start": "2023",
            "end": "present",
            "summary": "Built APIs.",
        }
    ],
    skills=["Python", "FastAPI", "PostgreSQL"],
    certifications=[],
    projects=[],
    total_experience_years=3,
)

EMPTY_PROFILE = GOOD_PROFILE.model_copy(
    update={"skills": [], "work_history": [], "education": []}
)

ALL_MET = Verdicts(
    verdicts=[
        Verdict(number=n, verdict="met", explanation="Shown in the CV.")
        for n in range(1, 6)
    ]
)

NO_PYTHON = Verdicts(
    verdicts=[
        Verdict(
            number=1,
            verdict="unmet",
            explanation="Python is not mentioned.",
        )
    ]
    + [
        Verdict(number=n, verdict="met", explanation="Shown in the CV.")
        for n in range(2, 6)
    ]
)


class FakeLLM:
    """Stands in for ask_llm(): returns the next prepared answer for each answer shape."""

    def __init__(self, profiles: list, verdicts: list):
        self.answers = {CVProfile: list(profiles), Verdicts: list(verdicts)}
        self.prompts: list[str] = []

    def __call__(self, system_prompt, user_prompt, answer_shape, **options):
        self.prompts.append(user_prompt)
        prepared = self.answers.get(answer_shape)
        if not prepared:
            raise LLMUnavailable("No prepared answer.")
        answer = prepared.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def use_fake_llm(monkeypatch, profiles: list, verdicts: list) -> FakeLLM:
    fake = FakeLLM(profiles, verdicts)
    monkeypatch.setattr(screening_agent, "ask_llm", fake)
    return fake