import json
import logging
from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field, ValidationError

from app import blogger
from app.agents.common import AgentState, has_error
from app.checkpointer import get_checkpointer
from app.db import SessionLocal
from app.job_profiles import JobIn, publish_job_post
from app.knowledge import search_policies
from app.llm import LLMUnavailable, ask_llm
from app.models import JobProfile

log = logging.getLogger("talentsight.jd_agent")

MAX_QUESTION_ROUNDS = 1  
MAX_DRAFT_ATTEMPTS = 2  

class JDState(AgentState, total=False):
    brief: str  
    policy_sources: list[str]  # the hiring-policy documents chosen in the Library; empty = all
    questions: list[str]  
    question_rounds: int  
    policies: list[str]  
    draft: dict 
    feedback: str 
    draft_attempts: int  
    job_id: int  
    slug: str  
    blog_url: str  # the post on the public blog, "" if it was not posted


class BriefCheck(BaseModel):
    job_title: str = Field(description="Short job title, for example 'Backend Developer'")
    missing_details: list[str] = Field(
        description="Up to 3 short questions about facts the brief does not give: the job level, "
        "the main skills, or the minimum years of experience. An empty list if all three are given."
    )

class DraftWeights(BaseModel):
    technical_skills: int
    experience: int
    qualifications: int
    jd_match: int

class DraftRound(BaseModel):
    name: str = Field(description="Short name of the round, for example 'HR interview' or 'Technical round 1'")
    focus: str = Field(description="What this round covers, in a few words")


class JobDraft(BaseModel):
    title: str
    description: str = Field(description="The full job post as plain text, in the company's job-post format")
    required_skills: list[str] = Field(description="Must-have skills, at most 6")
    preferred_skills: list[str] = Field(description="Nice-to-have skills")
    qualifications: list[str] = Field(description="Degrees or certificates, each with 'or equivalent experience'")
    min_experience_years: int
    selection_criteria: str = Field(description="One or two sentences on how candidates will be judged")
    weights: DraftWeights = Field(description="Scoring weights in percent; the four numbers must add up to 100")
    interview_rounds: list[DraftRound] = Field(
        default_factory=list,
        description="The interview rounds of the hiring process, in order, exactly as the brief describes them "
        "(at most 6). Empty when the brief does not describe the rounds.",
    )

CHECK_PROMPT = (
    "You help a hiring manager write a job post. Read their brief and check whether it gives "
    "the job level, the main skills and the minimum years of experience. Ask only about what is really missing."
)

DRAFT_PROMPT = (
    "You write job posts for a company. Follow the company policies you are given exactly. "
    "Use only job-related requirements. Never mention or ask for age, gender, religion, nationality, "
    "marital status or any other personal characteristic. "
    "If the brief describes the hiring process (the interview rounds), list those rounds in interview_rounds, "
    "in the same order, each with a short name and what it covers. Never invent rounds the brief does not mention."
)

# A brief that says nothing about the hiring process gives a job with one interview round.
ONE_ROUND = [{"name": "Interview", "focus": ""}]


def check_brief(state: JDState) -> dict:
    try:
        result = ask_llm(CHECK_PROMPT, state["brief"], BriefCheck)
    except LLMUnavailable as error:
        return {"error": str(error)}
    if result.missing_details and state.get("question_rounds", 0) < MAX_QUESTION_ROUNDS:
        return {"questions": result.missing_details[:3]}
    return {"questions": []}


def ask_for_details(state: JDState) -> dict:
    # interrupt() pauses the graph and saves it. The API shows the questions; when the
    # interviewer answers, the graph continues from here with their reply.
    reply = interrupt({"kind": "questions", "questions": state["questions"]})
    return {
        "brief": f"{state['brief']}\nMore details from the hiring manager: {reply['text']}",
        "question_rounds": state.get("question_rounds", 0) + 1,
    }


def find_policies(state: JDState) -> dict:
    with SessionLocal() as db:
        chunks = search_policies(db, state["brief"], limit=5, sources=state.get("policy_sources") or None)
    return {"policies": [f"[{chunk.source}] {chunk.text}" for chunk in chunks]}


