"""HR rounds judged as HR rounds, requirements checked with documents, and the analysis fixes
(hiring rounds update). Every AI call is a fake."""

from types import SimpleNamespace

from app import claim_check, round_info
from app.agents import assessment_agent, evaluation_agent, interview_score_agent, quality_agent
from app.agents.assessment_agent import Findings
from app.agents.interview_score_agent import InterviewScores
from app.agents.quality_agent import Review
from app.requirement_checks import DOCUMENTS, checked_by_documents, interview_items
from tests import test_assessment_agent as assessment_tests
from tests import test_evaluation_agent as evaluation_tests
from tests.test_interview_quality import COVERAGE, JOB, PAIRS, TURNS


# ---------- round types ----------


def test_a_round_type_is_guessed_from_its_name():
    assert round_info.guess_type("HR interview") == "hr"
    assert round_info.guess_type("Technical interview") == "technical"
    assert round_info.guess_type("Round 2", "behavioural questions and culture fit") == "hr"
    assert round_info.guess_type("Interview") == "technical"
    assert round_info.guess_type("Thread pools") == "technical"  # "hr" inside a word does not count


def test_a_saved_type_wins_over_the_guess():
    job = SimpleNamespace(interview_rounds=[{"name": "HR interview", "focus": "", "type": "technical"}])
    assert round_info.round_of(job, 1)["type"] == "technical"


def test_hr_topics_come_from_the_focus_or_the_default_list():
    assert round_info.hr_topics("Communication, salary expectations; teamwork") == [
        "Communication", "Salary expectations", "Teamwork",
    ]
    assert round_info.hr_topics("") == round_info.DEFAULT_HR_TOPICS
    assert round_info.hr_topics("general chat") == round_info.DEFAULT_HR_TOPICS


# ---------- requirements checked with documents ----------


def test_degrees_certificates_and_written_skills_are_document_checks():
    assert checked_by_documents({"requirement": "Bachelor's degree in Computer Science", "kind": "qualification"})
    assert checked_by_documents({"requirement": "Professional written English", "kind": "skill"})
    assert checked_by_documents({"requirement": "AWS certification", "kind": "preferred"})
    assert not checked_by_documents({"requirement": "Python", "kind": "skill"})
    assert not checked_by_documents({"requirement": "Written communication", "kind": "hr_topic"})


def test_interview_items_leave_out_document_checks_even_in_old_analyses():
    coverage = [
        {"requirement": "Python", "kind": "skill", "status": "explored"},
        {"requirement": "Bachelor's degree in CS", "kind": "qualification", "status": "weak"},  # an older analysis
        {"requirement": "Diploma", "kind": "qualification", "status": DOCUMENTS},
    ]
    assert [item["requirement"] for item in interview_items(coverage)] == ["Python"]


# ---------- the answer analysis ----------


def use_fake_evaluation_ai(monkeypatch, **kwargs):
    fake = evaluation_tests.FakeAI(**kwargs)
    monkeypatch.setattr(evaluation_agent, "ask", fake)
    asked: list[str] = []
    monkeypatch.setattr(evaluation_agent, "find_references", lambda q: asked.append(q) or [evaluation_tests.REFERENCE])
    return fake, asked


def test_a_question_said_twice_in_other_words_is_scored_once(monkeypatch):
    plans = {**evaluation_tests.PLANS, 4: {"questions": ["How good are you in Japanese?", "Do you know Japanese?"], "follow_up": False}}
    use_fake_evaluation_ai(monkeypatch, plans=plans)
    pairs = evaluation_tests.run()["pairs"]
    assert [p["question"] for p in pairs if "Japanese" in p["question"]] == ["How good are you in Japanese?"]


def test_a_real_two_part_question_still_becomes_two_pairs():
    assert evaluation_agent.drop_rephrased(["What is Docker?", "When would you use Docker?"]) == [
        "What is Docker?", "When would you use Docker?",
    ]


