"""Litmus Agent (F11): runs the real screening steps on the profile and its controlled copies.

The steps:
    prepare    -> make the copies (plain code, app/litmus.py)
    reference  -> score the unchanged profile
    repeat     -> score the unchanged profile again, to measure the scorer's own wobble
    variant    -> score the next copy; loops until every applicable copy is done
    judge      -> compare everything (plain code) and decide the outcome
Any AI failure goes to "failed" and the check is shown as failed, never half-done.

One run uses the Screening Agent's own steps (match_requirements, mandatory_gate, score_candidate),
so Litmus tests exactly the scorer the screening uses. The CV is not read again: the copies are
made from the stored profile, so only one thing changes at a time.
"""

import logging
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.agents.common import AgentState, has_error
from app.agents.screening_agent import mandatory_gate, match_requirements, score_candidate
from app.litmus import judge as judge_runs
from app.litmus import make_variants
from app.scoring import DIMENSIONS, aggregate

log = logging.getLogger("talentsight.litmus_agent")


# ---------- 1. The state ----------
class LitmusState(AgentState, total=False):
    job: dict          # job_for_agent(job): title, description, requirements
    weights: dict      # the job's weights, for the overall score
    profile: dict      # the stored, unchanged profile
    variants: list[dict]
    position: int      # which copy runs next
    runs: dict         # "reference", "repeat" and one entry per copy key
    report: dict


# ---------- 2. One run of the real screening steps ----------
def screen_once(job: dict, weights: dict, profile: dict) -> dict:
    """The requirement check, the must-have gate and the four scores for one profile."""
    state = {"job": job, "profile": profile}
    matched = match_requirements(state)
    if matched.get("error"):
        return {"error": matched["error"]}
    state.update(matched)
    gate = mandatory_gate(state)
    run = {
        "verdicts": [
            {"requirement": v["requirement"], "mandatory": v["mandatory"], "verdict": v["verdict"]}
            for v in matched["verdicts"]
        ],
        "excluded": gate["excluded"],
        "scores": {},
        "overall": None,
    }
    if gate["excluded"]:
        return run  # an excluded candidate is never scored, exactly as in the screening
    scored = score_candidate(state)
    if scored.get("error"):
        return {"error": scored["error"]}
    numbers = {d: scored["scores"][d]["score"] for d in DIMENSIONS}
    run["scores"] = numbers
    run["overall"] = aggregate(numbers, weights)
    return run


def run_into(state: LitmusState, key: str, profile: dict) -> dict:
    run = screen_once(state["job"], state["weights"], profile)
    if run.get("error"):
        return {"error": run["error"]}
    return {"runs": {**state.get("runs", {}), key: run}}


# ---------- 3. The steps ----------
def prepare(state: LitmusState) -> dict:
    return {"variants": make_variants(state["profile"]), "position": 0, "runs": {}}


def reference(state: LitmusState) -> dict:
    return run_into(state, "reference", state["profile"])


def repeat(state: LitmusState) -> dict:
    return run_into(state, "repeat", state["profile"])


def next_applicable(state: LitmusState) -> int | None:
    """The position of the next copy that changes something, or None when all are done."""
    variants = state["variants"]
    for position in range(state.get("position", 0), len(variants)):
        if variants[position]["applicable"]:
            return position
    return None


def variant(state: LitmusState) -> dict:
    position = next_applicable(state)
    chosen = state["variants"][position]
    update = run_into(state, chosen["key"], chosen["profile"])
    return {**update, "position": position + 1}


def judge(state: LitmusState) -> dict:
    return {"report": judge_runs(state["variants"], state["runs"])}


def failed(state: LitmusState) -> dict:
    log.warning("litmus agent stopped with an error", extra={"event": "litmus_failed"})
    return {}


# ---------- 4. The routes between the steps ----------
def after_run(state: LitmusState) -> str:
    if has_error(state):
        return "failed"
    return "variant" if next_applicable(state) is not None else "judge"


def after_reference(state: LitmusState) -> str:
    return "failed" if has_error(state) else "repeat"


# ---------- 5. The graph ----------
@lru_cache
def get_litmus_agent():
    graph = StateGraph(LitmusState)
    graph.add_node("prepare", prepare)
    graph.add_node("reference", reference)
    graph.add_node("repeat", repeat)
    graph.add_node("variant", variant)
    graph.add_node("judge", judge)
    graph.add_node("failed", failed)

    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "reference")
    graph.add_conditional_edges("reference", after_reference, ["repeat", "failed"])
    graph.add_conditional_edges("repeat", after_run, ["variant", "judge", "failed"])
    graph.add_conditional_edges("variant", after_run, ["variant", "judge", "failed"])
    graph.add_edge("judge", END)
    graph.add_edge("failed", END)
    return graph.compile()
