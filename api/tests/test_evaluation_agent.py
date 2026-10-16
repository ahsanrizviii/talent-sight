"""Tests for the Evaluation Agent (Module 9). The AI is replaced by a fake, so no real model is called."""

import pytest

from app.agents import evaluation_agent as agent
from app.agents.evaluation_agent import AnswerScores, PairKind, PairKinds, RequirementLinks, Segmentation
from app.llm import LLMUnavailable


def line(speaker: str, text: str, start_s: int) -> dict:
    return {"speaker": speaker, "text": text, "start_ms": start_s * 1000, "end_ms": start_s * 1000 + 900}


TRANSCRIPT = [
    line("interviewer", "Hi Maya, can you hear me?", 0),
    line("candidate", "Yes, loud and clear.", 3),
    line("interviewer", "What is a Python generator,", 10),
    line("interviewer", "and when would you use one?", 12),
    line("candidate", "A generator yields values one at a time.", 15),
    line("candidate", "I use them for large files.", 19),
    line("interviewer", "Can you give an example?", 25),
    line("candidate", "Reading a 5 GB log line by line.", 28),
    line("interviewer", "How do you index a PostgreSQL table?", 40),
    line("candidate", "With CREATE INDEX, usually a B-tree.", 44),
]

# What the fake AI says about the four exchanges above.
PLANS = {
    1: {"questions": [], "follow_up": False},  # a greeting: nothing asked
    2: {"questions": ["What is a Python generator?", "When would you use a generator?"], "follow_up": False},
    3: {"questions": ["Can you give an example?"], "follow_up": True},
    4: {"questions": ["How do you index a PostgreSQL table?"], "follow_up": False},
}


JOB = {
    "title": "Backend Developer",
    "description": "Build Python services.",
    "requirements": [
        {"requirement": "Python", "kind": "skill", "mandatory": True},
        {"requirement": "PostgreSQL", "kind": "skill", "mandatory": True},
        {"requirement": "Kubernetes", "kind": "preferred", "mandatory": False},
    ],
}

# Which requirements the fake AI links to each pair (pair 4 also gets a number that does not exist).
LINKS = {2: [1], 3: [1, 1], 4: [2, 9]}


def scores(value: int, turn: int = 4, quote: str = "yields values one at a time") -> dict:
    dimension = {"score": value, "justification": "Named the key idea."}
    return {d: dict(dimension) for d in agent.DIMENSIONS} | {"evidence_turn": turn, "quote": quote}


class FakeAI:
    """Answers like the model would, and remembers every question it was asked."""

    def __init__(self, plans=None, kinds=None, broken: set[type] = frozenset(), answers=None):
        self.plans = PLANS if plans is None else plans
        self.kinds = kinds or {1: "small_talk"}
        self.broken = broken
        self.answers = list(answers or [])  # AnswerScores to give, one per scoring question
        self.calls: list[tuple[type, str]] = []

    def __call__(self, system_prompt: str, user_prompt: str, answer_shape):
        self.calls.append((answer_shape, user_prompt))
        if answer_shape in self.broken:
            raise LLMUnavailable("The AI service is not available right now. Please try again.")
        if answer_shape is Segmentation:
            shown = [int(part.split("\n")[0].split()[1]) for part in user_prompt.split("\n\n")]
            return Segmentation(exchanges=[{"number": n, **self.plans[n]} for n in shown if n in self.plans])
        if answer_shape is PairKinds:
            shown = [int(part.split(".")[0]) for part in user_prompt.split("\n\n")]
            return PairKinds(pairs=[PairKind(id=i, kind=self.kinds.get(i, "job_related")) for i in shown])
        if answer_shape is RequirementLinks:
            shown = [int(part.split(".")[0]) for part in user_prompt.split("Pairs:\n")[1].split("\n\n")]
            return RequirementLinks(pairs=[{"id": i, "requirements": LINKS.get(i, [])} for i in shown])
        if answer_shape is AnswerScores:
            return AnswerScores(**(self.answers.pop(0) if self.answers else scores(80)))
        raise AssertionError(f"unexpected question for {answer_shape.__name__}")


