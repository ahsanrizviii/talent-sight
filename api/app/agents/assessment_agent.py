"""The Assessment Agent (Module 10): one consolidated, evidence-backed report per candidate.

It merges the three earlier results (F6): the CV screening (requirement verdicts, Module 5), the
CV score (Module 6) and the interview answer analysis (Module 9). The steps, each one node of the
LangGraph graph:

1. gather_evidence   plain code: numbers every fact the report may rest on. R = a requirement as
                     checked in the CV, S = a CV score dimension, Q = a scored interview answer,
                     C = a requirement as explored in the interview.
2. find_gaps         plain code: requirements without solid evidence, or backed by the CV alone.
3. compute_position  plain code: the component scores, their weighted total and the suitability
                     position. The AI never decides the position, so the same inputs always give
                     the same position.
4. write_findings    the AI writes the summary, strengths, weaknesses and follow-ups, and every
                     item names the evidence it rests on.
5. check_citations   plain code: drops evidence ids that do not exist and any item left without
                     one, so every conclusion can be traced to the CV or a transcript line. If
                     nothing usable is left, the AI is asked once more.
"""

import logging
import math
import re
from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agents.common import AgentState, has_error
from app.llm import LLMUnavailable, ask_llm
from app.requirement_checks import DOCUMENTS, checked_by_documents
from app.settings import settings

log = logging.getLogger("talentsight.assessment_agent")

# The parts of the overall position and how much each one counts (percent).
COMPONENTS = [
    # key, label, where it comes from, weight
    ("cv_score", "CV score from the screening", "cv", 30),
    ("requirements", "Requirements met in the CV", "cv", 15),
    ("answers", "Quality of the interview answers", "interview", 40),
    ("coverage", "Requirements explored in the interview", "interview", 15),
]
STRONG_FROM = 75    # weighted total from which the candidate is a strong fit
POSSIBLE_FROM = 55  # weighted total from which the candidate is a possible fit
POSITIONS = {"strong_fit": "Strong fit", "possible_fit": "Possible fit", "weak_fit": "Weak fit"}

VERDICT_POINTS = {"met": 100, "partially_met": 50, "unmet": 0}
COVERAGE_POINTS = {"explored": 100, "weak": 50, "not_explored": 0}
VERDICT_WORDS = {"met": "met", "partially_met": "partly met", "unmet": "not met"}

MAX_ITEMS = 5               # most strengths, weaknesses or follow-ups kept
MAX_FINDING_ATTEMPTS = 2    # the AI is asked again once if none of its findings can be traced
EVIDENCE_CHARS = 300        # the longest piece of one evidence item the AI is shown
# A weakness that only says some evidence is missing: that is a gap, listed (and followed up) already.
ONLY_MISSING = re.compile(
    r"\bno (solid |clear )?(interview )?evidence\b|\bnot (discussed|explored|covered|asked|shown in the interview)\b"
    r"|\bnever (asked|discussed|explored)\b|\brests on the cv alone\b",
    re.IGNORECASE,
)


# ---------- 1. The state ----------
class AssessmentState(AgentState, total=False):
    # Input (see assessment.inputs_for)
    job: dict          # {"title"}
    verdicts: list     # the CV requirement verdicts: [{"requirement", "kind", "mandatory", "verdict", "explanation"}]
    cv_score: dict     # {"overall", "dimensions": [{"dimension", "label", "score", "weight", "justification"}]}
    analysis: dict     # the interview answer analysis (Module 9): {"pairs", "coverage", "summary"}
    # Filled in step by step
    requirements: list  # one line per requirement: what the CV and the interview say about it
    evidence: list      # [{"id", "source", "label", "text", "at"}]
    gaps: list
    components: list
    position: dict
    draft: dict         # the AI's findings before they are checked
    attempts: int
    retry: bool
    findings: dict      # {"summary", "strengths", "weaknesses", "follow_ups"}, every item with evidence ids


