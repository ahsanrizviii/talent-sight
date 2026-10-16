"""Tests for the side-by-side comparison of assessed candidates (Task 10.2.2). The AI is a fake."""

from sqlalchemy import select

from app import assessment
from app.db import SessionLocal
from app.models import Candidate, InterviewEvaluation, InterviewSession, JobProfile
from tests.test_assessment_agent import ANALYSIS
from tests.test_assessments import assess, candidate, fake_ai  # noqa: F401  (fake_ai: the AI stays fake here too)


def job_id() -> int:
    with SessionLocal() as db:
        return db.scalar(select(JobProfile.id).where(JobProfile.title == "Backend Developer"))


def with_answers(candidate_id: int, average: int) -> None:
    """Gives the candidate's analysed interview another average answer score."""
    with SessionLocal() as db:
        evaluation = db.scalar(
            select(InterviewEvaluation).join(InterviewSession).where(InterviewSession.candidate_id == candidate_id)
        )
        evaluation.result = {**ANALYSIS, "summary": {"average": average}}
        db.commit()


def compare(client, headers, job: int):
    return client.get(f"/api/jobs/{job}/assessments", headers=headers)


def test_assessed_candidates_are_compared_best_first(client, auth_headers):
    maya, arif = candidate(name="Maya Rahman"), candidate(name="Arif Hossain")
    with_answers(arif, 95)
    for person in (maya, arif):
        assess(client, auth_headers, person)

    result = compare(client, auth_headers, job_id()).json()
    assert result["job_title"] == "Backend Developer" and result["waiting"] == 0
    assert [(c["name"], c["position"]["overall"]) for c in result["candidates"]] == [("Arif Hossain", 74.8), ("Maya Rahman", 61.6)]
    first = result["candidates"][0]
    assert [c["key"] for c in first["components"]] == ["cv_score", "requirements", "answers", "coverage"]
    assert first["strengths"] == ["Explains Python generators clearly."]
    assert (first["gaps"], first["must_have_gaps"]) == (3, 1)


def test_each_requirement_is_one_row_with_both_sources(client, auth_headers):
    assess(client, auth_headers, candidate())
    result = compare(client, auth_headers, job_id()).json()
    assert [(r["requirement"], r["mandatory"]) for r in result["requirements"]] == [
        ("Python", True), ("PostgreSQL", True), ("Docker", False), ("Kubernetes", False),
    ]
    assert result["candidates"][0]["requirements"]["postgresql"] == {"cv": "partially_met", "interview": "weak", "best_score": 40}


def test_unfinished_assessments_are_left_out_and_counted(client, auth_headers, monkeypatch):
    assess(client, auth_headers, candidate(name="Maya Rahman"))
    monkeypatch.setattr(assessment, "run_assessment", lambda assessment_id: None)  # stays "running"
    assess(client, auth_headers, candidate(name="Arif Hossain"))
    candidate(name="Nadia Islam")  # interviewed, never assessed
    result = compare(client, auth_headers, job_id()).json()
    assert [c["name"] for c in result["candidates"]] == ["Maya Rahman"]
    assert result["waiting"] == 2


def test_other_jobs_are_never_mixed_in(client, auth_headers):
    assess(client, auth_headers, candidate())
    with SessionLocal() as db:
        other = JobProfile(title="Data Analyst")
        db.add(other)
        db.commit()
        other_id = other.id
        assert db.scalar(select(Candidate.job_profile_id)) != other_id
    result = compare(client, auth_headers, other_id).json()
    assert result["candidates"] == [] and result["waiting"] == 0


def test_the_comparison_is_for_interviewers_only(client, auth_headers):
    candidate()
    assert compare(client, {}, job_id()).status_code == 401
    assert compare(client, auth_headers, 999999).status_code == 404