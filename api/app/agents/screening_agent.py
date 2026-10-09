import json
import logging
from functools import lru_cache
from typing import Literal

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agents.common import AgentState, has_error
from app.llm import LLMUnavailable, ask_llm
from app.models import JobProfile
from app.settings import settings

log = logging.getLogger("talentsight.screening_agent")

MAX_PROFILE_ATTEMPTS = 2  # one retry if the extracted profile breaks the rules
MAX_MATCH_ATTEMPTS = 2    # one retry if the AI skipped a requirement


# ---------- 1. The state ----------
class ScreeningState(AgentState, total=False):
    cv_text: str
    job: dict
    profile: dict
    feedback: str
    attempts: int
    verdicts: list[dict]
    excluded: bool
    exclusion_reason: str
    scores: dict 


# ---------- 2. The answer shapes ----------
class Education(BaseModel):
    degree: str
    institution: str
    year: str = Field(description="Year finished, or empty")


class WorkItem(BaseModel):
    title: str
    company: str
    start: str = Field(description="Start month and year as written, or empty")
    end: str = Field(
        description="End month and year as written, 'present', or empty"
    )
    summary: str = Field(description="One sentence on what they did")


class Project(BaseModel):
    name: str
    summary: str


class CVProfile(BaseModel):
    name: str = Field(description="Full name, or empty")
    email: str = Field(description="E-mail address, or empty")
    phone: str = Field(description="Phone number, or empty")
    education: list[Education]
    work_history: list[WorkItem]
    skills: list[str] = Field(
        description="Technical and professional skills named in the CV"
    )
    certifications: list[str]
    languages: list[str] = Field(
        default_factory=list,
        description="Languages with the level exactly as the CV states it, e.g. 'English: fluent', 'Japanese: JLPT N3'",
    )
    projects: list[Project]
    total_experience_years: float = Field(
        description="Years of work experience in total, 0 if none"
    )

class Verdict(BaseModel):
    number: int = Field(description="The requirement's number")
    verdict: Literal["met", "partially_met", "unmet"]
    explanation: str = Field(
        description="One sentence naming the evidence in the profile, or saying there is none"
    )

class Verdicts(BaseModel):
    verdicts: list[Verdict]

class DimensionScore(BaseModel):
    score: int = Field(description="0 to 100")
    justification: str = Field(description="One or two sentences naming the evidence for this score")


class Scores(BaseModel):
    technical_skills: DimensionScore
    experience: DimensionScore
    qualifications: DimensionScore
    jd_match: DimensionScore

# ---------- 3. Helpers ----------
def requirements_of(job: JobProfile) -> list[dict]:
    """The job's requirements as one list.

    Required skills, qualifications and the minimum experience are mandatory;
    preferred skills are not.
    """
    found = [
        {"requirement": s, "kind": "skill", "mandatory": True}
        for s in job.required_skills
    ]
    found += [
        {"requirement": q, "kind": "qualification", "mandatory": True}
        for q in job.qualifications
    ]
    if job.min_experience_years:
        years = job.min_experience_years
        found.append(
            {
                "requirement": f"At least {years} years of relevant work experience",
                "kind": "experience",
                "mandatory": True,
            }
        )
    found += [
        {"requirement": s, "kind": "preferred", "mandatory": False}
        for s in job.preferred_skills
    ]
    return found


def job_for_agent(job: JobProfile) -> dict:
    return {
        "title": job.title,
        "description": job.description,
        "requirements": requirements_of(job),
    }


def ask(system_prompt: str, user_prompt: str, answer_shape):
    """ask_llm with the screening model, and more patience for Groq's per-minute limit."""
    return ask_llm(
        system_prompt,
        user_prompt,
        answer_shape,
        model=settings.screening_model,
        max_retries=6,
    )


PROFILE_PROMPT = (
    "You read CVs and copy their facts into a structured profile. Copy facts exactly as the CV gives them; "
    "never guess or add anything. Leave a field empty when the CV does not give it. "
    "Record spoken and written languages with the level exactly as written (for example English: fluent, "
    "Japanese: JLPT N3); a language is a skill, not a personal attribute. "
    "Never record age, date of birth, gender, religion, marital status, nationality, photos or family details."
)

MATCH_PROMPT = (
    "You check a candidate's profile against job requirements. For EVERY numbered requirement give one verdict: "
    "met = clear evidence in the profile; partially_met = related or weaker evidence (a similar tool, fewer years); "
    "unmet = no evidence. Match by meaning, not exact words (PostgreSQL counts for Postgres). "
    "Judge only from the profile. The explanation names the evidence in one sentence."
)

SCORE_PROMPT = (
    "You score a candidate for a job on four dimensions, each from 0 to 100 in steps of 5. "
    "Follow this rubric exactly and use only the evidence given. "
    "technical_skills: the share of required skills that are Met (Partially Met counts half), "
    "plus up to 10 points for preferred skills. "
    "experience: 60 = exactly the minimum years of relevant work; add 5 per extra relevant year, at most 100; "
    "take off 15 per missing year, and up to 15 if the work is only partly relevant. "
    "qualifications: 80 = the required degree or an accepted equivalent; 90-100 = more than required "
    "(a related master's degree or relevant certifications); 50 = only a related degree; 20 = none. "
    "jd_match: how many of the job description's key duties and tools appear in the CV, by meaning: "
    "90 almost all, 75 most, 60 about half, 40 a few, 20 almost none. "
    "Each justification names the evidence in one or two sentences."
)

MAX_SCORE_ATTEMPTS = 2  # one retry if a score is outside 0-100

