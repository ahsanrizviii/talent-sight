"""Tests for the hiring rounds: a job's interview rounds, closing a round (who passes is the hiring
team's choice), the next round's invitations, rejection e-mails, the report decision and onboarding."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import assessment, hiring_rounds, mail_writer
from app.db import SessionLocal
from app.models import CandidateEmail, HiringDecision, InterviewScore, InterviewSession, JobProfile, RoundDecision
from app.routers import invite_batches

from tests.test_interviews import fake_video_server  # noqa: F401
from tests.test_invite_batches import make_job_with_ranked, next_monday
from tests.test_invite_mail import FakeSMTP, fake_mail_server  # noqa: F401
from tests.test_jobs import JOB

TWO_ROUNDS = [{"name": "HR interview", "focus": "Communication"}, {"name": "Technical interview", "focus": "Python"}]


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(invite_batches, "PAUSE_SECONDS", 0)
    monkeypatch.setattr(hiring_rounds, "PAUSE_SECONDS", 0)


def set_rounds(job_id: int, rounds: list[dict]) -> None:
    with SessionLocal() as db:
        db.get(JobProfile, job_id).interview_rounds = rounds
        db.commit()


def held_interview(candidate_id: int, round_number: int, score: float | None) -> int:
    """An interview that took place yesterday, with its interview score (None = not scored)."""
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    with SessionLocal() as db:
        session = InterviewSession(
            candidate_id=candidate_id,
            scheduled_at=yesterday,
            invite_token=f"token-{candidate_id}-{round_number}",
            invite_expires_at=yesterday + timedelta(hours=24),
            status="ended",
            started_at=yesterday,
            ended_at=yesterday + timedelta(hours=1),
            duration_minutes=60,
            round_number=round_number,
        )
        db.add(session)
        db.flush()
        if score is not None:
            db.add(InterviewScore(session_id=session.id, status="done", result={"overall": score, "dimensions": [], "answers": 1}))
        db.commit()
        return session.id


def close(client, headers, job_id, number, passed, start=True):
    body = {"passed_ids": passed, "rule": "manual"}
    if start:
        body["start_date"] = next_monday().isoformat()
    return client.post(f"/api/jobs/{job_id}/rounds/{number}/close", json=body, headers=headers)


def test_a_job_has_one_round_unless_more_are_given(client, auth_headers):
    created = client.post("/api/jobs", json=JOB, headers=auth_headers).json()
    assert created["interview_rounds"] == [{"name": "Interview", "focus": ""}]

    changed = client.put(f"/api/jobs/{created['id']}", json={**JOB, "interview_rounds": TWO_ROUNDS}, headers=auth_headers).json()
    assert [r["name"] for r in changed["interview_rounds"]] == ["HR interview", "Technical interview"]

    refused = client.put(f"/api/jobs/{created['id']}", json={**JOB, "interview_rounds": []}, headers=auth_headers)
    assert refused.status_code == 422  # every job has at least one round


def test_a_round_is_ranked_by_the_interview_score(client, auth_headers):
    job, ids = make_job_with_ranked(3)
    set_rounds(job, TWO_ROUNDS)
    held_interview(ids[0], 1, 55)
    held_interview(ids[1], 1, 85)
    held_interview(ids[2], 1, None)  # attended, not scored yet

    view = client.get(f"/api/jobs/{job}/rounds/1", headers=auth_headers).json()
    assert view["state"] == "open" and view["name"] == "HR interview" and not view["is_last"]
    assert [r["candidate_id"] for r in view["rows"]] == [ids[1], ids[0], ids[2]]
    assert [r["rank"] for r in view["rows"]] == [1, 2, None]


def test_closing_a_round_invites_who_passed_and_rejects_the_rest(client, auth_headers):
    job, ids = make_job_with_ranked(3)
    set_rounds(job, TWO_ROUNDS)
    for candidate_id, score in zip(ids, (90, 75, 40)):
        held_interview(candidate_id, 1, score)

    result = close(client, auth_headers, job, 1, ids[:2])
    assert result.status_code == 200
    body = result.json()
    assert body["passed"] == 2 and body["rejected"] == 1 and body["next_round"] == 2 and body["booked"] == 2

    with SessionLocal() as db:
        second = db.scalars(select(InterviewSession).where(InterviewSession.round_number == 2)).all()
        assert sorted(s.candidate_id for s in second) == sorted(ids[:2])
        decisions = {d.candidate_id: d.outcome for d in db.scalars(select(RoundDecision))}
        assert decisions == {ids[0]: "passed", ids[1]: "passed", ids[2]: "rejected"}
        rejection = db.scalar(select(CandidateEmail).where(CandidateEmail.candidate_id == ids[2]))
        assert rejection.kind == "rejection" and rejection.status == "sent"

    # The next-round invitations name the round; the rejection goes to the one who did not pass.
    subjects = {m["To"]: m["Subject"] for m in FakeSMTP.sent}
    assert "Technical interview" in subjects["person1@example.com"]
    assert "person3@example.com" in subjects

    emails = client.get(f"/api/jobs/{job}/emails", headers=auth_headers).json()
    assert sorted(e["kind"] for e in emails) == ["invitation", "invitation", "rejection"]
    assert close(client, auth_headers, job, 1, ids[:2]).status_code == 409  # closed once only


def test_a_round_with_interviews_still_to_come_cannot_be_closed(client, auth_headers):
    job, ids = make_job_with_ranked(2)
    held_interview(ids[0], 1, 80)
    client.post(
        "/api/jobs/{}/invite-top".format(job), json={"top": 2, "start_date": next_monday().isoformat()}, headers=auth_headers
    )  # the second candidate is booked, not held yet
    refused = close(client, auth_headers, job, 1, [ids[0]], start=False)
    assert refused.status_code == 409
    assert "not finished" in refused.json()["detail"]


def test_after_the_last_round_the_report_decides_onboarding(client, auth_headers):
    job, ids = make_job_with_ranked(2)  # one round
    held_interview(ids[0], 1, 88)
    held_interview(ids[1], 1, 72)
    assert close(client, auth_headers, job, 1, ids, start=False).json()["next_round"] is None

    report = client.get(f"/api/jobs/{job}/report", headers=auth_headers).json()
    assert sorted(r["candidate_id"] for r in report) == sorted(ids)
    assert [r["round_scores"][0]["score"] for r in sorted(report, key=lambda r: r["candidate_id"])] == [88, 72]

    decided = client.post(
        f"/api/jobs/{job}/report/decide", json={"selected_ids": [ids[0]], "onboarding_date": next_monday().isoformat()}, headers=auth_headers
    ).json()
    assert decided == {"selected": 1, "rejected": 1}
    with SessionLocal() as db:
        decisions = {d.candidate_id: d.decision for d in db.scalars(select(HiringDecision))}
    assert decisions == {ids[0]: "onboarding", ids[1]: "rejected"}

    onboarding = client.get(f"/api/jobs/{job}/onboarding", headers=auth_headers).json()
    assert [r["candidate_id"] for r in onboarding] == [ids[0]] and onboarding[0]["check_state"] == "waiting"
    desk = client.get("/api/workspace/identity-checks", headers=auth_headers).json()
    assert [r["candidate_id"] for r in desk] == [ids[0]]

    stages = {p["id"]: p["stage"] for p in client.get("/api/workspace/candidates?stage=all", headers=auth_headers).json()}
    assert stages[ids[0]] == "onboarding" and stages[ids[1]] == "rejected"
    welcome = next(m for m in FakeSMTP.sent if m["To"] == "person1@example.com")
    assert "photo ID" in welcome.get_body(("plain",)).get_content()


def test_the_report_joins_the_answers_of_every_round():
    job = JobProfile(title="Data Engineer", interview_rounds=TWO_ROUNDS)
    first = SimpleNamespace(result={
        "pairs": [{"id": 1, "kind": "job_related", "question": "Why us?", "overall": 60}],
        "coverage": [{"requirement": "Python", "status": "not_explored", "best_score": None, "pairs": []}],
    })
    second = SimpleNamespace(result={
        "pairs": [{"id": 1, "kind": "job_related", "question": "Explain a decorator", "overall": 80}],
        "coverage": [{"requirement": "Python", "status": "explored", "best_score": 80, "pairs": [1]}],
    })
    merged = assessment.merge_analyses(job, [(first, SimpleNamespace(round_number=1)), (second, SimpleNamespace(round_number=2))])
    assert [p["id"] for p in merged["pairs"]] == [1, 2]  # numbered on across the rounds
    assert merged["pairs"][1]["question"].startswith("[Round 2 · Technical interview]")
    assert merged["coverage"] == [{"requirement": "Python", "status": "explored", "best_score": 80, "pairs": [2]}]
    assert merged["summary"]["average"] == 70


def test_rejection_and_onboarding_wording_without_the_ai():
    rejection, source = mail_writer.write_outcome("Ayesha", "Software Engineer", "rejection", "HR interview")
    assert source == "template" and "HR interview" in rejection.intro
    welcome, _ = mail_writer.write_outcome("Ayesha", "Software Engineer", "onboarding")
    assert "photo ID" in welcome.intro
