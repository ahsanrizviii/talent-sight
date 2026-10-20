"""The Question Chat Agent (Module 13): suggests interview questions grounded in the CV and the transcript.

The interviewer types a message in the Chat tab of the interview room ("what should I ask about
Kubernetes?", "they said they led the migration, how do I check that?"). The agent answers in a few
sentences and suggests up to three questions. Every suggestion must point to what it is based on:
a CV line (C3), a transcript turn (T12) or a job requirement (R2). Plain code checks those pointers and
the wording; a suggestion that fails is sent back to the AI once, then dropped.

Steps:
    gather_context  (plain code) picks the CV lines, the requirements and the transcript turns to show
    write_reply     (AI)         writes the answer and the suggested questions
    check_sources   (plain code) every suggestion names a real C/T/R line and asks nothing personal (N20);
                                 problems go back to write_reply once (a loop in the graph)

Interviewer only (N9). It never changes a score, an assessment or a stage.
"""

import logging
import re
from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agents.common import AgentState, has_error
from app.llm import LLMUnavailable, ask_llm

log = logging.getLogger("talentsight.chat_agent")

RECENT_TURNS = 14      # the newest transcript turns always shown
RELATED_TURNS = 4      # older turns shown because they share words with the interviewer's message
TURN_CHARS = 400       # the longest piece of one turn the AI is shown
HISTORY = 6            # earlier chat messages shown, so a follow-up ("and the second one?") makes sense
MAX_SUGGESTIONS = 3
MAX_ATTEMPTS = 2       # the AI is asked again once when a suggestion fails the checks
SOURCE_CHARS = 240     # how much of the source line the screen shows

# Questions about these are not allowed in an interview (N20). Checked on every suggested question.
PERSONAL = re.compile(
    r"\b(how old|your age|age|date of birth|born in|married|marital|spouse|wife|husband|boyfriend|girlfriend|"
    r"pregnan\w*|have children|any kids|your kids|family plans|religio\w*|pray\w*|church|mosque|caste|ethnic\w*|"
    r"your race|nationality|citizenship|where are you from|disabilit\w*|medical condition|medical history|"
    r"illness|health condition|sexual\w*|gender|political|union member\w*)\b",
    re.IGNORECASE,
)
SOURCE_ID = re.compile(r"\b([CTR])\s*(\d+)\b", re.IGNORECASE)
COMMON = {"what", "when", "which", "with", "about", "that", "this", "they", "their", "them", "have", "should",
          "would", "could", "does", "there", "were", "your", "from", "into", "more", "some", "just", "like",
          "said", "tell", "candidate", "question", "questions", "ask", "next"}


# ---------- 1. The state ----------
class ChatState(AgentState, total=False):
    # Input (see interview_chat.answer)
    message: str     # what the interviewer typed
    history: list    # earlier messages: [{"role", "text", "suggestions"}], oldest first
    job: dict        # {"title", "requirements": [text, ...]}
    cv: list         # [{"id": "C1", "text"}]
    turns: list      # [{"n", "speaker", "text", "start_ms", "end_ms"}]
    coverage: list   # [{"requirement", "status"}]
    # Filled in step by step
    shown: dict      # source id -> {"kind", "text", ...} for everything the AI was shown
    prompt: str
    draft: dict      # the AI's last answer
    problems: list   # what was wrong with the last answer, sent back once
    attempts: int
    reply: str
    suggestions: list


# ---------- 2. The answer shape ----------
class Suggestion(BaseModel):
    question: str = Field(description="One question the interviewer can ask the candidate, in plain words")
    why: str = Field(description="One short sentence on what the answer would show")
    source: str = Field(description="The one line it is based on: a CV line like C3, a transcript turn like T12, or a requirement like R2")


class ChatReply(BaseModel):
    reply: str = Field(description="A short answer to the interviewer, at most three sentences, without the questions themselves")
    suggestions: list[Suggestion] = Field(description="Zero to three suggested questions")


# ---------- 3. Small helpers ----------
def tidy(text) -> str:
    return " ".join(str(text or "").split())