def test_a_degree_is_marked_as_a_document_check_and_never_linked(monkeypatch):
    fake, _ = use_fake_evaluation_ai(monkeypatch)
    job = {**evaluation_tests.JOB, "requirements": evaluation_tests.JOB["requirements"] + [
        {"requirement": "Bachelor's degree in Computer Science", "kind": "qualification", "mandatory": True},
    ]}
    result = evaluation_tests.run(job=job)
    degree = result["coverage"][-1]
    assert degree["status"] == DOCUMENTS and degree["pairs"] == []
    asked = next(prompt for shape, prompt in fake.calls if shape is evaluation_agent.RequirementLinks)
    assert "Bachelor" not in asked
    assert all(4 not in p["requirements"] for p in result["pairs"])


def test_an_hr_round_is_scored_with_the_hr_rubric_and_no_reference_notes(monkeypatch):
    fake, asked = use_fake_evaluation_ai(monkeypatch)
    prompts: list[str] = []
    original = fake.__call__

    def remember(system_prompt, user_prompt, answer_shape):
        prompts.append(system_prompt)
        return original(system_prompt, user_prompt, answer_shape)

    monkeypatch.setattr(evaluation_agent, "ask", remember)
    topics = [{"requirement": t, "kind": "hr_topic", "mandatory": False} for t in round_info.DEFAULT_HR_TOPICS]
    result = evaluation_agent.get_evaluation_agent().invoke({
        "turns": evaluation_agent.build_turns(evaluation_tests.TRANSCRIPT),
        "job": {"title": "Backend Developer", "description": "", "requirements": topics},
        "round_type": "hr",
    })
    assert evaluation_agent.HR_SCORE_PROMPT in prompts and evaluation_agent.SCORE_PROMPT not in prompts
    assert asked == []  # no technical notes for an HR answer
    assert all(p["references"] == [] for p in result["pairs"])


# ---------- the interview score ----------


HR_SCORES = {"scores": [
    {"dimension": "communication", "score": 80, "reason": "Clear answers.", "turn": 4},
    {"dimension": "motivation", "score": 70, "reason": "Explained why the role.", "turn": 4},
    {"dimension": "teamwork", "score": 75, "reason": "Talks problems through.", "turn": 4},
    {"dimension": "judgement", "score": 60, "reason": "Handles a rude manager calmly.", "turn": 6},
    {"dimension": "professionalism", "score": 85, "reason": "Clear about salary.", "turn": 4},
]}


def test_an_hr_round_gets_its_own_six_parts(monkeypatch):
    monkeypatch.setattr(interview_score_agent, "ask", lambda s, u, shape: InterviewScores(**HR_SCORES))
    final = interview_score_agent.get_interview_score_agent().invoke(
        {"job": JOB, "turns": TURNS, "pairs": PAIRS, "coverage": COVERAGE, "round_type": "hr"}
    )
    assert [d["label"] for d in final["dimensions"]] == [
        "Communication", "Motivation and fit", "Teamwork", "Situational judgement", "Professionalism", "HR topic coverage",
    ]
    assert "Technical competency" not in [d["label"] for d in final["dimensions"]]
    assert "HR topics explored" in final["dimensions"][-1]["reason"]


# ---------- the quality review ----------


def test_a_what_question_is_never_labelled_yes_no(monkeypatch):
    closed = {"summary": "Fine.", "questions": [{"id": 2, "kind": "closed", "note": "-"}, {"id": 3, "kind": "closed", "note": "-"}],
              "recommendations": [{"text": "Ask follow-ups.", "turn": 0}]}
    monkeypatch.setattr(quality_agent, "ask", lambda s, u, shape: Review(**closed))
    pairs = [dict(p) for p in PAIRS]
    pairs[1]["question"] = "What do you use to deploy this project?"
    final = quality_agent.get_quality_agent().invoke(
        {"job": JOB, "turns": TURNS, "pairs": pairs, "coverage": COVERAGE, "others": []}
    )
    kinds = {q["id"]: q["kind"] for q in final["questions"]}
    assert kinds == {2: "open", 3: "closed"}  # "You know PostgreSQL, right?" stays closed


# ---------- the report ----------


def run_assessment(monkeypatch, verdicts, analysis, findings=None):
    fake = assessment_tests.FakeAI([findings or assessment_tests.GOOD])
    monkeypatch.setattr(assessment_agent, "ask", fake)
    return assessment_agent.get_assessment_agent().invoke({
        "job": assessment_tests.JOB, "verdicts": verdicts, "cv_score": assessment_tests.CV_SCORE, "analysis": analysis,
    })


