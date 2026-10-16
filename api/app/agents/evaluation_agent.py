"""The Evaluation Agent (Module 9): reads a finished interview and judges the candidate's answers.

The steps, each one node of the LangGraph graph:
1. segment_pairs     the transcript becomes question-answer pairs. A question with several parts
                     becomes one pair per part; a follow-up ("Can you give an example?") joins the
                     question it follows (Task 9.1.2, Q&A 38).
2. classify_pairs    job-related exchange or small talk. Small talk is kept, but never scored (Q&A 16).

Turning transcript lines into turns and turns into exchanges is plain code, so the same transcript
always gives the same raw material. The AI only decides what plain code cannot: where one question
ends and the next begins, and what an exchange is about.
"""

import logging
from functools import lru_cache
from typing import Literal

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agents.common import AgentState, has_error
from app.llm import LLMUnavailable, ask_llm
from app.settings import settings

log = logging.getLogger("talentsight.evaluation_agent")

BATCH = 12          # exchanges or pairs in one AI call, to stay inside Groq's free per-minute limit
TURN_CHARS = 1500   # the longest piece of one turn the AI is shown


# ---------- 1. The state ----------
class EvaluationState(AgentState, total=False):
    turns: list[dict]   # input: [{"n", "speaker", "text", "start_ms", "end_ms"}], see build_turns()
    job: dict           # input: {"title", "description", "requirements"}, like the Screening Agent
    pairs: list[dict]   # the question-answer pairs, filled in step by step


# ---------- 2. The answer shapes ----------
class ExchangePlan(BaseModel):
    number: int = Field(description="The exchange's number")
    questions: list[str] = Field(
        description="Each separate question the interviewer asked, as one short complete question. "
        "Empty when the interviewer asked nothing."
    )
    follow_up: bool = Field(description="True when this exchange only continues the previous question")


class Segmentation(BaseModel):
    exchanges: list[ExchangePlan]


class PairKind(BaseModel):
    id: int = Field(description="The pair's number")
    kind: Literal["job_related", "small_talk"]


class PairKinds(BaseModel):
    pairs: list[PairKind]


# ---------- 3. Plain code: from transcript lines to exchanges ----------
def build_turns(segments: list[dict]) -> list[dict]:
    """Joins lines in a row from the same speaker into one turn, numbered from 1.

    segments: [{"speaker", "text", "start_ms", "end_ms"}] in time order (the saved transcript).
    """
    turns: list[dict] = []
    for segment in segments:
        text = " ".join(segment["text"].split())
        if not text:
            continue
        if turns and turns[-1]["speaker"] == segment["speaker"]:
            turns[-1]["text"] += f" {text}"
            turns[-1]["end_ms"] = max(turns[-1]["end_ms"], segment["end_ms"])
        else:
            turns.append({
                "n": len(turns) + 1,
                "speaker": segment["speaker"],
                "text": text,
                "start_ms": segment["start_ms"],
                "end_ms": segment["end_ms"],
            })
    return turns


def group_exchanges(turns: list[dict]) -> list[dict]:
    """An exchange = what the interviewer said, then what the candidate said until the interviewer spoke again."""
    exchanges: list[dict] = []
    for turn in turns:
        if turn["speaker"] == "interviewer" or not exchanges:
            exchanges.append({"question": [], "answer": []})
        side = "question" if turn["speaker"] == "interviewer" else "answer"
        exchanges[-1][side].append(turn)
    return exchanges


def clip(text: str, limit: int = TURN_CHARS) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def said(turns: list[dict]) -> str:
    return " ".join(turn["text"] for turn in turns)


def ask(system_prompt: str, user_prompt: str, answer_shape):
    """ask_llm with the evaluation model, and patience for Groq's per-minute limit."""
    return ask_llm(system_prompt, user_prompt, answer_shape, model=settings.evaluation_model, max_retries=6)


SEGMENT_PROMPT = (
    "You split a job interview into questions. You get numbered exchanges: what the interviewer said, "
    "then what the candidate answered. For EVERY exchange give: "
    "questions = each separate question the interviewer asked, rewritten as one short, complete question "
    "in the interviewer's own terms. Split a multi-part question ('What is X, and when would you use Y?') "
    "into its parts. Give an empty list when the interviewer asked nothing (a greeting, thanks, an "
    "instruction, a comment). "
    "follow_up = true only when the interviewer asks the candidate to go on with the PREVIOUS question "
    "('Can you give an example?', 'Why?', 'Anything else?') instead of asking something new. "
    "Use only what the transcript says."
)

