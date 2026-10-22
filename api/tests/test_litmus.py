"""Tests for running Litmus checks, the human review, the shortlist queue and the job summary (F11).

The AI is the fake from test_litmus_engine.py, so no real model is ever called.
"""

from pydantic import BaseModel
from sqlalchemy import select

from app import llm, litmus_run
from app.db import SessionLocal
from app.models import Candidate, CandidateScore, JobProfile, LitmusCheck, RequirementVerdict
from app.settings import settings
from tests.test_litmus_engine import PROFILE, FakeAI, use


def job() -> int:
    """The test job: Python, SQL, a degree, 3+ years (all must-have) and Docker (preferred)."""
    with SessionLocal() as db:
        found = JobProfile(
            title="Backend Developer",
            description="Build and run Python APIs on PostgreSQL.",
            required_skills=["Python", "SQL"],
            qualifications=["BSc in Computer Science"],
            min_experience_years=3,
            preferred_skills=["Docker"],
        )
        db.add(found)
        db.commit()
        return found.id


def candidate(job_id: int | None = None, name: str = "Priya Saha", overall: float = 77.8, screened: bool = True) -> int:
    with SessionLocal() as db:
        person = Candidate(
            job_profile_id=job_id or job(),
            name=name,
            cv_filename="cv.pdf",
            status="screened" if screened else "uploaded",
            profile={**PROFILE, "name": name} if screened else {},
        )
        db.add(person)
        db.flush()
        if screened:
            db.add(CandidateScore(candidate_id=person.id, technical_skills=80, experience=70, qualifications=90, jd_match=75, overall=overall))
            db.add(RequirementVerdict(candidate_id=person.id, requirement="Python", kind="skill", mandatory=True, verdict="met"))
        db.commit()
        return person.id


def start(client, headers, candidate_id: int):
    return client.post(f"/api/candidates/{candidate_id}/litmus", headers=headers)


def read(client, headers, candidate_id: int):
    return client.get(f"/api/candidates/{candidate_id}/litmus", headers=headers).json()


def test_the_check_answers_at_once_and_runs_in_the_background(client, auth_headers, monkeypatch):
    use(monkeypatch, FakeAI())
    candidate_id = candidate()
    started = start(client, auth_headers, candidate_id)
    assert started.status_code == 202
    assert started.json()["status"] == "running" and started.json()["step"] == litmus_run.FIRST_STEP

    done = read(client, auth_headers, candidate_id)  # the background work has finished by now
    assert done["status"] == "done" and done["error"] == "" and done["outdated"] is False
    assert done["result"]["outcome"] == "steady" and done["review_status"] == ""
    assert len(done["result"]["variants"]) == 4
    assert done["result"]["audit"]["prompt_version"] == litmus_run.PROMPT_VERSION
    assert "profile" not in str(done["result"]["variants"])  # the copies themselves are never stored


def test_nothing_is_there_before_anyone_asks(client, auth_headers):
    assert read(client, auth_headers, candidate()) is None


def test_the_check_needs_a_screened_candidate(client, auth_headers):
    response = start(client, auth_headers, candidate(screened=False))
    assert response.status_code == 400 and response.json()["detail"] == litmus_run.NOT_SCREENED


def test_the_check_never_touches_the_score_or_the_verdicts(client, auth_headers, monkeypatch):
    use(monkeypatch, FakeAI(marked_down="Daniel Novak"))
    candidate_id = candidate()
    start(client, auth_headers, candidate_id)
    with SessionLocal() as db:
        score = db.scalar(select(CandidateScore).where(CandidateScore.candidate_id == candidate_id))
        assert score.overall == 77.8 and score.technical_skills == 80
        assert len(db.scalars(select(RequirementVerdict).where(RequirementVerdict.candidate_id == candidate_id)).all()) == 1
        assert db.get(Candidate, candidate_id).status == "screened"


def test_a_flagged_result_waits_for_a_person(client, auth_headers, monkeypatch):
    use(monkeypatch, FakeAI(marked_down="Daniel Novak"))
    candidate_id = candidate()
    start(client, auth_headers, candidate_id)
    done = read(client, auth_headers, candidate_id)
    assert done["result"]["outcome"] == "needs_review" and done["review_status"] == "pending"

    review = f"/api/litmus/{done['id']}/review"
    short = client.post(review, json={"note": "ok"}, headers=auth_headers)
    assert short.status_code == 400 and short.json()["detail"] == litmus_run.NOTE_TOO_SHORT

    note = "Read the name B copy; raised it with the screening owner."
    signed = client.post(review, json={"note": note}, headers=auth_headers).json()
    assert signed["review_status"] == "acknowledged" and signed["review_note"] == note
    assert signed["reviewed_by"] == settings.seed_interviewer_email and signed["reviewed_at"]

    again = client.post(review, json={"note": note}, headers=auth_headers)
    assert again.status_code == 400 and again.json()["detail"] == litmus_run.NOTHING_TO_REVIEW


def test_a_steady_result_has_nothing_to_review(client, auth_headers, monkeypatch):
    use(monkeypatch, FakeAI())
    candidate_id = candidate()
    start(client, auth_headers, candidate_id)
    done = read(client, auth_headers, candidate_id)
    response = client.post(f"/api/litmus/{done['id']}/review", json={"note": "Nothing to see here."}, headers=auth_headers)
    assert response.status_code == 400


