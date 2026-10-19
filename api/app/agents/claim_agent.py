"""The Claim Check Agent (Module 13, stretch feature F8): CV claims checked against the interview.

It reads what the CV says (the profile the Screening Agent extracted) and what the candidate said
in the interview (the transcript turns of the answer analysis, Module 9). For each claim it says
one of four things, and keeps them clearly apart:

- supported        the candidate talked about it and gave concrete detail that fits the CV
- contradicted     something the candidate said does not fit the CV (other years, other role ...)
- unsubstantiated  it came up, but the candidate gave no real detail, or only repeated the claim
- not_discussed    nothing in the interview was about it

Every result is a prompt for a person to follow up, never an accusation, and it never changes
the candidate's score or position (F8). The steps, each one node of the LangGraph graph:

1. list_claims    plain code: numbers the CV claims (K1, K2 ...) worth checking: roles, projects,
                  certifications, total experience and the skills the job asks for.
2. find_mentions  plain code (RAG): for each claim, the candidate turns that are closest to it in
                  meaning (embeddings) or name it outright, with the question before each one.
3. judge_claims   the AI reads each claim with its turns and gives one of the four statuses, the
                  turn and a short quote, and a follow-up question.
4. check_quotes   plain code: a status other than "not discussed" must point at a turn that was
                  shown and a quote the candidate really said. If not, the AI is asked once more;
                  after that the claim is shown as "not discussed", never as a flag without proof.
"""

import logging
import math
import re
from functools import lru_cache
from typing import Literal

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app import knowledge
from app.agents.common import AgentState, has_error
from app.llm import LLMUnavailable, ask_llm
from app.settings import settings

log = logging.getLogger("talentsight.claim_agent")

MAX_CLAIMS = 12        # the most claims checked in one run (keeps it inside Groq's free limit)
TURNS_PER_CLAIM = 3    # candidate turns shown to the AI for one claim
BATCH = 6              # claims in one AI call
TURN_CHARS = 700       # the longest piece of one turn the AI is shown
MAX_JUDGE_ATTEMPTS = 2  # the AI is asked again once about claims whose proof could not be found

STATUSES = ("contradicted", "unsubstantiated", "not_discussed", "supported")  # the order on the screen
LABELS = {
    "supported": "Backed up in the interview",
    "contradicted": "Possible contradiction",
    "unsubstantiated": "Mentioned, not shown",
    "not_discussed": "Not discussed",
}
KIND_ORDER = {"role": 0, "experience": 1, "project": 2, "certification": 3, "skill": 4}


# ---------- 1. The state ----------
class ClaimState(AgentState, total=False):
    # Input (see claim_check.inputs_for)
    job: dict        # {"title", "requirements": [text, ...]}
    profile: dict    # the structured CV (screening_agent.CVProfile)
    turns: list      # the interview turns: [{"n", "speaker", "text", "start_ms", "end_ms"}]
    # Filled in step by step
    claims: list     # [{"id", "kind", "claim", "terms", "turns": [n, ...]}]
    draft: dict      # claim id -> what the AI said about it
    attempts: int
    recheck: list    # claim ids the AI is asked about again
    results: list    # the checked claims, in screen order
    summary: dict


# ---------- 2. The answer shape ----------
class ClaimJudgement(BaseModel):
    id: str = Field(description="The claim's id, for example K3")
    status: Literal["supported", "contradicted", "unsubstantiated", "not_discussed"]
    turn: int = Field(description="The number of the candidate turn the status rests on, 0 when not discussed")
    quote: str = Field(description="A short exact quote from that turn, at most 25 words; empty when not discussed")
    note: str = Field(description="One neutral sentence on what the candidate said compared with the CV")
    follow_up: str = Field(description="One question a person could ask next to settle it")


class ClaimJudgements(BaseModel):
    claims: list[ClaimJudgement]


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


def same(text: str) -> str:
    return tidy(text).lower()


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    size = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / size if size else 0.0


def names_term(text: str, term: str) -> bool:
    """True when the turn names the term as a whole word ("Go" must not match "good")."""
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(term.lower())}(?![A-Za-z0-9])", text.lower()))


def ask(system_prompt: str, user_prompt: str, answer_shape):
    """ask_llm with the assessment model, and patience for Groq's per-minute limit."""
    return ask_llm(system_prompt, user_prompt, answer_shape, model=settings.assessment_model, max_retries=6)