REFERENCE = {"skill": "Python", "heading": "Generators", "url": "https://docs.python.org/3/", "text": "Python — Generators: ..."}


@pytest.fixture(autouse=True)
def fake_references(monkeypatch):
    """The skills documents are searched in the database; here a fixed note stands in for them."""
    asked: list[str] = []
    monkeypatch.setattr(agent, "find_references", lambda question: asked.append(question) or [REFERENCE])
    return asked

@pytest.fixture
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(agent, "ask", fake)
    return fake


def run(turns=None, job=None) -> dict:
    return agent.get_evaluation_agent().invoke({"turns": turns or agent.build_turns(TRANSCRIPT), "job": job or JOB})


# ---------- Plain code: turns and exchanges ----------


def test_lines_in_a_row_from_one_speaker_become_one_turn():
    turns = agent.build_turns(TRANSCRIPT)
    assert [(t["n"], t["speaker"]) for t in turns] == [
        (1, "interviewer"), (2, "candidate"), (3, "interviewer"), (4, "candidate"),
        (5, "interviewer"), (6, "candidate"), (7, "interviewer"), (8, "candidate"),
    ]
    assert turns[2]["text"] == "What is a Python generator, and when would you use one?"
    assert (turns[3]["start_ms"], turns[3]["end_ms"]) == (15_000, 19_900)  # from the first line to the last


def test_empty_lines_are_skipped():
    turns = agent.build_turns([line("candidate", "   ", 0), line("interviewer", "Hello", 1)])
    assert [(t["n"], t["text"]) for t in turns] == [(1, "Hello")]


def test_an_exchange_runs_until_the_interviewer_speaks_again():
    turns = agent.build_turns([line("candidate", "Hello?", 0), line("interviewer", "Hi.", 2), line("interviewer", "", 3)])
    exchanges = agent.group_exchanges(turns)
    assert [([t["n"] for t in e["question"]], [t["n"] for t in e["answer"]]) for e in exchanges] == [([], [1]), ([2], [])]


# ---------- Task 9.1.2: question-answer pairs ----------


def test_a_multi_part_question_becomes_one_pair_per_part(ai):
    pairs = run()["pairs"]
    generator = [p for p in pairs if "generator" in p["question"]]
    assert [p["question"] for p in generator] == ["What is a Python generator?", "When would you use a generator?"]
    assert [(p["part"], p["parts"]) for p in generator] == [(1, 2), (2, 2)]
    assert generator[0]["answer_turns"][:1] == generator[1]["answer_turns"][:1] == [4]  # both parts share the answer


def test_a_follow_up_joins_the_question_it_follows(ai):
    pairs = run()["pairs"]
    last_part = next(p for p in pairs if p["question"] == "When would you use a generator?")
    assert last_part["follow_ups"] == ["Can you give an example?"]
    assert last_part["turns"] == [3, 4, 5, 6] and last_part["answer_turns"] == [4, 6]
    assert not any(p["question"] == "Can you give an example?" for p in pairs)  # not a pair of its own


def test_every_pair_keeps_the_interviewers_own_words_and_start_time(ai):
    pairs = run()["pairs"]
    assert [p["id"] for p in pairs] == [1, 2, 3, 4]
    greeting = pairs[0]
    assert greeting["question"] == "Hi Maya, can you hear me?"  # nothing asked: the words themselves are kept
    assert pairs[3]["asked"] == "How do you index a PostgreSQL table?" and pairs[3]["start_ms"] == 40_000


