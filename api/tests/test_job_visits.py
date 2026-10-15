"""Tests for the "new CVs since your last visit" notice on the job page."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.db import SessionLocal
from app.job_visits import record_visit
from app.models import Candidate, Interviewer, JobProfile


def make_job() -> int:
    with SessionLocal() as db:
        job = JobProfile(title="Data Engineer")
        db.add(job)
        db.commit()
        return job.id


def add_cv(job_id: int, when: datetime) -> None:
    with SessionLocal() as db:
        cv = Candidate(job_profile_id=job_id, name="Someone", cv_filename="cv.pdf")
        db.add(cv)
        db.flush()
        db.execute(update(Candidate).where(Candidate.id == cv.id).values(created_at=when))
        db.commit()


def make_person(email: str) -> int:
    with SessionLocal() as db:
        person = Interviewer(email=email, password_hash="x")
        db.add(person)
        db.commit()
        return person.id


NOW = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)


def visit(person: int, job: int, at: datetime):
    with SessionLocal() as db:
        return record_visit(db, person, job, at)


def test_first_visit_counts_every_cv(client):  # client = a fresh, empty database
    job, person = make_job(), make_person("a@example.com")
    add_cv(job, NOW - timedelta(days=2))
    add_cv(job, NOW - timedelta(days=1))
    result = visit(person, job, NOW)
    assert result.new_cvs == 2
    assert result.since is None


def test_later_visit_counts_only_cvs_that_came_after_the_last_one(client):  # client = a fresh, empty database
    job, person = make_job(), make_person("b@example.com")
    add_cv(job, NOW - timedelta(days=1))
    visit(person, job, NOW)
    add_cv(job, NOW + timedelta(hours=1))
    add_cv(job, NOW + timedelta(hours=2))
    result = visit(person, job, NOW + timedelta(hours=3))
    assert result.new_cvs == 2
    assert result.since == NOW


def test_no_new_cvs_gives_zero(client):  # client = a fresh, empty database
    job, person = make_job(), make_person("c@example.com")
    add_cv(job, NOW - timedelta(days=1))
    visit(person, job, NOW)
    assert visit(person, job, NOW + timedelta(hours=5)).new_cvs == 0


def test_a_quick_refresh_keeps_the_notice(client):  # client = a fresh, empty database
    """Reopening within a minute is the same visit, so the count does not drop to zero."""
    job, person = make_job(), make_person("d@example.com")
    add_cv(job, NOW - timedelta(days=1))
    visit(person, job, NOW)
    add_cv(job, NOW + timedelta(hours=1))
    first = visit(person, job, NOW + timedelta(hours=2))
    again = visit(person, job, NOW + timedelta(hours=2, seconds=20))
    assert first.new_cvs == again.new_cvs == 1


def test_each_person_has_their_own_last_visit(client):  # client = a fresh, empty database
    job = make_job()
    ana, ben = make_person("ana@example.com"), make_person("ben@example.com")
    add_cv(job, NOW - timedelta(days=1))
    visit(ana, job, NOW)
    add_cv(job, NOW + timedelta(hours=1))
    assert visit(ana, job, NOW + timedelta(hours=2)).new_cvs == 1
    assert visit(ben, job, NOW + timedelta(hours=2)).new_cvs == 2  # Ben never came before


def test_the_endpoint_needs_a_login_and_a_real_job(client, auth_headers):
    job = make_job()
    assert client.post(f"/api/jobs/{job}/visit").status_code == 401
    assert client.post("/api/jobs/999999/visit", headers=auth_headers).status_code == 404
    response = client.post(f"/api/jobs/{job}/visit", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"new_cvs": 0, "since": None}