def clip(text: str, limit: int) -> str:
    text = tidy(text)
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def elapsed(ms: int) -> str:
    """75 000 ms -> "01:15", the same clock the transcript shows."""
    seconds = max(0, ms // 1000)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#.]{4,}", text.lower()) if w not in COMMON}


def ask(system_prompt: str, user_prompt: str, answer_shape):
    return ask_llm(system_prompt, user_prompt, answer_shape, max_retries=4)


# ---------- 4. The steps ----------
def gather_context(state: ChatState) -> dict:
    """Picks what the AI is shown and numbers it, so every suggestion can point to one line."""
    turns = state.get("turns") or []
    recent = turns[-RECENT_TURNS:]
    # Older turns that share words with the message ("the migration they mentioned") are shown too.
    asked = words(state["message"])
    older = [t for t in turns[: max(0, len(turns) - RECENT_TURNS)] if len(asked & words(t["text"])) >= 2]
    older.sort(key=lambda t: -len(asked & words(t["text"])))
    picked = sorted(older[:RELATED_TURNS] + recent, key=lambda t: t["n"])

    shown: dict[str, dict] = {}
    lines = [f"Job: {state['job']['title']}", "", "Job requirements (R) and how far the interview has covered them:"]
    coverage = {item["requirement"]: item["status"] for item in state.get("coverage") or []}
    for n, requirement in enumerate(state["job"].get("requirements", []), start=1):
        shown[f"R{n}"] = {"kind": "requirement", "text": requirement}
        lines.append(f"[R{n}] {requirement} ({coverage.get(requirement, 'not_mentioned').replace('_', ' ')})")

    lines += ["", "The candidate's CV (C):"]
    for line in state.get("cv") or []:
        shown[line["id"]] = {"kind": "cv", "text": line["text"]}
        lines.append(f"[{line['id']}] {line['text']}")
    if not state.get("cv"):
        lines.append("(no CV profile yet)")

    lines += ["", "The interview transcript so far (T):"]
    for turn in picked:
        who = "Candidate" if turn["speaker"] == "candidate" else "Interviewer"
        shown[f"T{turn['n']}"] = {"kind": "transcript", "turn": turn["n"], "at": elapsed(turn["start_ms"]),
                                  "speaker": turn["speaker"], "text": turn["text"]}
        lines.append(f"[T{turn['n']}, {elapsed(turn['start_ms'])}] {who}: {clip(turn['text'], TURN_CHARS)}")
    if not picked:
        lines.append("(nothing said yet)")

    history = (state.get("history") or [])[-HISTORY:]
    if history:
        lines += ["", "Earlier in this chat:"]
        for item in history:
            if item["role"] == "interviewer":
                lines.append(f"Interviewer: {clip(item['text'], 300)}")
            else:
                asked_before = "; ".join(s["question"] for s in item.get("suggestions") or [])
                lines.append(f"You: {clip(item['text'], 300)}" + (f" Suggested: {asked_before}" if asked_before else ""))

    lines += ["", f"The interviewer now asks: {state['message']}"]
    return {"shown": shown, "prompt": "\n".join(lines), "attempts": 0, "problems": []}


SYSTEM_PROMPT = (
    "You help an interviewer during a job interview. You see the job requirements (R), the candidate's CV (C) "
    "and the transcript so far (T). Answer the interviewer's message in at most three short sentences, then "
    "suggest up to three questions they could ask the candidate next. Good questions ask for concrete detail "
    "(what they built, how, why, what went wrong), follow up on vague answers, or explore requirements the "
    "interview has not covered yet. Do not repeat questions already asked in the transcript or suggested earlier.\n"
    "Every suggestion must name exactly one line it is based on, by its id: a CV line (C3), a transcript turn "
    "(T12) or a requirement (R2). Only use ids you were shown. Base everything on what you were shown; never "
    "invent facts about the candidate.\n"
    "Never suggest questions about age, family, marriage, children, pregnancy, religion, ethnicity, "
    "nationality, health, disability, gender, sexuality or politics, and decline politely if asked for them. "
    "Do not judge the candidate's honesty or character. If the message is not about this interview, say you "
    "can only help with this interview and suggest nothing."
)


def write_reply(state: ChatState) -> dict:
    """The AI writes the answer and the suggestions. On a second try it is told what was wrong."""
    prompt = state["prompt"]
    if state.get("problems"):
        prompt += "\n\nYour last answer had these problems. Fix them:\n- " + "\n- ".join(state["problems"])
    try:
        answer = ask(SYSTEM_PROMPT, prompt, ChatReply)
    except LLMUnavailable as error:
        return {"error": str(error)}
    return {"draft": answer.model_dump(), "attempts": state.get("attempts", 0) + 1}


def check_sources(state: ChatState) -> dict:
    """Plain code: every suggestion points to a line the AI was shown and asks nothing personal (N20)."""
    shown = state["shown"]
    draft = state["draft"]
    kept, problems, seen = [], [], set()
    for item in (draft.get("suggestions") or [])[: MAX_SUGGESTIONS + 2]:
        question = tidy(item.get("question"))
        if not question or question.lower() in seen:
            continue
        found = SOURCE_ID.search(str(item.get("source") or ""))
        source_id = f"{found.group(1).upper()}{found.group(2)}" if found else ""
        if PERSONAL.search(question):
            problems.append(f'"{question}" asks about a personal matter that must not be asked in an interview. Replace it.')
        elif source_id not in shown:
            problems.append(f'"{question}" does not name a line you were shown (C, T or R with its number).')
        else:
            seen.add(question.lower())
            kept.append({"question": question, "why": tidy(item.get("why")), "source": source_of(source_id, shown[source_id])})

    if problems and state["attempts"] < MAX_ATTEMPTS:
        return {"problems": problems}
    reply = tidy(draft.get("reply")) or ("Here are some questions to ask next." if kept else "I have nothing to suggest for that.")
    return {"reply": reply, "suggestions": kept[:MAX_SUGGESTIONS], "problems": []}


def source_of(source_id: str, line: dict) -> dict:
    """What the screen shows under a suggestion: the line it is based on."""
    found = {"id": source_id, "kind": line["kind"], "text": clip(line["text"], SOURCE_CHARS)}
    if line["kind"] == "transcript":
        found.update(turn=line["turn"], at=line["at"], speaker=line["speaker"])
    return found


def failed(state: ChatState) -> dict:
    log.warning("chat agent stopped with an error", extra={"event": "chat_failed"})
    return {}


def after_writing(state: ChatState) -> str:
    return "failed" if has_error(state) else "check_sources"


def after_checking(state: ChatState) -> str:
    return "write_reply" if state.get("problems") else END


# ---------- 5. The graph ----------
@lru_cache
def get_chat_agent():
    graph = StateGraph(ChatState)
    graph.add_node("gather_context", gather_context)
    graph.add_node("write_reply", write_reply)
    graph.add_node("check_sources", check_sources)
    graph.add_node("failed", failed)

    graph.add_edge(START, "gather_context")
    graph.add_edge("gather_context", "write_reply")
    graph.add_conditional_edges("write_reply", after_writing, ["check_sources", "failed"])
    # check_sources can send the answer back to write_reply once: a loop in the graph.
    graph.add_conditional_edges("check_sources", after_checking, ["write_reply", END])
    graph.add_edge("failed", END)
    return graph.compile()