def test_an_exchange_the_ai_skipped_is_kept_as_one_pair(monkeypatch):
    fake = FakeAI(plans={1: PLANS[1], 2: PLANS[2], 3: PLANS[3]})  # nothing for exchange 4
    monkeypatch.setattr(agent, "ask", fake)
    pairs = run()["pairs"]
    assert pairs[-1]["question"] == "How do you index a PostgreSQL table?"
    assert pairs[-1]["answer_turns"] == [8]


def test_long_interviews_are_sent_in_batches(monkeypatch):
    lines = []
    for i in range(25):
        lines += [line("interviewer", f"Question {i}?", i * 10), line("candidate", f"Answer {i}.", i * 10 + 5)]
    fake = FakeAI(plans={n: {"questions": [f"Question {n - 1}?"], "follow_up": False} for n in range(1, 26)}, kinds={})
    monkeypatch.setattr(agent, "ask", fake)
    pairs = run(agent.build_turns(lines))["pairs"]
    assert len(pairs) == 25
    assert [shape for shape, _ in fake.calls].count(Segmentation) == 3  # 12 + 12 + 1 exchanges


# ---------- Task 9.1.2: job-related or small talk ----------


def test_small_talk_is_kept_but_marked(ai):
    pairs = run()["pairs"]
    assert pairs[0]["kind"] == "small_talk"
    assert [p["kind"] for p in pairs[1:]] == ["job_related"] * 3


def test_a_pair_the_ai_did_not_sort_counts_as_job_related(monkeypatch):
    fake = FakeAI(kinds={1: "small_talk"})
    original = fake.__call__

    def forgetful(system_prompt, user_prompt, answer_shape):
        answer = original(system_prompt, user_prompt, answer_shape)
        if answer_shape is PairKinds:
            answer.pairs = [p for p in answer.pairs if p.id != 4]
        return answer

    monkeypatch.setattr(agent, "ask", forgetful)
    assert run()["pairs"][3]["kind"] == "job_related"


def test_an_ai_failure_stops_with_a_clear_message(monkeypatch):
    monkeypatch.setattr(agent, "ask", FakeAI(broken={PairKinds}))
    result = run()
    assert result["error"] == "The AI service is not available right now. Please try again."
    assert "kind" not in result["pairs"][0]  # the step that failed changed nothing




# ---------- Task 9.1.3: requirements and scores ----------


def test_each_job_related_pair_is_linked_to_the_requirements_it_touches(ai):
    pairs = run()["pairs"]
    assert [p["requirements"] for p in pairs] == [[], [1], [1], [2]]  # duplicates removed, number 9 dropped
    asked = next(prompt for shape, prompt in ai.calls if shape is RequirementLinks)
    assert "1. Python" in asked and "Hi Maya" not in asked  # small talk is never sent


def test_small_talk_is_not_scored(ai):
    greeting = run()["pairs"][0]
    assert greeting["scores"] is None and greeting["overall"] is None and greeting["evidence"] is None


def test_answers_get_four_scores_with_reasons_and_evidence(ai):
    pair = run()["pairs"][1]
    assert set(pair["scores"]) == {"relevance", "accuracy", "completeness", "articulation"}
    assert pair["scores"]["accuracy"] == {"score": 80, "justification": "Named the key idea."}
    assert pair["overall"] == 80
    assert pair["evidence"] == {"turn": 4, "start_ms": 15_000, "quote": "yields values one at a time"}
    assert pair["references"] == [{"skill": "Python", "heading": "Generators", "url": "https://docs.python.org/3/"}]


def test_the_reference_search_uses_the_question_and_its_requirements(ai, fake_references):
    run()
    assert fake_references[-1] == "How do you index a PostgreSQL table? PostgreSQL"


def test_scores_are_rounded_to_steps_of_five(monkeypatch):
    fake = FakeAI(answers=[scores(83), scores(77), scores(42)])
    monkeypatch.setattr(agent, "ask", fake)
    pairs = run()["pairs"]
    assert [p["overall"] for p in pairs[1:]] == [85, 75, 40]


