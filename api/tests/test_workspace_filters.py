"""Tests for the candidate and interview filters and the dashboard to-do list (Task 14.2.1).

The dashboard links to /candidates?stage=new and ?stage=screened, so every stage must be accepted.
The helpers come from test_workspace.py, so both files build their data the same way.
"""

from datetime import timedelta

from app.db import SessionLocal
from app.models import InterviewSession, LitmusCheck
from app.routers.workspace import local_day
from tests.test_workspace import get, in_hours, make_candidate, make_interview, make_job, shortlisted


def names(rows: list[dict]) -> set[str]:
    return {row["name"] for row in rows}


# ---------- Candidates: every stage can be asked for ----------


def test_the_dashboard_links_open_the_right_people(client, auth_headers):
    job = make_job("Backend Developer")
    shortlisted(make_candidate(job, "Maya Rahman", score=82))
    make_candidate(job, "Ready Rafi", score=75)  # passed screening, not invited yet
    make_candidate(job, "New Nadia", status="uploaded")
    make_candidate(job, "Out Omar", status="excluded")

    assert names(get(client, auth_headers, "/api/workspace/candidates?stage=screened")) == {"Ready Rafi"}
    assert names(get(client, auth_headers, "/api/workspace/candidates?stage=new")) == {"New Nadia"}
    assert names(get(client, auth_headers, "/api/workspace/candidates?stage=excluded")) == {"Out Omar"}
    assert len(get(client, auth_headers, "/api/workspace/candidates?stage=all")) == 4
    # No stage is still the shortlist, as before.
    assert names(get(client, auth_headers, "/api/workspace/candidates")) == {"Maya Rahman"}


def test_an_unknown_stage_is_refused(client, auth_headers):
    response = client.get("/api/workspace/candidates?stage=hired", headers=auth_headers)
    assert response.status_code == 422


# ---------- Interviews: not ended, dates and test calls ----------


def test_a_call_nobody_ended_is_not_happening_now(client, auth_headers):
    job = make_job("Backend Developer")
    make_interview(make_candidate(job, "Maya Rahman", score=82), status="live", hours=-5)  # started 5 hours ago
    make_interview(make_candidate(job, "Arif Khan", score=61), status="live", hours=0.1)

    live = get(client, auth_headers, "/api/workspace/interviews?state=live")
    not_ended = get(client, auth_headers, "/api/workspace/interviews?state=not_ended")
    assert [row["candidate_name"] for row in live] == ["Arif Khan"]
    assert [row["candidate_name"] for row in not_ended] == ["Maya Rahman"]
    assert not_ended[0]["forgotten"] is True


def test_interviews_can_be_narrowed_to_a_date_range(client, auth_headers):
    job = make_job("Backend Developer")
    make_interview(make_candidate(job, "Soon Sami", score=70), hours=2)
    make_interview(make_candidate(job, "Later Lina", score=71), hours=24 * 5)

    later_day = local_day(in_hours(24 * 5))
    rows = get(client, auth_headers, f"/api/workspace/interviews?date_from={later_day}&date_to={later_day}")
    assert [row["candidate_name"] for row in rows] == ["Later Lina"]
    rows = get(client, auth_headers, f"/api/workspace/interviews?date_to={later_day - timedelta(days=1)}")
    assert [row["candidate_name"] for row in rows] == ["Soon Sami"]


def test_test_calls_can_be_hidden(client, auth_headers):
    job = make_job("Backend Developer")
    real = make_interview(make_candidate(job, "Maya Rahman", score=82), status="ended", hours=-5, lines=4)
    short = make_interview(make_candidate(job, "Arif Khan", score=61), status="ended", hours=-4)
    with SessionLocal() as db:
        session = db.get(InterviewSession, short)
        session.ended_at = session.started_at + timedelta(seconds=40)  # a 40-second call, nothing said
        db.commit()

    assert len(get(client, auth_headers, "/api/workspace/interviews")) == 2
    rows = get(client, auth_headers, "/api/workspace/interviews?hide_test_calls=true")
    assert [row["id"] for row in rows] == [real]


# ---------- The dashboard to-do list ----------


def test_a_litmus_check_waiting_for_review_is_on_the_to_do_list(client, auth_headers):
    job = make_job("Backend Developer")
    waiting = make_candidate(job, "Maya Rahman", score=82)
    done = make_candidate(job, "Arif Khan", score=61)
    with SessionLocal() as db:
        db.add(LitmusCheck(candidate_id=waiting, status="done", review_status="pending"))
        db.add(LitmusCheck(candidate_id=done, status="done", review_status="pending"))
        db.add(LitmusCheck(candidate_id=done, status="done", review_status=""))  # checked again: steady now
        db.commit()

    todo = get(client, auth_headers, "/api/workspace/overview")["todo"]
    litmus = [item for item in todo if "Litmus" in item["text"]]
    assert [item["to"] for item in litmus] == [f"/candidates/{waiting}?tab=litmus"]