def write_draft(state: JDState) -> dict:
    policies = "\n".join(f"- {policy}" for policy in state["policies"])
    prompt = f"Brief:\n{state['brief']}\n\nCompany policies:\n{policies}"
    if state.get("feedback"):
        prompt += f"\n\nYour previous draft:\n{json.dumps(state['draft'])}"
        prompt += f"\n\nChange it as follows:\n{state['feedback']}"
    try:
        draft = ask_llm(DRAFT_PROMPT, prompt, JobDraft)
    except LLMUnavailable as error:
        return {"error": str(error)}
    result = draft.model_dump()
    rounds = [
        {"name": r["name"].strip()[:80], "focus": r.get("focus", "").strip()[:300]}
        for r in result.get("interview_rounds", [])
        if r.get("name", "").strip()
    ]
    result["interview_rounds"] = rounds[:6] or [dict(r) for r in ONE_ROUND]
    return {"draft": result, "feedback": "", "draft_attempts": state.get("draft_attempts", 0) + 1}


def check_draft(state: JDState) -> dict:

    try:
        JobIn(**state["draft"])
        return {}
    except ValidationError as error:
        problems = "; ".join(item["msg"] for item in error.errors())
    if state["draft_attempts"] >= MAX_DRAFT_ATTEMPTS:
        return {"error": "The AI could not write a valid job post. Please try again with a clearer brief."}
    return {"feedback": f"Fix these problems: {problems}"}


def ask_for_approval(state: JDState) -> dict:

    reply = interrupt({"kind": "draft", "draft": state["draft"]})
    if reply.get("approve"):
        return {}
    return {"feedback": reply.get("text") or "Improve the draft.", "draft_attempts": 0}


def save_and_publish(state: JDState) -> dict:
    with SessionLocal() as db:
        job = JobProfile(**JobIn(**state["draft"]).model_dump())
        job.policy_sources = list(state.get("policy_sources") or [])
        db.add(job)
        db.flush()  # the database gives the job its id, which the web address needs
        slug = publish_job_post(job)
        db.commit()
        log.info("job published by jd agent", extra={"event": "jd_published", "job_id": job.id})
        # Approved, so the agent now uses its Blogger MCP tool to post the job publicly.
        blog_url = blogger.post_job(job)
        return {"job_id": job.id, "slug": slug, "blog_url": blog_url or ""}


def failed(state: JDState) -> dict:
    log.warning("jd agent stopped with an error", extra={"event": "jd_agent_failed"})
    return {}


def after_check_brief(state: JDState) -> str:
    if has_error(state):
        return "failed"
    return "ask_for_details" if state.get("questions") else "find_policies"


def after_write_draft(state: JDState) -> str:
    return "failed" if has_error(state) else "check_draft"


def after_check_draft(state: JDState) -> str:
    if has_error(state):
        return "failed"
    return "write_draft" if state.get("feedback") else "ask_for_approval"


def after_approval(state: JDState) -> str:
    return "write_draft" if state.get("feedback") else "save_and_publish"



@lru_cache 
def get_jd_agent():
    graph = StateGraph(JDState)
    graph.add_node("check_brief", check_brief)
    graph.add_node("ask_for_details", ask_for_details)
    graph.add_node("find_policies", find_policies)
    graph.add_node("write_draft", write_draft)
    graph.add_node("check_draft", check_draft)
    graph.add_node("ask_for_approval", ask_for_approval)
    graph.add_node("save_and_publish", save_and_publish)
    graph.add_node("failed", failed)

    graph.add_edge(START, "check_brief")
    graph.add_conditional_edges("check_brief", after_check_brief, ["ask_for_details", "find_policies", "failed"])
    graph.add_edge("ask_for_details", "check_brief")
    graph.add_edge("find_policies", "write_draft")
    graph.add_conditional_edges("write_draft", after_write_draft, ["check_draft", "failed"])
    graph.add_conditional_edges("check_draft", after_check_draft, ["write_draft", "ask_for_approval", "failed"])
    graph.add_conditional_edges("ask_for_approval", after_approval, ["write_draft", "save_and_publish"])
    graph.add_edge("save_and_publish", END)
    graph.add_edge("failed", END)

    return graph.compile(checkpointer=get_checkpointer())
