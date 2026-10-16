import logging
from functools import lru_cache
from typing import Literal

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app import references
from app.agents.common import AgentState, has_error
from app.db import SessionLocal
from app.llm import LLMUnavailable, ask_llm
from app.settings import settings

log = logging.getLogger("talentsight.evaluation_agent")

BATCH = 12          # exchanges or pairs in one AI call, to stay inside Groq's free per-minute limit
TURN_CHARS = 1500   # the longest piece of one turn the AI is shown
MAX_SCORE_ATTEMPTS = 2  # one retry if a score is outside 0-100
DIMENSIONS = ("relevance", "accuracy", "completeness", "articulation")


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
    

class RequirementLink(BaseModel):
    id: int = Field(description="The pair's number")
    requirements: list[int] = Field(description="Numbers of the requirements this exchange gives evidence about")


class RequirementLinks(BaseModel):
    pairs: list[RequirementLink]


class DimensionScore(BaseModel):
    score: int = Field(description="0 to 100")
    justification: str = Field(description="One or two sentences naming what in the answer supports the score")


class AnswerScores(BaseModel):
    relevance: DimensionScore
    accuracy: DimensionScore
    completeness: DimensionScore
    articulation: DimensionScore
    evidence_turn: int = Field(description="The number of the candidate turn that best supports the scores")
    quote: str = Field(description="A short exact quote from that turn, at most 20 words")


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



