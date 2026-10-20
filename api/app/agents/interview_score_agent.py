"""The Interview Scoring Agent (Module 13, F9): one score for the interview, in six parts.

It scores the candidate's interview as a whole, separately from the CV score (Module 6). Five parts
come from the AI, each with a reason and the candidate turn it rests on: technical competency,
problem-solving, depth of experience, relevance of answers and communication. Alignment with the
requirements comes from the requirement coverage, by plain code. Every part is in steps of 5, and the
overall score is a weighted average with fixed weights, worked out by plain code.

Steps:
    measure_alignment (plain code) explored 100, weak 50, not explored 0; required requirements count double
    score             (AI)         the other five parts, each with a reason and a candidate turn
    check_scores      (plain code) every part is scored and rests on a real answer turn; problems go back once
"""

import logging
from collections import Counter
from functools import lru_cache
from typing import Literal

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agents.common import AgentState, has_error
from app.llm import LLMUnavailable, ask_llm
from app.settings import settings

log = logging.getLogger("talentsight.interview_score_agent")

# (key, label, weight). The weights add up to 100 and never change, so totals can be compared.
DIMENSIONS = (
    ("technical", "Technical competency", 25),
    ("problem_solving", "Problem-solving", 20),
    ("depth", "Depth of experience", 15),
    ("relevance", "Relevance of answers", 15),
    ("communication", "Communication", 10),
    ("alignment", "Alignment with requirements", 15),
)
BY_AI = ("technical", "problem_solving", "depth", "relevance", "communication")
COVERAGE_POINTS = {"explored": 100, "weak": 50, "not_explored": 0}
MAX_PAIRS = 12        # job questions shown to the AI (keeps it inside Groq's free limit)
ANSWER_CHARS = 500
MAX_ATTEMPTS = 2      # the AI is asked again once when a part is missing or rests on no answer


# ---------- 1. The state ----------
class ScoreState(AgentState, total=False):
    # Input (see interview_scoring.inputs_for)
    job: dict
    turns: list
    pairs: list
    coverage: list
    # Filled in step by step
    alignment: dict
    draft: dict
    problems: list
    attempts: int
    dimensions: list
    overall: float
    answers: int


# ---------- 2. The answer shape ----------
class PartScore(BaseModel):
    dimension: Literal["technical", "problem_solving", "depth", "relevance", "communication"]
    score: int = Field(description="0 to 100")
    reason: str = Field(description="One neutral sentence on why, naming what the candidate said")
    turn: int = Field(description="The candidate turn that best supports this score, for example 12 for T12")


class InterviewScores(BaseModel):
    scores: list[PartScore]


# ---------- 3. Small helpers ----------
def tidy(text) -> str:
    return " ".join(str(text or "").split())


