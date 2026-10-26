"""The Interview Quality Agent (Module 13, F10): how well the interview itself was run.

It reviews the interview, not the candidate: how much each side talked, how many job questions were
asked and followed up, how much of the job's requirements were covered, the kind of each question, and
how this interview compares with the other interviews for the same job. It ends with two to four
recommendations, each pointing to a moment in the transcript (or to the whole interview).

Steps:
    measure        (plain code) talk time, questions, follow-ups, answer lengths, coverage, personal
                                questions (N20), and the averages of the other interviews for this job
    review         (AI)         the kind of each job question, a short summary and the recommendations
    check_review   (plain code) every recommendation points to a real turn; problems go back once (a loop)

Advice for the hiring team only: it never changes the candidate's score, assessment or stage.
"""

import logging
import re
from collections import Counter
from functools import lru_cache
from statistics import mean
from typing import Literal

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agents.chat_agent import PERSONAL
from app.agents.common import AgentState, has_error
from app.llm import LLMUnavailable, ask_llm
from app.settings import settings

log = logging.getLogger("talentsight.quality_agent")

MAX_QUESTIONS = 15   # job questions shown to the AI (keeps it inside Groq's free limit)
TURN_CHARS = 300
MAX_ATTEMPTS = 2     # the AI is asked again once when a recommendation points nowhere
MAX_RECOMMENDATIONS = 4
COMPARED = ("interviewer_talk_pct", "questions", "follow_ups", "coverage_pct", "minutes")
KINDS = ("open", "probing", "closed", "leading", "unclear")
LABELS = {
    "open": "Open",
    "probing": "Probing follow-up",
    "closed": "Closed (yes / no)",
    "leading": "Leading",
    "unclear": "Unclear",
    "unrated": "Not rated",
}
# A question that starts like this asks for an explanation, so it is never a yes/no question.
OPEN_START = re.compile(r"^\s*(what|how|why|which|describe|tell|explain|walk|talk|give)\b", re.IGNORECASE)


# ---------- 1. The state ----------
class QualityState(AgentState, total=False):
    # Input (see interview_quality.inputs_for)
    job: dict        # {"title", "requirements"}
    turns: list      # [{"n", "speaker", "text", "start_ms", "end_ms"}]
    pairs: list      # the question-answer pairs from the answer analysis (Module 9)
    coverage: list   # [{"requirement", "mandatory", "status"}]; in an HR round the HR topics
    round_type: str  # "technical" or "hr"
    others: list     # the measures of the other reviewed interviews for the same job
    # Filled in step by step
    measures: dict
    compare: dict
    personal: list   # interviewer turns that touch a personal matter (N20)
    draft: dict
    problems: list
    attempts: int
    questions: list
    kinds: dict
    recommendations: list
    summary: str


# ---------- 2. The answer shape ----------
class QuestionKind(BaseModel):
    id: int = Field(description="The question's number: 3 for Q3")
    kind: Literal["open", "probing", "closed", "leading", "unclear"]
    note: str = Field(description="One short neutral sentence on why")


class Recommendation(BaseModel):
    text: str = Field(description="One concrete recommendation for the interviewer, one or two sentences")
    turn: int = Field(description="The transcript turn it is about (12 for T12), or 0 if it is about the whole interview")


class Review(BaseModel):
    summary: str = Field(description="Two neutral sentences on how the interview was run")
    questions: list[QuestionKind]
    recommendations: list[Recommendation]


# ---------- 3. Small helpers ----------
def tidy(text) -> str:
    return " ".join(str(text or "").split())