CLASSIFY_PROMPT = (
    "You sort interview questions. job_related = the exchange tests the candidate's skills, knowledge, "
    "experience, way of working, problem solving or motivation for the role. small_talk = greetings, "
    "checking the audio, chit-chat, scheduling and logistics, the interviewer introducing the company, "
    "and 'Do you have any questions for us?'. When in doubt, choose job_related. Give a kind for EVERY pair."
)


# ---------- 4. The steps ----------
def segment_pairs(state: EvaluationState) -> dict:
    """Task 9.1.2: question-answer pairs, with multi-part questions split and follow-ups joined (Q&A 38)."""
    exchanges = group_exchanges(state["turns"])

    plans: dict[int, ExchangePlan] = {}
    for start in range(0, len(exchanges), BATCH):
        shown = []
        for number, exchange in enumerate(exchanges[start : start + BATCH], start=start + 1):
            question = clip(said(exchange["question"])) or "(nothing)"
            answer = clip(said(exchange["answer"])) or "(no answer)"
            shown.append(f"Exchange {number}\nInterviewer: {question}\nCandidate: {answer}")
        try:
            answer = ask(SEGMENT_PROMPT, "\n\n".join(shown), Segmentation)
        except LLMUnavailable as error:
            return {"error": str(error)}
        plans.update({plan.number: plan for plan in answer.exchanges})

    pairs: list[dict] = []
    for number, exchange in enumerate(exchanges, start=1):
        plan = plans.get(number)  # an exchange the AI skipped is simply kept as one pair
        asked = said(exchange["question"])
        turn_numbers = [t["n"] for t in exchange["question"] + exchange["answer"]]
        answer_numbers = [t["n"] for t in exchange["answer"]]

        if plan and plan.follow_up and pairs:
            # The follow-up and its answer belong to the question it follows (the last part of it).
            previous = pairs[-1]
            previous["follow_ups"].append(asked)
            previous["turns"] += turn_numbers
            previous["answer_turns"] += answer_numbers
            continue

        questions = [q.strip() for q in plan.questions if q.strip()] if plan else []
        if not questions:
            questions = [asked or "(The candidate spoke before any question.)"]
        for part, question in enumerate(questions, start=1):
            pairs.append({
                "id": len(pairs) + 1,
                "question": question,
                "asked": asked,  # the interviewer's own words, for the record
                "turns": list(turn_numbers),
                "answer_turns": list(answer_numbers),
                "part": part,
                "parts": len(questions),  # 2 or more = one part of a multi-part question
                "follow_ups": [],
                "start_ms": (exchange["question"] or exchange["answer"])[0]["start_ms"],
            })
    return {"pairs": pairs}


def classify_pairs(state: EvaluationState) -> dict:
    """Task 9.1.2: job-related or small talk. Small talk stays in the record but is never scored (Q&A 16)."""
    by_n = {turn["n"]: turn for turn in state["turns"]}
    pairs = [dict(pair) for pair in state["pairs"]]

    kinds: dict[int, str] = {}
    for start in range(0, len(pairs), BATCH):
        shown = []
        for pair in pairs[start : start + BATCH]:
            answer = clip(" ".join(by_n[n]["text"] for n in pair["answer_turns"]), 400) or "(no answer)"
            shown.append(f"{pair['id']}. Question: {pair['question']}\nAnswer: {answer}")
        try:
            answer = ask(CLASSIFY_PROMPT, "\n\n".join(shown), PairKinds)
        except LLMUnavailable as error:
            return {"error": str(error)}
        kinds.update({item.id: item.kind for item in answer.pairs})

    for pair in pairs:
        pair["kind"] = kinds.get(pair["id"], "job_related")  # a pair the AI skipped is checked, not hidden
    return {"pairs": pairs}


def failed(state: EvaluationState) -> dict:
    log.warning("evaluation agent stopped with an error", extra={"event": "evaluation_failed"})
    return {}


def next_or_failed(next_step: str):
    """After an AI step: go on, or stop at "failed" when the step could not finish."""

    def route(state: EvaluationState) -> str:
        return "failed" if has_error(state) else next_step

    return route


# ---------- 5. The graph ----------
@lru_cache
def get_evaluation_agent():
    graph = StateGraph(EvaluationState)
    graph.add_node("segment_pairs", segment_pairs)
    graph.add_node("classify_pairs", classify_pairs)
    graph.add_node("failed", failed)

    graph.add_edge(START, "segment_pairs")
    graph.add_conditional_edges("segment_pairs", next_or_failed("classify_pairs"), ["classify_pairs", "failed"])
    graph.add_conditional_edges("classify_pairs", next_or_failed(END), [END, "failed"])
    graph.add_edge("failed", END)
    return graph.compile()