def clip(text: str, limit: int) -> str:
    text = tidy(text)
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def elapsed(ms: int) -> str:
    seconds = max(0, ms // 1000)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def steps_of_5(value) -> int:
    """Kept between 0 and 100, in steps of 5, like the CV scores (Module 6)."""
    return int(5 * round(max(0, min(100, float(value))) / 5))


def answered_pairs(state: ScoreState) -> list[dict]:
    return [p for p in state.get("pairs") or [] if p.get("kind") == "job_related" and p.get("answer_turns")][:MAX_PAIRS]


def ask(system_prompt: str, user_prompt: str, answer_shape):
    return ask_llm(system_prompt, user_prompt, answer_shape, model=settings.assessment_model, max_retries=6)


# ---------- 4. The steps ----------
def measure_alignment(state: ScoreState) -> dict:
    if not answered_pairs(state):
        return {"error": "The interview has no answered job questions to score."}
    coverage = state.get("coverage") or []
    weights = [(2 if item.get("mandatory") else 1, COVERAGE_POINTS.get(item["status"], 0)) for item in coverage]
    total = sum(weight for weight, _ in weights)
    score = steps_of_5(sum(weight * points for weight, points in weights) / total) if total else 0
    status = Counter(item["status"] for item in coverage)
    reason = (
        f"{status['explored']} of {len(coverage)} requirements explored and {status['weak']} weakly; required ones count double."
        if coverage
        else "The job has no requirements to cover."
    )
    return {"alignment": {"score": score, "reason": reason}, "attempts": 0, "problems": []}


SYSTEM_PROMPT = (
    "You score a candidate's job interview as a whole, from the questions and the candidate's own answers. "
    "Give five parts, each 0 to 100: technical (technical competency for this job), problem_solving (how they "
    "reason through problems), depth (depth of real experience: concrete detail, ownership, results), relevance "
    "(answers address the questions asked) and communication (clear, structured answers). For each part give one "
    "neutral sentence naming what the candidate said, and the candidate turn (T number) that best supports it. "
    "Use only turns you were shown under the answers. The earlier per-answer scores are a guide, not a rule. "
    "Score only what was said: never consider age, gender, ethnicity, religion, nationality, accent or health."
)


def prompt_for(state: ScoreState) -> str:
    by_n = {turn["n"]: turn for turn in state["turns"]}
    names = {item.get("number"): item["requirement"] for item in state.get("coverage") or []}
    lines = [
        f"Job: {state['job']['title']}",
        "Requirements: " + "; ".join(state["job"].get("requirements", [])),
        "",
        "The job questions (Q), the candidate's answers (T) and the earlier per-answer scores (0-100):",
    ]
    for pair in answered_pairs(state):
        linked = [names[n] for n in pair.get("requirements", []) if n in names]
        lines.append(f"[Q{pair['id']}] {clip(pair['question'], 250)}" + (f" (about: {', '.join(linked)})" if linked else ""))
        for n in pair["answer_turns"]:
            turn = by_n.get(n)
            if turn:
                lines.append(f"  [T{n}, {elapsed(turn['start_ms'])}] Candidate: {clip(turn['text'], ANSWER_CHARS)}")
        parts = pair.get("scores") or {}
        if parts:
            lines.append("  Earlier scores: " + ", ".join(f"{name} {value.get('score')}" for name, value in parts.items()))
    return "\n".join(lines)


def score(state: ScoreState) -> dict:
    prompt = prompt_for(state)
    if state.get("problems"):
        prompt += "\n\nYour last answer had these problems. Fix them:\n- " + "\n- ".join(state["problems"])
    try:
        answer = ask(SYSTEM_PROMPT, prompt, InterviewScores)
    except LLMUnavailable as error:
        return {"error": str(error)}
    return {"draft": answer.model_dump(), "attempts": state.get("attempts", 0) + 1}


def check_scores(state: ScoreState) -> dict:
    """Plain code: all five AI parts are there and each rests on a candidate answer turn."""
    by_n = {turn["n"]: turn for turn in state["turns"]}
    answers = {n for pair in answered_pairs(state) for n in pair["answer_turns"]}
    found: dict[str, dict] = {}
    for item in state["draft"].get("scores") or []:
        if item.get("dimension") in BY_AI and item["dimension"] not in found:
            found[item["dimension"]] = item
    missing = [key for key in BY_AI if key not in found]
    problems = [f"Score every part; missing: {', '.join(missing)}."] if missing else []
    for key, item in found.items():
        if int(item.get("turn") or 0) not in answers:
            problems.append(f"{key}: name the candidate turn (a T number shown under the answers) that best supports the score.")
    if problems and state["attempts"] < MAX_ATTEMPTS:
        return {"problems": problems}
    if missing:
        return {"error": "The AI did not score every part of the interview. Please try again."}

    dimensions = []
    for key, label, weight in DIMENSIONS:
        if key == "alignment":
            dimensions.append({"key": key, "label": label, "weight": weight, "score": state["alignment"]["score"],
                               "reason": state["alignment"]["reason"], "evidence": None, "by": "code"})
            continue
        item = found[key]
        turn = int(item.get("turn") or 0)
        evidence = (
            {"turn": turn, "at": elapsed(by_n[turn]["start_ms"]), "text": clip(by_n[turn]["text"], 220)}
            if turn in answers and turn in by_n
            else None  # after the second try a part without proof keeps its score, shown without a quote
        )
        dimensions.append({"key": key, "label": label, "weight": weight, "score": steps_of_5(item.get("score", 0)),
                           "reason": tidy(item.get("reason")), "evidence": evidence, "by": "ai"})
    overall = round(sum(d["score"] * d["weight"] for d in dimensions) / 100, 1)
    return {"dimensions": dimensions, "overall": overall, "answers": len(answered_pairs(state)), "problems": []}


def failed(state: ScoreState) -> dict:
    log.warning("interview score agent stopped with an error", extra={"event": "interview_score_failed"})
    return {}


def next_or_failed(next_step: str):
    def route(state: ScoreState) -> str:
        return "failed" if has_error(state) else next_step

    return route


def after_checking(state: ScoreState) -> str:
    if has_error(state):
        return "failed"
    return "score" if state.get("problems") else END


# ---------- 5. The graph ----------
@lru_cache
def get_interview_score_agent():
    graph = StateGraph(ScoreState)
    graph.add_node("measure_alignment", measure_alignment)
    graph.add_node("score", score)
    graph.add_node("check_scores", check_scores)
    graph.add_node("failed", failed)

    graph.add_edge(START, "measure_alignment")
    graph.add_conditional_edges("measure_alignment", next_or_failed("score"), ["score", "failed"])
    graph.add_conditional_edges("score", next_or_failed("check_scores"), ["check_scores", "failed"])
    # check_scores can send the answer back to score once: a loop in the graph.
    graph.add_conditional_edges("check_scores", after_checking, ["score", "failed", END])
    graph.add_edge("failed", END)
    return graph.compile()