# ---------- 4. The steps ----------
def list_claims(state: ClaimState) -> dict:
    """The CV claims worth checking, numbered K1, K2 ... Plain code, so the same CV gives the same list."""
    profile = state.get("profile") or {}
    wanted = [same(r) for r in state["job"].get("requirements", [])]
    found: list[dict] = []

    for item in profile.get("work_history", []):
        title, company = tidy(item.get("title")), tidy(item.get("company"))
        if not (title or company):
            continue
        when = " to ".join(part for part in (tidy(item.get("start")), tidy(item.get("end"))) if part)
        claim = f"{title} at {company}" + (f" ({when})" if when else "")
        if tidy(item.get("summary")):
            claim += f": {tidy(item['summary'])}"
        found.append({"kind": "role", "claim": claim, "terms": [t for t in (company,) if len(t) > 2]})

    years = profile.get("total_experience_years") or 0
    if years:
        found.append({"kind": "experience", "claim": f"{years:g} years of work experience in total", "terms": []})

    for item in profile.get("projects", []):
        name = tidy(item.get("name"))
        if name:
            summary = tidy(item.get("summary"))
            found.append({"kind": "project", "claim": f"Project {name}" + (f": {summary}" if summary else ""), "terms": [name]})

    for name in profile.get("certifications", []):
        if tidy(name):
            found.append({"kind": "certification", "claim": f"Certification: {tidy(name)}", "terms": [tidy(name)]})

    # Skills: only the ones the job asks for, so the list stays short and relevant.
    for skill in profile.get("skills", []):
        skill = tidy(skill)
        if skill and any(names_term(r, skill) or names_term(skill, r) for r in wanted):
            found.append({"kind": "skill", "claim": f"Skill: {skill}", "terms": [skill]})

    # The same claim twice (a skill listed twice, say) is checked once.
    unique, seen = [], set()
    for claim in found:
        if same(claim["claim"]) not in seen:
            seen.add(same(claim["claim"]))
            unique.append(claim)
    unique.sort(key=lambda c: KIND_ORDER[c["kind"]])  # stable: the CV's own order inside each kind
    claims = [{"id": f"K{n}", **claim} for n, claim in enumerate(unique[:MAX_CLAIMS], start=1)]
    if not claims:
        return {"error": "The CV has no claims to check (no roles, projects, certifications or job skills were found in it)."}
    return {"claims": claims}


def find_mentions(state: ClaimState) -> dict:
    """For each claim, the candidate turns closest to it in meaning, plus any turn that names it."""
    answers = [t for t in state["turns"] if t["speaker"] == "candidate" and tidy(t["text"])]
    if not answers:
        return {"error": "The candidate says nothing in this interview's transcript, so no claim can be checked."}

    turn_vectors = knowledge.embed_texts([clip(t["text"], TURN_CHARS) for t in answers])
    claims = []
    for claim in state["claims"]:
        claim_vector = knowledge.embed_question(claim["claim"])
        ranked = sorted(zip(answers, turn_vectors), key=lambda pair: -cosine(claim_vector, pair[1]))
        picked = [turn["n"] for turn, _ in ranked[:TURNS_PER_CLAIM]]
        # A turn that names the company, project or skill is always shown, even if it ranks lower.
        for turn in answers:
            if turn["n"] not in picked and any(names_term(turn["text"], term) for term in claim["terms"]):
                picked.append(turn["n"])
        claims.append({**claim, "turns": sorted(picked[: TURNS_PER_CLAIM + 2])})
    return {"claims": claims}


JUDGE_PROMPT = (
    "You compare claims from a candidate's CV with what the candidate said in a job interview. "
    "For each claim you see the interview turns most likely to be about it, each with the question asked "
    "before it. Give each claim exactly one status:\n"
    "- supported: the candidate gave concrete detail that fits the claim (what they built, how, with what).\n"
    "- contradicted: something the candidate said does not fit the claim (different years, role, employer, "
    "or they say they did not do it). Only use this when the words clearly conflict.\n"
    "- unsubstantiated: the topic came up, but the candidate gave no real detail or only repeated the claim.\n"
    "- not_discussed: none of the turns shown is about this claim.\n"
    "turn and quote must come from the turns shown for that claim; use turn 0 and an empty quote for "
    "not_discussed. note: one neutral sentence. follow_up: one fair question a person could ask to settle it. "
    "These are prompts for a person to check, never accusations: do not judge honesty or character. "
    "Never mention or guess age, gender, ethnicity, nationality, religion, marital status or health."
)


def prompt_for(claims: list[dict], by_n: dict[int, dict], job_title: str) -> str:
    blocks = []
    for claim in claims:
        lines = []
        for n in claim["turns"]:
            asked = next((by_n[m] for m in range(n - 1, 0, -1) if m in by_n and by_n[m]["speaker"] == "interviewer"), None)
            if asked:
                lines.append(f"  Question before it: {clip(asked['text'], 200)}")
            lines.append(f"  [turn {n}, {elapsed(by_n[n]['start_ms'])}] Candidate: {clip(by_n[n]['text'], TURN_CHARS)}")
        blocks.append(f"[{claim['id']}] CV claim: {claim['claim']}\n" + "\n".join(lines))
    return f"Job: {job_title}\n\n" + "\n\n".join(blocks)


