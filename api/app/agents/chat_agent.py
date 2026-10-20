"""The Question Chat Agent (Module 13): a chat assistant for the interviewer, grounded in the CV and the transcript.

The interviewer types in the Chat tab of the interview room and the assistant answers like a colleague:
a greeting gets a greeting, "what have we covered?" gets a list, "write 5 Python questions" gets five
questions (with model answers if asked), "should I ask this?" gets an honest opinion.

Only when the interviewer asks for questions about THIS candidate does the assistant return suggestion cards.
Every card must point to what it is based on: a CV line (C3), a transcript turn (T12) or a job requirement (R2).
Plain code checks those pointers, and checks the wording of cards and replies for personal matters (N20);
a problem is sent back to the AI once.

Steps:
    gather_context  (plain code) picks the CV lines, the requirements and the transcript turns to show
    write_reply     (AI)         writes the answer, and cards when they were asked for
    check_sources   (plain code) every card names a real C/T/R line; nothing personal anywhere (N20);
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

RECENT_TURNS = 30      # the newest transcript turns always shown
RELATED_TURNS = 4      # older turns shown because they share words with the interviewer's message
TURN_CHARS = 400       # the longest piece of one turn the AI is shown
HISTORY = 6            # earlier chat messages shown, so a follow-up ("and the second one?") makes sense
HISTORY_CHARS = 900    # long enough to keep a numbered list the assistant wrote
MAX_SUGGESTIONS = 3
MAX_ATTEMPTS = 2       # the AI is asked again once when something fails the checks
SOURCE_CHARS = 240     # how much of the source line the screen shows

DECLINED = (
    "I can't help with that kind of question in an interview. "
    "I can help with the candidate's skills, experience, the job requirements and how the interview is going."
)

# Questions about these are not allowed in an interview (N20). Checked on every card and every reply.
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
    question: str = Field(description="One question the interviewer can ask this candidate, in plain words")
    why: str = Field(description="One short sentence on what the answer would show")
    source: str = Field(description="The one line it is based on: a CV line like C3, a transcript turn like T12, or a requirement like R2")


class ChatReply(BaseModel):
    reply: str = Field(
        description="The answer to what the interviewer asked, in natural plain text with no markdown symbols. "
                    "As short as the question allows. Use short numbered lines for a list."
    )
    suggestions: list[Suggestion] = Field(
        description="Leave this EMPTY unless the interviewer asked for questions to put to THIS candidate "
                    "(based on their CV, what they said, or requirements not covered yet). Then at most three."
    )


# ---------- 3. Small helpers ----------
def tidy(text) -> str:
    return " ".join(str(text or "").split())


def tidy_block(text) -> str:
    """Like tidy, but keeps the line breaks (one blank line at most), so a numbered list stays a list."""
    lines = [" ".join(line.split()) for line in str(text or "").splitlines()]
    kept: list[str] = []
    for line in lines:
        if line or (kept and kept[-1]):
            kept.append(line)
    return "\n".join(kept).strip()


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
    """Picks what the AI is shown and numbers it, so every card can point to one line."""
    turns = state.get("turns") or []
    recent = turns[-RECENT_TURNS:]
    # Older turns that share words with the message ("the migration they mentioned") are shown too.
    asked = words(state["message"])
    older = [t for t in turns[: max(0, len(turns) - RECENT_TURNS)] if len(asked & words(t["text"])) >= 2]
    older.sort(key=lambda t: -len(asked & words(t["text"])))
    picked = sorted(older[:RELATED_TURNS] + recent, key=lambda t: t["n"])

    shown: dict[str, dict] = {}
    lines = [
        f"Job: {state['job']['title']}",
        "",
        "Job requirements (R). The note in brackets is a rough check of whether the interview has touched on it "
        "(a keyword match while the interview is live, so confirm it against the transcript):",
    ]
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
                lines.append(f"You: {clip(item['text'], HISTORY_CHARS)}" + (f" Suggested: {asked_before}" if asked_before else ""))

    lines += ["", f"The interviewer now writes: {state['message']}"]
    return {"shown": shown, "prompt": "\n".join(lines), "attempts": 0, "problems": []}


SYSTEM_PROMPT = (
    "You are a helpful assistant for an interviewer who is running, or has just run, a job interview. You can see "
    "the job requirements (R), the candidate's CV (C), the transcript so far (T) and the earlier chat. Talk like a "
    "knowledgeable colleague, in plain natural language: answer exactly what the interviewer wrote, nothing more.\n"
    "- A greeting or small talk gets a short friendly reply. A question gets an answer.\n"
    "- Do NOT offer interview questions unless the interviewer asks for them.\n"
    "- If they ask you to write questions on a topic (for example Python or system design), write them in the reply as "
    "a numbered list, as many as they ask for (five if they give no number). If they ask for the answers too, or later "
    "ask for the answers, give the key points of a good answer for each, so they can judge the candidate's reply.\n"
    "- If they ask what has been covered or how the interview is going, list it from the requirements, the "
    "transcript and the CV. The brackets next to the requirements are only a rough keyword check, so use the "
    "transcript as the evidence and say plainly when something was not discussed.\n"
    "- If they ask whether to ask something, or how to word it, give your honest opinion and a better wording if "
    "there is one.\n"
    "- Only when they ask for questions to put to THIS candidate (about their CV, what they said, or requirements "
    "not covered yet): put up to three questions in the suggestions field instead of the reply text, each naming "
    "exactly one line it is based on by its id (C3, T12 or R2; only ids you were shown), and keep the reply short. "
    "In every other case leave suggestions empty.\n"
    "- Base everything about the candidate on what you were shown. Never invent facts about them. Do not repeat "
    "questions already asked in the transcript or already written earlier in this chat.\n"
    "- Never write questions about age, family, marriage, children, pregnancy, religion, ethnicity, nationality, "
    "health, disability, gender, sexuality or politics. If asked, decline in one short sentence without listing the "
    "topics. Do not judge the candidate's honesty or character; point to what the transcript shows instead.\n"
    "- Write plain text only: no markdown symbols such as ** or #. Keep it as short as the question allows."
)


def write_reply(state: ChatState) -> dict:
    """The AI writes the answer. On a second try it is told what was wrong."""
    prompt = state["prompt"]
    if state.get("problems"):
        prompt += "\n\nYour last answer had these problems. Fix them:\n- " + "\n- ".join(state["problems"])
    try:
        answer = ask(SYSTEM_PROMPT, prompt, ChatReply)
    except LLMUnavailable as error:
        return {"error": str(error)}
    return {"draft": answer.model_dump(), "attempts": state.get("attempts", 0) + 1}


def check_sources(state: ChatState) -> dict:
    """Plain code: every card points to a line the AI was shown, and nothing personal is asked (N20)."""
    shown = state["shown"]
    draft = state["draft"]
    reply = tidy_block(draft.get("reply"))
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

    if PERSONAL.search(reply):
        problems.append("Your reply touches a personal matter that must not be asked about in an interview. "
                        "Rewrite it without that, and do not name the topics.")

    if problems and state["attempts"] < MAX_ATTEMPTS:
        return {"problems": problems}
    if PERSONAL.search(reply):
        reply = DECLINED
    if not reply:
        reply = "Here are some questions to ask next." if kept else "I don't have anything to add on that."
    return {"reply": reply, "suggestions": kept[:MAX_SUGGESTIONS], "problems": []}


def source_of(source_id: str, line: dict) -> dict:
    """What the screen shows under a card: the line it is based on."""
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