def clip(text: str, limit: int) -> str:
    text = tidy(text)
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def elapsed(ms: int) -> str:
    seconds = max(0, ms // 1000)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def job_pairs(state: QualityState) -> list[dict]:
    return [p for p in state.get("pairs") or [] if p.get("kind") == "job_related"][:MAX_QUESTIONS]


def ask(system_prompt: str, user_prompt: str, answer_shape):
    return ask_llm(system_prompt, user_prompt, answer_shape, model=settings.assessment_model, max_retries=6)


# ---------- 4. The steps ----------
def measure(state: QualityState) -> dict:
    """Plain code, so the same interview always gives the same numbers."""
    turns = state.get("turns") or []
    if not turns:
        return {"error": "This interview has no transcript to review."}
    pairs = state.get("pairs") or []
    coverage = state.get("coverage") or []

    talk: Counter = Counter()
    for turn in turns:
        talk[turn["speaker"]] += max(0, turn["end_ms"] - turn["start_ms"])
    spoken = sum(talk.values()) or 1
    answers = [turn["end_ms"] - turn["start_ms"] for turn in turns if turn["speaker"] == "candidate"]
    asked = [p for p in pairs if p.get("kind") == "job_related"]
    status = Counter(item["status"] for item in coverage)

    measures = {
        "minutes": round((turns[-1]["end_ms"] - turns[0]["start_ms"]) / 60000, 1),
        "interviewer_talk_pct": round(100 * talk["interviewer"] / spoken),
        "questions": len(asked),
        "small_talk": len(pairs) - len(asked),
        "follow_ups": sum(len(p.get("follow_ups") or []) for p in asked),
        "longest_answer_s": round(max(answers, default=0) / 1000),
        "average_answer_s": round(mean(answers) / 1000) if answers else 0,
        "requirements": len(coverage),
        "explored": status["explored"],
        "weak": status["weak"],
        "not_explored": status["not_explored"],
        "coverage_pct": round(100 * status["explored"] / len(coverage)) if coverage else 0,
    }
    personal = [
        {"turn": turn["n"], "at": elapsed(turn["start_ms"]), "text": clip(turn["text"], 200)}
        for turn in turns
        if turn["speaker"] == "interviewer" and PERSONAL.search(turn["text"])
    ]
    others = [item for item in state.get("others") or [] if item]
    compare = {
        "interviews": len(others),
        "average": {key: round(mean(item.get(key, 0) for item in others), 1) for key in COMPARED} if others else {},
    }
    return {"measures": measures, "personal": personal, "compare": compare, "attempts": 0, "problems": []}


SYSTEM_PROMPT = (
    "You review how a job interview was run, to help the interviewer improve. You do not judge the candidate. "
    "For each job question (Q) give its kind: open (invites a full answer), probing (a good follow-up that asks "
    "for detail), closed (yes/no or one word), leading (suggests the answer) or unclear (hard to understand or "
    "several questions at once). Then write a two-sentence summary and two to four concrete recommendations. "
    "Each recommendation names the transcript turn it is about (12 for T12), or 0 if it is about the whole "
    "interview. Use only turns you were shown. Base everything on the numbers and the transcript you see. "
    "A question that starts with what, how, why or which, or asks the candidate to describe or explain, is never "
    "closed. The transcript comes from speech-to-text: do not blame the interviewer for wrong words. "
    "Never comment on the candidate's or the interviewer's age, gender, ethnicity, religion, nationality or health."
)

HR_NOTE = (
    " This was an HR interview round: judge how well it explored the HR topics (communication, motivation, "
    "teamwork, situational judgement, professionalism, expectations). Never recommend technical questions."
)


def prompt_for(state: QualityState) -> str:
    by_n = {turn["n"]: turn for turn in state["turns"]}
    m = state["measures"]
    hr_round = state.get("round_type") == "hr"
    lines = [
        f"Job: {state['job']['title']}",
        "",
        "Measured by plain code:",
        f"- The interview lasted {m['minutes']} minutes; the interviewer talked {m['interviewer_talk_pct']}% of the time.",
        f"- {m['questions']} job questions, {m['follow_ups']} follow-up questions, {m['small_talk']} small-talk exchanges.",
        f"- {'HR topics' if hr_round else 'Requirements'}: {m['explored']} explored, "
        f"{m['weak']} weakly explored, {m['not_explored']} not explored.",
    ]
    missed = [item["requirement"] for item in state.get("coverage") or [] if item["status"] == "not_explored"]
    if missed:
        lines.append("- Not explored: " + ", ".join(missed))
    average = state["compare"].get("average")
    if average:
        lines.append(
            f"- The other {state['compare']['interviews']} interviews for this job average: interviewer talk "
            f"{average['interviewer_talk_pct']}%, {average['questions']} job questions, {average['follow_ups']} follow-ups, "
            f"{average['coverage_pct']}% of {'HR topics' if hr_round else 'requirements'} explored."
        )
    lines += ["", "The job questions (Q) with their transcript turns (T):"]
    for pair in job_pairs(state):
        lines.append(f"[Q{pair['id']}] {clip(pair['question'], 250)}")
        for n in pair.get("turns", [])[:4]:
            turn = by_n.get(n)
            if turn:
                who = "Candidate" if turn["speaker"] == "candidate" else "Interviewer"
                lines.append(f"  [T{n}, {elapsed(turn['start_ms'])}] {who}: {clip(turn['text'], TURN_CHARS)}")
    return "\n".join(lines)


def review(state: QualityState) -> dict:
    prompt = prompt_for(state)
    if state.get("problems"):
        prompt += "\n\nYour last answer had these problems. Fix them:\n- " + "\n- ".join(state["problems"])
    try:
        system = SYSTEM_PROMPT + (HR_NOTE if state.get("round_type") == "hr" else "")
        answer = ask(system, prompt, Review)
    except LLMUnavailable as error:
        return {"error": str(error)}
    return {"draft": answer.model_dump(), "attempts": state.get("attempts", 0) + 1}


def check_review(state: QualityState) -> dict:
    """Plain code: every recommendation points to a real turn (or 0 for the whole interview)."""
    by_n = {turn["n"]: turn for turn in state["turns"]}
    draft = state["draft"]
    problems, recommendations = [], []
    for item in draft.get("recommendations") or []:
        text, turn = tidy(item.get("text")), int(item.get("turn") or 0)
        if not text:
            continue
        if turn and turn not in by_n:
            problems.append(f'"{clip(text, 80)}" points to turn {turn}, which does not exist.')
            continue
        recommendations.append({"text": text, "turn": turn or None, "at": elapsed(by_n[turn]["start_ms"]) if turn else None})
    if not recommendations:
        problems.append("Give two to four recommendations.")
    if problems and state["attempts"] < MAX_ATTEMPTS:
        return {"problems": problems}

    rated = {item["id"]: item for item in draft.get("questions") or [] if item.get("kind") in KINDS}
    questions = []
    for pair in job_pairs(state):
        found = rated.get(pair["id"])
        kind = found["kind"] if found else "unrated"  # a question the AI skipped is shown, not hidden
        if kind == "closed" and OPEN_START.match(pair["question"]):
            kind = "open"  # plain code: "What do you use to deploy it?" is not a yes/no question
        questions.append({
            "id": pair["id"],
            "question": pair["question"],
            "at": elapsed(pair.get("start_ms", 0)),
            "kind": kind,
            "label": LABELS[kind],
            "note": tidy(found["note"]) if found else "",
        })
    return {
        "questions": questions,
        "kinds": dict(Counter(q["kind"] for q in questions)),
        "recommendations": recommendations[:MAX_RECOMMENDATIONS],
        "summary": tidy(draft.get("summary")),
        "problems": [],
    }


def failed(state: QualityState) -> dict:
    log.warning("quality agent stopped with an error", extra={"event": "quality_failed"})
    return {}


def next_or_failed(next_step: str):
    def route(state: QualityState) -> str:
        return "failed" if has_error(state) else next_step

    return route


def after_checking(state: QualityState) -> str:
    return "review" if state.get("problems") else END


# ---------- 5. The graph ----------
@lru_cache
def get_quality_agent():
    graph = StateGraph(QualityState)
    graph.add_node("measure", measure)
    graph.add_node("review", review)
    graph.add_node("check_review", check_review)
    graph.add_node("failed", failed)

    graph.add_edge(START, "measure")
    graph.add_conditional_edges("measure", next_or_failed("review"), ["review", "failed"])
    graph.add_conditional_edges("review", next_or_failed("check_review"), ["check_review", "failed"])
    # check_review can send the answer back to review once: a loop in the graph.
    graph.add_conditional_edges("check_review", after_checking, ["review", END])
    graph.add_edge("failed", END)
    return graph.compile()