def elapsed(ms: int) -> str:
    """75 000 ms -> "01:15", the same clock the transcript shows (Q&A 31)."""
    seconds = max(0, ms // 1000)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def find_references(question: str) -> list[dict]:
    """The three sections of the skills documents closest to the question (Task 9.1.1)."""
    with SessionLocal() as db:
        found = references.search_references(db, question, limit=3)
        return [{"skill": c.skill, "heading": c.heading, "url": c.url, "text": c.text} for c in found]


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



MAP_PROMPT = (
    "You link interview exchanges to a job's requirements. For EVERY numbered pair list the numbers of the "
    "requirements it gives evidence about: the question asks about the requirement, or the answer shows "
    "(or fails to show) it. Match by meaning, not exact words (PostgreSQL counts for SQL databases). "
    "Give an empty list when the exchange touches none of them."
)

SCORE_PROMPT = (
    "You evaluate one answer from a job interview. Score four dimensions from 0 to 100 in steps of 5, "
    "using only the conversation and the reference notes. "
    "relevance: does the answer address the question that was asked (100 = fully on point, 0 = off topic). "
    "accuracy: are the facts and technical claims correct? Check them against the reference notes. "
    "100 = nothing wrong; take points off for each wrong or doubtful claim; when the answer makes no "
    "technical claim, judge whether it is plausible and consistent. "
    "completeness: does it cover the main points a good answer would, including every part of the "
    "question and the follow-ups? "
    "articulation: is it clear, structured and easy to follow? Ignore small speech-to-text errors. "
    "Every justification is one or two sentences and names what in the answer supports the score. "
    "evidence_turn is the number of the candidate turn that best supports the scores, and quote is a "
    "short exact quote from it."
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


def map_requirements(state: EvaluationState) -> dict:
    """Task 9.1.3: the requirements each job-related pair speaks to, so coverage gaps can be seen."""
    requirements = state["job"]["requirements"]
    by_n = {turn["n"]: turn for turn in state["turns"]}
    pairs = [{**pair, "requirements": []} for pair in state["pairs"]]
    job_related = [pair for pair in pairs if pair["kind"] == "job_related"]
    if not requirements or not job_related:
        return {"pairs": pairs}

    numbered = "\n".join(f"{i}. {r['requirement']}" for i, r in enumerate(requirements, start=1))
    links: dict[int, list[int]] = {}
    for start in range(0, len(job_related), BATCH):
        shown = []
        for pair in job_related[start : start + BATCH]:
            answer = clip(" ".join(by_n[n]["text"] for n in pair["answer_turns"]), 600) or "(no answer)"
            shown.append(f"{pair['id']}. Question: {pair['question']}\nAnswer: {answer}")
        prompt = f"Requirements:\n{numbered}\n\nPairs:\n" + "\n\n".join(shown)
        try:
            answer = ask(MAP_PROMPT, prompt, RequirementLinks)
        except LLMUnavailable as error:
            return {"error": str(error)}
        links.update({item.id: item.requirements for item in answer.pairs})

    for pair in job_related:
        # Only numbers that exist, each once, in order: the AI cannot invent a requirement.
        pair["requirements"] = sorted({n for n in links.get(pair["id"], []) if 1 <= n <= len(requirements)})
    return {"pairs": pairs}


def score_one(pair: dict, state: EvaluationState) -> dict | str:
    """The four scores of one answer, or the error message when the AI could not give them."""
    by_n = {turn["n"]: turn for turn in state["turns"]}
    job = state["job"]
    if not pair["answer_turns"]:
        reason = "The candidate did not answer this question."
        return {
            "scores": {d: {"score": 0, "justification": reason} for d in DIMENSIONS},
            "overall": 0,
            "evidence": None,
            "references": [],
        }

    linked = [job["requirements"][n - 1]["requirement"] for n in pair["requirements"]]
    notes = find_references(" ".join([pair["question"], *linked]))
    conversation = "\n".join(
        f"[turn {n}, {elapsed(by_n[n]['start_ms'])}] "
        f"{'Interviewer' if by_n[n]['speaker'] == 'interviewer' else 'Candidate'}: {clip(by_n[n]['text'])}"
        for n in pair["turns"]
    )
    prompt = (
        f"Job: {job['title']}\n"
        f"Question being scored: {pair['question']}\n"
        + (f"Follow-up questions: {' | '.join(pair['follow_ups'])}\n" if pair["follow_ups"] else "")
        + (f"Requirements it relates to: {'; '.join(linked)}\n" if linked else "")
        + f"\nConversation:\n{conversation}\n\nReference notes:\n"
        + ("\n".join(f"- {clip(note['text'], 900)}" for note in notes) or "(none)")
    )

    for _ in range(MAX_SCORE_ATTEMPTS):
        try:
            answer = ask(SCORE_PROMPT, prompt, AnswerScores)
        except LLMUnavailable as error:
            return str(error)
        scores = {d: getattr(answer, d).model_dump() for d in DIMENSIONS}
        if all(0 <= s["score"] <= 100 for s in scores.values()):
            break
    else:
        return "The AI gave a score outside 0-100."

    for s in scores.values():
        s["score"] = int(5 * round(s["score"] / 5))  # steps of 5, like the CV scores (Module 6)

    # The evidence must point at something the candidate really said in this exchange:
    # the turn that holds the quote, or else the turn named, with its own words instead of the quote.
    quote = " ".join(answer.quote.split()).strip('"')
    holding = [n for n in pair["answer_turns"] if quote and quote.lower() in by_n[n]["text"].lower()]
    if holding:
        turn = answer.evidence_turn if answer.evidence_turn in holding else holding[0]
    else:
        turn = answer.evidence_turn if answer.evidence_turn in pair["answer_turns"] else pair["answer_turns"][0]
        quote = clip(by_n[turn]["text"], 160)  # never show words the candidate did not say
    return {
        "scores": scores,
        "overall": round(sum(s["score"] for s in scores.values()) / len(scores)),
        "evidence": {"turn": turn, "start_ms": by_n[turn]["start_ms"], "quote": quote},
        "references": [{"skill": n["skill"], "heading": n["heading"], "url": n["url"]} for n in notes],
    }


def score_answers(state: EvaluationState) -> dict:
    """Task 9.1.3: every job-related answer scored on four dimensions. Small talk is not scored (Q&A 16)."""
    pairs = []
    for pair in state["pairs"]:
        pair = {**pair, "scores": None, "overall": None, "evidence": None, "references": []}
        if pair["kind"] == "job_related":
            result = score_one(pair, state)
            if isinstance(result, str):
                return {"error": result}
            pair.update(result)
        pairs.append(pair)
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
    graph.add_node("map_requirements", map_requirements)
    graph.add_node("score_answers", score_answers)
    graph.add_node("failed", failed)

    graph.add_edge(START, "segment_pairs")
    graph.add_conditional_edges("segment_pairs", next_or_failed("classify_pairs"), ["classify_pairs", "failed"])
    graph.add_conditional_edges("classify_pairs", next_or_failed("map_requirements"), ["map_requirements", "failed"])
    graph.add_conditional_edges("map_requirements", next_or_failed("score_answers"), ["score_answers", "failed"])
    graph.add_conditional_edges("score_answers", next_or_failed(END), [END, "failed"])
    graph.add_edge("failed", END)
    return graph.compile()