# ---------- 4. The steps ----------
def extract_profile(state: ScreeningState) -> dict:
    prompt = f"CV:\n{state['cv_text'][: settings.cv_max_chars]}"
    if state.get("feedback"):
        prompt += (
            f"\n\nYour last profile had these problems, fix them:\n{state['feedback']}"
        )
    try:
        profile = ask(PROFILE_PROMPT, prompt, CVProfile)
    except LLMUnavailable as error:
        return {"error": str(error)}
    return {
        "profile": profile.model_dump(),
        "attempts": state.get("attempts", 0) + 1,
        "feedback": "",
    }


def check_profile(state: ScreeningState) -> dict:
    """Checks the profile with plain rules. No AI."""
    profile, problems = state["profile"], []
    if not (profile["skills"] or profile["work_history"] or profile["education"]):
        problems.append(
            "The profile is empty: list the skills, jobs and education the CV gives."
        )
    if profile["email"] and "@" not in profile["email"]:
        problems.append(
            f"'{profile['email']}' is not an e-mail address; leave it empty if there is none."
        )
    if not 0 <= profile["total_experience_years"] <= 60:
        problems.append("total_experience_years must be between 0 and 60.")

    if not problems:
        return {}
    if state["attempts"] >= MAX_PROFILE_ATTEMPTS:
        return {"error": "The AI could not read a usable profile from this CV."}
    return {"feedback": "\n".join(problems)}

def match_requirements(state: ScreeningState) -> dict:
    requirements = state["job"]["requirements"]
    numbered = "\n".join(
        f"{i}. {r['requirement']}" for i, r in enumerate(requirements, start=1)
    )
    prompt = (
        f"Profile:\n{json.dumps(state['profile'], ensure_ascii=False)}"
        f"\n\nRequirements:\n{numbered}"
    )

    for _ in range(MAX_MATCH_ATTEMPTS):
        try:
            answer = ask(MATCH_PROMPT, prompt, Verdicts)
        except LLMUnavailable as error:
            return {"error": str(error)}

        by_number = {v.number: v for v in answer.verdicts}
        if all(i in by_number for i in range(1, len(requirements) + 1)):
            verdicts = [
                {
                    **r,
                    "verdict": by_number[i].verdict,
                    "explanation": by_number[i].explanation,
                }
                for i, r in enumerate(requirements, start=1)
            ]
            return {"verdicts": verdicts}

    return {"error": "The AI did not give a verdict for every requirement."}

def mandatory_gate(state: ScreeningState) -> dict:
    """Excludes the candidate if any mandatory requirement is unmet. Plain code (Q&A 9)."""
    missing = [
        v["requirement"]
        for v in state["verdicts"]
        if v["mandatory"] and v["verdict"] == "unmet"
    ]
    if missing:
        return {
            "excluded": True,
            "exclusion_reason": "Mandatory requirement not met: " + "; ".join(missing),
        }
    return {"excluded": False, "exclusion_reason": ""}

def score_candidate(state: ScreeningState) -> dict:
    """Module 6: four scores with a justification each (Q&A 11, 20). Only for candidates who passed the gate."""
    job = state["job"]
    verdicts = "\n".join(f"- {v['requirement']}: {v['verdict']} ({v['explanation']})" for v in state["verdicts"])
    prompt = (
        f"Job: {job['title']}\n\nJob description:\n{job['description'][:3000]}\n\n"
        f"Requirement check:\n{verdicts}\n\nProfile:\n{json.dumps(state['profile'], ensure_ascii=False)}"
    )
    for _ in range(MAX_SCORE_ATTEMPTS):
        try:
            answer = ask(SCORE_PROMPT, prompt, Scores)
        except LLMUnavailable as error:
            return {"error": str(error)}
        scores = answer.model_dump()
        if all(0 <= s["score"] <= 100 for s in scores.values()):
            for s in scores.values():
                s["score"] = int(5 * round(s["score"] / 5))  # steps of 5: small wobbles do not change the total
            return {"scores": scores}
    return {"error": "The AI gave a score outside 0-100."}


def failed(state: ScreeningState) -> dict:
    log.warning(
        "screening agent stopped with an error",
        extra={"event": "screening_failed"},
    )
    return {}


def after_extract(state: ScreeningState) -> str:
    return "failed" if has_error(state) else "check_profile"


def after_check(state: ScreeningState) -> str:
    if has_error(state):
        return "failed"
    return "extract_profile" if state.get("feedback") else "match_requirements"


def after_match(state: ScreeningState) -> str:
    return "failed" if has_error(state) else "mandatory_gate"


def after_gate(state: ScreeningState) -> str:
    return END if state["excluded"] else "score_candidate"


def after_score(state: ScreeningState) -> str:
    return "failed" if has_error(state) else END


# ---------- 6. The graph ----------


@lru_cache
def get_screening_agent():
    graph = StateGraph(ScreeningState)
    graph.add_node("extract_profile", extract_profile)
    graph.add_node("check_profile", check_profile)
    graph.add_node("match_requirements", match_requirements)
    graph.add_node("mandatory_gate", mandatory_gate)
    graph.add_node("score_candidate", score_candidate)
    graph.add_node("failed", failed)

    graph.add_edge(START, "extract_profile")
    graph.add_conditional_edges("extract_profile", after_extract, ["check_profile", "failed"])
    graph.add_conditional_edges("check_profile", after_check, ["extract_profile", "match_requirements", "failed"])
    graph.add_conditional_edges("match_requirements", after_match, ["mandatory_gate", "failed"])
    graph.add_conditional_edges("mandatory_gate", after_gate, ["score_candidate", END])
    graph.add_conditional_edges("score_candidate", after_score, ["failed", END])
    graph.add_edge("failed", END)
    return graph.compile()  