DEGREE = {"requirement": "Bachelor's degree in Computer Science", "kind": "qualification", "mandatory": True,
          "verdict": "partially_met", "explanation": "BSc in CSE."}


def test_a_degree_is_never_a_gap_or_a_follow_up_unless_the_cv_does_not_show_it(monkeypatch):
    result = run_assessment(monkeypatch, assessment_tests.VERDICTS + [DEGREE], assessment_tests.ANALYSIS)
    degree = result["requirements"][-1]
    assert degree["interview"] == DOCUMENTS
    assert "Bachelor's degree in Computer Science" not in [g["requirement"] for g in result["gaps"]]

    unmet = {**DEGREE, "verdict": "unmet"}
    gaps = run_assessment(monkeypatch, assessment_tests.VERDICTS + [unmet], assessment_tests.ANALYSIS)["gaps"]
    assert ("Bachelor's degree in Computer Science", "not_in_cv") in [(g["requirement"], g["kind"]) for g in gaps]


def test_a_requirement_the_interview_never_saw_counts_as_not_explored(monkeypatch):
    extra = {"requirement": "Data preprocessing", "kind": "skill", "mandatory": True, "verdict": "met", "explanation": "-"}
    result = run_assessment(monkeypatch, assessment_tests.VERDICTS + [extra], assessment_tests.ANALYSIS)
    line = result["requirements"][-1]
    assert line["interview"] == "not_explored"
    coverage = next(c for c in result["components"] if c["key"] == "coverage")
    assert coverage["score"] == 30.0  # (100 + 50 + 0 + 0 + 0) / 5, not the 37.5 of the four it saw


def test_missing_evidence_is_not_a_weakness_and_a_partly_met_requirement_is_not_a_strength(monkeypatch):
    findings = {
        **assessment_tests.GOOD,
        "strengths": [
            {"text": "Explains Python generators clearly.", "evidence": ["Q2", "R1"]},
            {"text": "Strong PostgreSQL background.", "evidence": ["R2"]},  # the CV only partly shows it
        ],
        "weaknesses": [
            {"text": "PostgreSQL indexing answer was thin.", "evidence": ["Q3"]},
            {"text": "No interview evidence of Docker.", "evidence": ["C3"]},
        ],
    }
    report = run_assessment(monkeypatch, assessment_tests.VERDICTS, assessment_tests.ANALYSIS, findings)["findings"]
    assert [s["text"] for s in report["strengths"]] == ["Explains Python generators clearly."]
    assert [w["text"] for w in report["weaknesses"]] == ["PostgreSQL indexing answer was thin."]


def test_the_claim_check_reads_every_round():
    first = SimpleNamespace(result={"turns": [{"n": 1, "speaker": "candidate", "text": "I use Docker.", "start_ms": 0, "end_ms": 1}]})
    second = SimpleNamespace(result={"turns": [
        {"n": 1, "speaker": "interviewer", "text": "Why us?", "start_ms": 0, "end_ms": 1},
        {"n": 2, "speaker": "candidate", "text": "Good team.", "start_ms": 2, "end_ms": 3},
    ]})
    turns = claim_check.turns_of_every_round(
        [(first, SimpleNamespace(round_number=1)), (second, SimpleNamespace(round_number=2))]
    )
    assert [(t["n"], t["round"], t["text"]) for t in turns] == [
        (1, 1, "I use Docker."), (2, 2, "Why us?"), (3, 2, "Good team."),
    ]


def test_findings_shape_is_unchanged():
    assert set(Findings.model_fields) == {"summary", "strengths", "weaknesses", "follow_ups"}


def test_a_cv_screened_against_old_requirements_is_flagged():
    from app.routers.candidates import requirements_changed

    job = SimpleNamespace(required_skills=["Python"], qualifications=[], min_experience_years=0, preferred_skills=["Docker"])
    same = [SimpleNamespace(requirement="python"), SimpleNamespace(requirement="Docker")]
    old = same + [SimpleNamespace(requirement="Basic Machine Learning concepts")]
    assert requirements_changed(job, same) is False
    assert requirements_changed(job, old) is True
    assert requirements_changed(job, []) is False  # not screened yet