# ---------- 2. The answer shape ----------
class Finding(BaseModel):
    text: str = Field(description="One clear sentence (the summary may have two or three)")
    evidence: list[str] = Field(description="The ids of the evidence it rests on, for example Q2 or R1")


class Findings(BaseModel):
    summary: Finding
    strengths: list[Finding]
    weaknesses: list[Finding]
    follow_ups: list[Finding] = Field(description="Areas a person should verify next")


# ---------- 3. Small helpers ----------
def half_up(value: float) -> float:
    """One decimal, rounded half up (77.75 -> 77.8), like the CV score (Module 6)."""
    return math.floor(round(value * 10, 6) + 0.5) / 10  # round(..., 6) first: 61.55 * 10 is 615.4999... in floats


def elapsed(ms: int) -> str:
    """75 000 ms -> "01:15", the same clock the transcript shows."""
    seconds = max(0, ms // 1000)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def clip(text: str, limit: int = EVIDENCE_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def same(text: str) -> str:
    """Requirement texts are matched without case and extra spaces."""
    return " ".join(text.lower().split())


def ask(system_prompt: str, user_prompt: str, answer_shape):
    """ask_llm with the assessment model, and patience for Groq's per-minute limit."""
    return ask_llm(system_prompt, user_prompt, answer_shape, model=settings.assessment_model, max_retries=6)


# ---------- 4. The steps ----------
def gather_evidence(state: AssessmentState) -> dict:
    """Numbers every fact the report may cite. Plain code, so the ids are always the same."""
    analysis = state["analysis"]

    # One line per requirement: the CV verdict and the interview coverage side by side.
    requirements: list[dict] = []
    by_text: dict[str, dict] = {}
    for verdict in state["verdicts"]:
        line = {
            "n": len(requirements) + 1,
            "requirement": verdict["requirement"],
            "kind": verdict["kind"],
            "mandatory": verdict["mandatory"],
            "cv": verdict["verdict"],
            "cv_note": verdict.get("explanation", ""),
            "interview": None,
            "best_score": None,
            "pairs": [],
        }
        requirements.append(line)
        by_text[same(line["requirement"])] = line
    for covered in analysis.get("coverage", []):
        line = by_text.get(same(covered["requirement"]))
        if line is None:  # asked about in the interview, but not part of the CV check
            line = {
                "n": len(requirements) + 1,
                "requirement": covered["requirement"],
                "kind": covered.get("kind", ""),
                "mandatory": covered.get("mandatory", False),
                "cv": None,
                "cv_note": "",
            }
            requirements.append(line)
            by_text[same(line["requirement"])] = line
        line.update(interview=covered["status"], best_score=covered.get("best_score"), pairs=list(covered.get("pairs", [])))

    # A technical interview took place, so a requirement it never touched counts as not explored (it is
    # not left out, which would make the coverage look better than it was). Degrees, certificates and
    # written skills are checked with documents at onboarding, whatever an older analysis said.
    interviewed = analysis.get("technical_rounds", 1 if analysis.get("coverage") else 0)
    for line in requirements:
        if checked_by_documents(line):
            line.update(interview=DOCUMENTS, best_score=None, pairs=[])
        elif line["interview"] is None and line["cv"] and interviewed:
            line["interview"] = "not_explored"

    evidence: list[dict] = []
    for line in requirements:
        if line["cv"]:
            text = f"CV check: {VERDICT_WORDS.get(line['cv'], line['cv'])}. {line['cv_note']}".strip()
            evidence.append({"id": f"R{line['n']}", "source": "cv", "label": line["requirement"], "text": text, "at": None})
    for number, dimension in enumerate(state["cv_score"]["dimensions"], start=1):
        evidence.append({
            "id": f"S{number}",
            "source": "cv",
            "label": f"CV score, {dimension['label']}: {dimension['score']:g}/100",
            "text": dimension.get("justification", ""),
            "at": None,
        })
    for pair in analysis.get("pairs", []):
        if pair.get("kind") != "job_related" or pair.get("overall") is None:
            continue  # small talk is never evidence (Q&A 16)
        found = pair.get("evidence")
        quote = f' "{found["quote"]}"' if found else ""
        evidence.append({
            "id": f"Q{pair['id']}",
            "source": "interview",
            "label": pair["question"],
            "text": f"Answer scored {pair['overall']}/100.{quote}",
            "at": elapsed(found["start_ms"] if found else pair.get("start_ms", 0)),
        })
    for line in requirements:
        if not line["interview"] or line["interview"] == DOCUMENTS:
            continue
        answers = ", ".join(f"Q{p}" for p in line["pairs"])
        text = {
            "explored": f"Explored in the interview: best answer {line['best_score']}/100 ({answers}).",
            "weak": f"Asked about, but the best answer scored only {line['best_score']}/100 ({answers}).",
            "not_explored": "Never asked about in the interview.",
        }[line["interview"]]
        evidence.append({"id": f"C{line['n']}", "source": "interview", "label": line["requirement"], "text": text, "at": None})
    return {"requirements": requirements, "evidence": evidence}


def find_gaps(state: AssessmentState) -> dict:
    """Requirements the report cannot vouch for. Plain code: the same inputs give the same gaps."""
    gaps = []
    for line in state["requirements"]:
        ids = [f"R{line['n']}"] if line["cv"] else []
        ids += [f"C{line['n']}"] if line["interview"] else []
        name = line["requirement"]
        if line["interview"] == DOCUMENTS:
            # Checked with documents at onboarding: only a CV that does not show it at all is a gap.
            if line["cv"] == "unmet":
                gaps.append({
                    "kind": "not_in_cv",
                    "requirement": name,
                    "mandatory": line["mandatory"],
                    "text": f"The CV does not show {name}; it is checked with documents at onboarding.",
                    "evidence": ids,
                })
            continue
        if line["interview"] != "explored" and line["cv"] != "met":
            kind = "no_evidence"
            text = f"No solid evidence for {name}: the CV check says {VERDICT_WORDS.get(line['cv'], 'nothing')}"
            text += " and the interview did not show it." if line["interview"] else " and it is not in the interview analysis."
        elif line["cv"] == "met" and line["interview"] in (None, "not_explored"):
            kind = "cv_only"
            text = f"{name} rests on the CV alone: it was not discussed in the interview."
        elif line["cv"] == "met" and line["interview"] == "weak":
            kind = "weak_in_interview"
            text = f"The CV shows {name}, but the interview answers about it were weak (best {line['best_score']}/100)."
            ids += [f"Q{p}" for p in line["pairs"]]
        else:
            continue
        gaps.append({"kind": kind, "requirement": name, "mandatory": line["mandatory"], "text": text, "evidence": ids})
    gaps.sort(key=lambda gap: not gap["mandatory"])  # must-have requirements first
    return {"gaps": gaps}


def compute_position(state: AssessmentState) -> dict:
    """The component scores, their weighted total and the position. Plain code, no AI."""
    requirements = state["requirements"]
    ids = {item["id"] for item in state["evidence"]}
    cv_lines = [line for line in requirements if line["cv"] in VERDICT_POINTS]
    talked = [line for line in requirements if line["interview"] in COVERAGE_POINTS]
    values = {
        "cv_score": state["cv_score"].get("overall"),
        "requirements": sum(VERDICT_POINTS[l["cv"]] for l in cv_lines) / len(cv_lines) if cv_lines else None,
        "answers": state["analysis"].get("summary", {}).get("average"),
        "coverage": sum(COVERAGE_POINTS[l["interview"]] for l in talked) / len(talked) if talked else None,
    }
    sources = {
        "cv_score": sorted((i for i in ids if i.startswith("S")), key=lambda i: int(i[1:])),
        "requirements": [f"R{l['n']}" for l in cv_lines],
        "answers": sorted((i for i in ids if i.startswith("Q")), key=lambda i: int(i[1:])),
        "coverage": [f"C{l['n']}" for l in talked],
    }

    # A part with nothing to measure is left out, and the others share its weight.
    present = [(key, label, source, weight) for key, label, source, weight in COMPONENTS if values[key] is not None]
    total_weight = sum(weight for *_, weight in present)
    components = []
    for key, label, source, weight in present:
        score = half_up(values[key])
        components.append({
            "key": key,
            "label": label,
            "source": source,
            "score": score,
            "weight": weight,
            "contribution": half_up(score * weight / total_weight),
            "evidence": sources[key],
        })
    overall = half_up(sum(values[key] * weight for key, _, _, weight in present) / total_weight) if present else 0.0

    code = "strong_fit" if overall >= STRONG_FROM else "possible_fit" if overall >= POSSIBLE_FROM else "weak_fit"
    reasons = [
        f"Weighted total {overall:g} out of 100 from {len(components)} parts.",
        f"A strong fit starts at {STRONG_FROM}, a possible fit at {POSSIBLE_FROM}.",
    ]
    capped_by = []
    # A must-have requirement with no solid evidence anywhere keeps the candidate from "strong fit".
    for gap in state["gaps"]:
        if gap["mandatory"] and gap["kind"] in ("no_evidence", "not_in_cv") and code == "strong_fit":
            code = "possible_fit"
            capped_by += gap["evidence"]
            reasons.append(f"Lowered to a possible fit: no solid evidence for the must-have {gap['requirement']}.")
    position = {"code": code, "label": POSITIONS[code], "overall": overall, "reasons": reasons, "evidence": capped_by}
    return {"components": components, "position": position}


FINDINGS_PROMPT = (
    "You write the findings of a hiring assessment from numbered evidence about one candidate. "
    "Use ONLY the evidence given. Every item must list the ids of the evidence it rests on, for example "
    '["Q2", "R1"]. summary: two or three sentences on the overall picture. strengths: up to 4 clear strengths. '
    "weaknesses: up to 4 clear weaknesses or risks that the evidence SHOWS (a low answer score, a weak answer, "
    "a requirement the CV does not meet); a piece of evidence that is only missing is not a weakness, it is a gap. "
    "Never cite a requirement the CV check marks partly met or not met (R) as a strength. "
    "follow_ups: up to 4 concrete areas a person should verify next, for example a question for the next round; "
    "start with the evidence gaps. Degrees, certificates and written skills are checked with documents at "
    "onboarding: never make them a follow-up. Questions labelled with an HR round are HR answers (communication, "
    "motivation, teamwork): use them for soft-skill findings, never as evidence of technical skill. "
    "Write short, neutral sentences about job-related skills and experience only. Never mention or guess age, "
    "gender, ethnicity, nationality, religion, marital status or health. The position is decided already; "
    "do not change it."
)


def write_findings(state: AssessmentState) -> dict:
    """The AI writes the summary, strengths, weaknesses and follow-ups, citing evidence ids."""
    position = state["position"]
    gaps = "\n".join(f"- {gap['text']} [{', '.join(gap['evidence'])}]" for gap in state["gaps"]) or "- none"
    evidence = "\n".join(
        f"[{item['id']}] ({'CV' if item['source'] == 'cv' else 'Interview'}"
        + (f", {item['at']}" if item["at"] else "")
        + f") {clip(item['label'], 160)}: {clip(item['text'])}"
        for item in state["evidence"]
    )
    prompt = (
        f"Job: {state['job']['title']}\n"
        f"Position (decided by code): {position['label']}, weighted total {position['overall']:g}/100.\n\n"
        f"Evidence gaps found by code:\n{gaps}\n\nEvidence:\n{evidence}"
    )
    try:
        answer = ask(FINDINGS_PROMPT, prompt, Findings)
    except LLMUnavailable as error:
        return {"error": str(error)}
    return {"draft": answer.model_dump(), "attempts": state.get("attempts", 0) + 1, "retry": False}


def keep_traceable(items: list[dict], known: set[str]) -> list[dict]:
    """Only real evidence ids, each once; an item left without one is dropped."""
    kept = []
    for item in items:
        ids: list[str] = []
        for raw in item.get("evidence", []):
            code = re.sub(r"[^A-Za-z0-9]", "", str(raw)).upper()
            if code in known and code not in ids:
                ids.append(code)
        text = " ".join(str(item.get("text", "")).split())
        if ids and text:
            kept.append({"text": text, "evidence": ids})
    return kept[:MAX_ITEMS]


def check_citations(state: AssessmentState) -> dict:
    """Every conclusion must point at the CV or a transcript line (F6, traceability)."""
    known = {item["id"] for item in state["evidence"]}
    draft = state["draft"]
    findings = {part: keep_traceable(draft.get(part, []), known) for part in ("strengths", "weaknesses", "follow_ups")}
    # Plain code keeps the report from contradicting itself or repeating its gaps.
    not_met = {f"R{line['n']}" for line in state["requirements"] if line["cv"] in ("partially_met", "unmet")}
    strengths = []
    for item in findings["strengths"]:
        ids = [code for code in item["evidence"] if code not in not_met]
        if ids:
            strengths.append({**item, "evidence": ids})
    findings["strengths"] = strengths
    findings["weaknesses"] = [item for item in findings["weaknesses"] if not ONLY_MISSING.search(item["text"])]
    documents = {f"R{line['n']}" for line in state["requirements"] if line["interview"] == DOCUMENTS}
    findings["follow_ups"] = [item for item in findings["follow_ups"] if not set(item["evidence"]) <= documents]

    if not findings["strengths"] and not findings["weaknesses"]:
        if state.get("attempts", 0) < MAX_FINDING_ATTEMPTS:
            return {"retry": True}
        return {"error": "The AI's findings could not be traced to the CV or the interview. Please try again."}

    summary = keep_traceable([draft.get("summary", {})], known)
    if summary:
        findings["summary"] = summary[0]
    else:  # a summary that cites nothing is replaced by one made from the numbers
        position = state["position"]
        findings["summary"] = {
            "text": f"{position['label']}: weighted total {position['overall']:g} out of 100.",
            "evidence": [component["evidence"][0] for component in state["components"] if component["evidence"]],
        }
    return {"findings": findings, "retry": False}


def failed(state: AssessmentState) -> dict:
    log.warning("assessment agent stopped with an error", extra={"event": "assessment_failed"})
    return {}


def after_writing(state: AssessmentState) -> str:
    return "failed" if has_error(state) else "check_citations"


def after_checking(state: AssessmentState) -> str:
    if has_error(state):
        return "failed"
    return "write_findings" if state.get("retry") else END


def report_of(state: AssessmentState) -> dict:
    """The parts of the finished state that make up the report."""
    findings = state["findings"]
    return {
        "position": state["position"],
        "components": state["components"],
        "requirements": state["requirements"],
        "gaps": state["gaps"],
        "summary": findings["summary"],
        "strengths": findings["strengths"],
        "weaknesses": findings["weaknesses"],
        "follow_ups": findings["follow_ups"],
        "evidence": state["evidence"],
    }


# ---------- 5. The graph ----------
@lru_cache
def get_assessment_agent():
    graph = StateGraph(AssessmentState)
    graph.add_node("gather_evidence", gather_evidence)
    graph.add_node("find_gaps", find_gaps)
    graph.add_node("compute_position", compute_position)
    graph.add_node("write_findings", write_findings)
    graph.add_node("check_citations", check_citations)
    graph.add_node("failed", failed)

    graph.add_edge(START, "gather_evidence")
    graph.add_edge("gather_evidence", "find_gaps")
    graph.add_edge("find_gaps", "compute_position")
    graph.add_edge("compute_position", "write_findings")
    graph.add_conditional_edges("write_findings", after_writing, ["check_citations", "failed"])
    # check_citations can send the work back to write_findings once: a loop in the graph.
    graph.add_conditional_edges("check_citations", after_checking, ["write_findings", "failed", END])
    graph.add_edge("failed", END)
    return graph.compile()