def test_checking_again_adds_a_record_and_keeps_the_old_one(client, auth_headers, monkeypatch):
    use(monkeypatch, FakeAI())
    candidate_id = candidate()
    start(client, auth_headers, candidate_id)
    start(client, auth_headers, candidate_id)
    history = client.get(f"/api/candidates/{candidate_id}/litmus/history", headers=auth_headers).json()
    assert len(history) == 2 and history[0]["id"] > history[1]["id"]
    assert all(item["outcome"] == "steady" for item in history)


def test_a_check_is_outdated_when_the_weights_change(client, auth_headers, monkeypatch):
    use(monkeypatch, FakeAI())
    candidate_id = candidate()
    start(client, auth_headers, candidate_id)
    with SessionLocal() as db:
        found = db.get(JobProfile, db.get(Candidate, candidate_id).job_profile_id)
        found.weights = {"technical_skills": 25, "experience": 25, "qualifications": 25, "jd_match": 25}
        db.commit()
    assert read(client, auth_headers, candidate_id)["outdated"] is True


def test_a_failed_ai_is_shown_as_a_failed_check(client, auth_headers, monkeypatch):
    use(monkeypatch, FakeAI(broken_after=3))
    candidate_id = candidate()
    start(client, auth_headers, candidate_id)
    done = read(client, auth_headers, candidate_id)
    assert done["status"] == "failed" and "not available" in done["error"] and done["result"] == {}


def test_a_running_check_cannot_be_started_twice(client, auth_headers):
    candidate_id = candidate()
    with SessionLocal() as db:
        db.add(LitmusCheck(candidate_id=candidate_id, status="running"))
        db.commit()
    assert start(client, auth_headers, candidate_id).status_code == 409


def test_the_shortlist_check_takes_the_top_and_never_pays_twice(client, auth_headers, monkeypatch):
    use(monkeypatch, FakeAI(marked_down="Daniel Novak"))
    monkeypatch.setattr(settings, "litmus_shortlist_size", 2)
    job_id = job()
    best = candidate(job_id, "Priya Saha", overall=90)
    second = candidate(job_id, "Arif Hossain", overall=80)
    third = candidate(job_id, "Maya Rahman", overall=70)

    queued = client.post(f"/api/jobs/{job_id}/litmus", headers=auth_headers)
    assert queued.status_code == 202 and queued.json()["queued"] == 2
    with SessionLocal() as db:
        checked = {row.candidate_id for row in db.scalars(select(LitmusCheck)).all()}
    assert checked == {best, second} and third not in checked

    again = client.post(f"/api/jobs/{job_id}/litmus", headers=auth_headers)
    assert again.status_code == 400 and again.json()["detail"] == litmus_run.ALL_CHECKED


def test_the_job_summary_adds_up_the_latest_checks(client, auth_headers, monkeypatch):
    use(monkeypatch, FakeAI(marked_down="Daniel Novak"))
    job_id = job()
    start(client, auth_headers, candidate(job_id, "Priya Saha"))
    start(client, auth_headers, candidate(job_id, "Arif Hossain"))
    candidate(job_id, "Maya Rahman")  # never checked

    summary = client.get(f"/api/jobs/{job_id}/litmus", headers=auth_headers).json()
    assert summary["checked"] == 2 and summary["pending_review"] == 2 and summary["pass_rate"] == 0
    copies = {c["key"]: c for c in summary["copies"]}
    assert copies["name_b"]["flags"] == 2 and copies["name_b"]["average_move"] == 8.0
    assert copies["blind"]["flags"] == 0 and copies["blind"]["average_move"] == 0.0


def test_the_shortlist_needs_a_screening_first(client, auth_headers):
    job_id = job()
    candidate(job_id, screened=False)
    response = client.post(f"/api/jobs/{job_id}/litmus", headers=auth_headers)
    assert response.status_code == 400 and response.json()["detail"] == litmus_run.NO_SHORTLIST


def test_a_restart_marks_unfinished_checks_as_interrupted(client):
    candidate_id = candidate()
    with SessionLocal() as db:
        db.add(LitmusCheck(candidate_id=candidate_id, status="queued"))
        db.commit()
    litmus_run.mark_interrupted()
    with SessionLocal() as db:
        row = db.scalar(select(LitmusCheck).where(LitmusCheck.candidate_id == candidate_id))
        assert row.status == "failed" and row.error == litmus_run.INTERRUPTED


# ---------- What the AI calls used and cost ----------
class Answer(BaseModel):
    ok: bool = True


class FakeChat:
    """Stands in for ChatGroq: answers at once and reports 1000 tokens in and 200 out."""

    def __init__(self, **options):
        self.shape = Answer

    def with_structured_output(self, shape, method):
        self.shape = shape
        return self

    def invoke(self, messages, config=None):
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, LLMResult

        usage = {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200}
        result = LLMResult(generations=[[ChatGeneration(message=AIMessage(content="{}", usage_metadata=usage))]])
        for callback in (config or {}).get("callbacks", []):
            callback.on_llm_end(result)
        return self.shape()


def test_usage_and_cost_are_counted_inside_measure_usage(monkeypatch):
    monkeypatch.setattr(llm, "ChatGroq", FakeChat)
    monkeypatch.setattr(settings, "llm_price_input_per_million", 0.15)
    monkeypatch.setattr(settings, "llm_price_output_per_million", 0.60)
    with llm.measure_usage() as meter:
        llm.ask_llm("system", "question", Answer)
        llm.ask_llm("system", "question", Answer)
    assert (meter.calls, meter.input_tokens, meter.output_tokens) == (2, 2000, 400)
    assert meter.cost_usd() == 0.00054

    llm.ask_llm("system", "question", Answer)  # outside: nothing is counted
    assert meter.calls == 2