def test_a_score_outside_the_range_is_asked_again(monkeypatch):
    fake = FakeAI(answers=[scores(140), scores(70)])
    monkeypatch.setattr(agent, "ask", fake)
    assert run()["pairs"][1]["overall"] == 70


def test_two_bad_scores_stop_with_a_clear_message(monkeypatch):
    fake = FakeAI(answers=[scores(140), scores(-5)])
    monkeypatch.setattr(agent, "ask", fake)
    assert run()["error"] == "The AI gave a score outside 0-100."


def test_evidence_never_shows_words_the_candidate_did_not_say(monkeypatch):
    # Turn 2 is the greeting answer, not part of this exchange; the quote is made up.
    fake = FakeAI(answers=[scores(80, turn=2, quote="I am an expert in everything")])
    monkeypatch.setattr(agent, "ask", fake)
    evidence = run()["pairs"][1]["evidence"]
    assert evidence["turn"] == 4  # moved to the candidate's own answer in this exchange
    assert evidence["quote"] == "A generator yields values one at a time. I use them for large files."


def test_a_quote_from_a_follow_up_answer_points_at_that_answer(monkeypatch):
    # Pair 3 holds turns 4 and 6; the quote is from turn 6 although the AI named turn 4.
    fake = FakeAI(answers=[scores(80), scores(80, turn=4, quote="Reading a 5 GB log line by line.")])
    monkeypatch.setattr(agent, "ask", fake)
    evidence = run()["pairs"][2]["evidence"]
    assert evidence == {"turn": 6, "start_ms": 28_000, "quote": "Reading a 5 GB log line by line."}


def test_an_unanswered_question_scores_zero_without_asking_the_ai(monkeypatch):
    fake = FakeAI(plans={1: PLANS[1], 2: {"questions": ["Why Python?"], "follow_up": False}}, kinds={1: "small_talk"})
    monkeypatch.setattr(agent, "ask", fake)
    turns = agent.build_turns(TRANSCRIPT[:2] + [line("interviewer", "Why Python?", 9)])
    pair = run(turns)["pairs"][1]
    assert pair["overall"] == 0 and pair["scores"]["relevance"]["justification"] == "The candidate did not answer this question."
    assert AnswerScores not in [shape for shape, _ in fake.calls]


def test_a_job_without_requirements_is_still_scored(ai):
    pairs = run(job={"title": "Backend Developer", "description": "", "requirements": []})["pairs"]
    assert all(p["requirements"] == [] for p in pairs)
    assert pairs[1]["overall"] == 80




# ---------- Task 9.2.1: requirement coverage ----------


def test_coverage_shows_what_the_interview_explored_and_what_it_missed(monkeypatch):
    fake = FakeAI(answers=[scores(80), scores(70), scores(30)])  # pair 4 (PostgreSQL) is a weak answer
    monkeypatch.setattr(agent, "ask", fake)
    coverage = run()["coverage"]
    assert [(c["number"], c["requirement"], c["status"], c["pairs"], c["best_score"]) for c in coverage] == [
        (1, "Python", "explored", [2, 3], 80),
        (2, "PostgreSQL", "weak", [4], 30),
        (3, "Kubernetes", "not_explored", [], None),
    ]
    assert coverage[2]["mandatory"] is False and coverage[2]["kind"] == "preferred"


def test_small_talk_never_counts_as_exploring_a_requirement(monkeypatch):
    fake = FakeAI(kinds={1: "small_talk", 2: "small_talk", 3: "small_talk", 4: "small_talk"})
    monkeypatch.setattr(agent, "ask", fake)
    result = run()
    assert all(c["status"] == "not_explored" for c in result["coverage"])
    assert RequirementLinks not in [shape for shape, _ in fake.calls]  # nothing job-related to link


def test_a_failed_run_has_no_coverage(monkeypatch):
    monkeypatch.setattr(agent, "ask", FakeAI(broken={AnswerScores}))
    result = run()
    assert result["error"] and "coverage" not in result