def judge_claims(state: ClaimState) -> dict:
    """The AI gives each claim a status, the turn and quote it rests on, and a follow-up question."""
    by_n = {t["n"]: t for t in state["turns"]}
    wanted = set(state.get("recheck") or [c["id"] for c in state["claims"]])
    todo = [c for c in state["claims"] if c["id"] in wanted]
    draft = dict(state.get("draft") or {})
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        try:
            answer = ask(JUDGE_PROMPT, prompt_for(batch, by_n, state["job"]["title"]), ClaimJudgements)
        except LLMUnavailable as error:
            return {"error": str(error)}
        ids = {c["id"] for c in batch}
        for item in answer.claims:
            code = re.sub(r"[^A-Za-z0-9]", "", item.id).upper()
            if code in ids:
                draft[code] = item.model_dump()
    return {"draft": draft, "attempts": state.get("attempts", 0) + 1, "recheck": []}


def fallback_question(claim: dict, status: str) -> str:
    if status == "supported":
        return ""
    if status == "not_discussed":
        return f"Ask the candidate to walk you through this: {claim['claim']}."
    return f"Ask for a concrete example that shows this: {claim['claim']}."


def check_quotes(state: ClaimState) -> dict:
    """Every status except "not discussed" must rest on a turn that was shown and words really said."""
    by_n = {t["n"]: t for t in state["turns"]}
    results, recheck = [], []
    for claim in state["claims"]:
        said = state["draft"].get(claim["id"])
        status = said["status"] if said else "not_discussed"
        evidence = None
        if status != "not_discussed":
            quote = tidy(said.get("quote")).strip('"')
            holding = [n for n in claim["turns"] if quote and quote.lower() in by_n[n]["text"].lower()]
            if holding:
                turn = said["turn"] if said["turn"] in holding else holding[0]
                evidence = {"turn": turn, "start_ms": by_n[turn]["start_ms"], "at": elapsed(by_n[turn]["start_ms"]), "quote": quote}
            elif said["turn"] in claim["turns"]:
                # The right turn, but not the exact words: show the candidate's own words instead.
                turn = said["turn"]
                evidence = {"turn": turn, "start_ms": by_n[turn]["start_ms"], "at": elapsed(by_n[turn]["start_ms"]), "quote": clip(by_n[turn]["text"], 200)}
        if status != "not_discussed" and evidence is None:
            if state.get("attempts", 0) < MAX_JUDGE_ATTEMPTS:
                recheck.append(claim["id"])
                continue
            status = "not_discussed"  # a flag without proof is never shown
            said = {**(said or {}), "note": "The interview turns shown did not clearly cover this claim."}
        note = tidy((said or {}).get("note")) or "Nothing in the interview was about this claim."
        results.append({
            "id": claim["id"],
            "kind": claim["kind"],
            "claim": claim["claim"],
            "status": status,
            "label": LABELS[status],
            "note": note,
            "evidence": evidence,
            "follow_up": "" if status == "supported" else tidy((said or {}).get("follow_up")) or fallback_question(claim, status),
            "turns": claim["turns"],
        })
    if recheck:
        return {"recheck": recheck}
    results.sort(key=lambda r: STATUSES.index(r["status"]))  # flags first, then the backed-up claims
    summary = {status: sum(1 for r in results if r["status"] == status) for status in STATUSES}
    summary["claims"] = len(results)
    summary["follow_ups"] = sum(1 for r in results if r["follow_up"])
    return {"results": results, "summary": summary, "recheck": []}


def failed(state: ClaimState) -> dict:
    log.warning("claim check agent stopped with an error", extra={"event": "claim_check_failed"})
    return {}


def next_or_failed(next_step: str):
    def route(state: ClaimState) -> str:
        return "failed" if has_error(state) else next_step

    return route


def after_checking(state: ClaimState) -> str:
    return "judge_claims" if state.get("recheck") else END


# ---------- 5. The graph ----------
@lru_cache
def get_claim_agent():
    graph = StateGraph(ClaimState)
    graph.add_node("list_claims", list_claims)
    graph.add_node("find_mentions", find_mentions)
    graph.add_node("judge_claims", judge_claims)
    graph.add_node("check_quotes", check_quotes)
    graph.add_node("failed", failed)

    graph.add_edge(START, "list_claims")
    graph.add_conditional_edges("list_claims", next_or_failed("find_mentions"), ["find_mentions", "failed"])
    graph.add_conditional_edges("find_mentions", next_or_failed("judge_claims"), ["judge_claims", "failed"])
    graph.add_conditional_edges("judge_claims", next_or_failed("check_quotes"), ["check_quotes", "failed"])
    # check_quotes can send unproven claims back to judge_claims once: a loop in the graph.
    graph.add_conditional_edges("check_quotes", after_checking, ["judge_claims", END])
    graph.add_edge("failed", END)
    return graph.compile()