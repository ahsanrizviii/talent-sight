"""The views that look across every job at once (UI refresh).

They answer the questions a hiring team asks from the dashboard: who is in the pipeline,
what needs doing, and which interviews are coming up.
"""

from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import (
    Candidate,
    CandidateScore,
    InterviewSession,
    JobProfile,
    RequirementVerdict,
    TranscriptSegment,
)


def in_hours(hours: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def make_job(title: str, status: str = "published") -> int:
    with SessionLocal() as db:
        job = JobProfile(title=title, required_skills=["Python"], status=status, slug=f"{title.lower()}-x")
        db.add(job)
        db.commit()
        return job.id


def make_candidate(job_id: int, name: str, status: str = "screened", score: float | None = None, source: str = "upload") -> int:
    with SessionLocal() as db:
        candidate = Candidate(
            job_profile_id=job_id,
            name=name,
            email=f"{name.split()[0].lower()}@example.com",
            cv_filename=f"{name.split()[0].lower()}.pdf",
            status=status,
            source=source,
        )
        db.add(candidate)
        db.flush()
        if score is not None:
            db.add(
                CandidateScore(
                    candidate_id=candidate.id,
                    technical_skills=score,
                    experience=score,
                    qualifications=score,
                    jd_match=score,
                    overall=score,
                )
            )
        db.add(
            RequirementVerdict(
                candidate_id=candidate.id, requirement="Python", kind="skill", mandatory=True, verdict="met"
            )
        )
        db.commit()
        return candidate.id


def make_interview(candidate_id: int, status: str = "scheduled", hours: float = 2, lines: int = 0) -> int:
    with SessionLocal() as db:
        session = InterviewSession(
            candidate_id=candidate_id,
            scheduled_at=in_hours(hours),
            invite_token=f"token-{candidate_id}-{status}",
            invite_expires_at=in_hours(hours + 24),
            status=status,
            started_at=in_hours(hours) if status != "scheduled" else None,
            ended_at=in_hours(hours + 0.5) if status == "ended" else None,
        )
        db.add(session)
        db.flush()
        for number in range(lines):
            db.add(
                TranscriptSegment(
                    session_id=session.id,
                    speaker="candidate" if number % 2 else "interviewer",
                    text="Hello.",
                    start_ms=number * 1000,
                    end_ms=number * 1000 + 900,
                )
            )
        db.commit()
        return session.id


def get(client, headers, path: str):
    response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------- Candidates across every job: the shortlist ----------


def shortlisted(candidate_id: int, status: str = "scheduled") -> int:
    """Sends this candidate an interview invitation (a booked interview), so they are on the shortlist."""
    return make_interview(candidate_id, status=status)


def test_only_shortlisted_candidates_are_listed(client, auth_headers):
    backend = make_job("Backend Developer")
    designer = make_job("Product Designer")
    shortlisted(make_candidate(backend, "Maya Rahman", score=82))
    shortlisted(make_candidate(designer, "Arif Khan", score=61), status="ended")
    make_candidate(backend, "Not Invited", score=95)  # passed screening, never invited
    make_candidate(backend, "Rafi Islam", status="excluded")
    make_candidate(backend, "Tanvir Ahmed", status="uploaded")

    rows = get(client, auth_headers, "/api/workspace/candidates")
    assert [row["name"] for row in rows] == ["Maya Rahman", "Arif Khan"]  # best score first
    assert {row["stage"] for row in rows} == {"interview", "interviewed"}
    assert {row["job_title"] for row in rows} == {"Backend Developer", "Product Designer"}


def test_the_list_can_be_narrowed_by_job_stage_source_and_score(client, auth_headers):
    backend = make_job("Backend Developer")
    designer = make_job("Product Designer")
    shortlisted(make_candidate(backend, "Maya Rahman", score=82))
    shortlisted(make_candidate(backend, "Tanvir Ahmed", score=55, source="google_form"), status="ended")
    shortlisted(make_candidate(designer, "Arif Khan", score=61))

    assert len(get(client, auth_headers, f"/api/workspace/candidates?job_id={backend}")) == 2
    assert len(get(client, auth_headers, "/api/workspace/candidates?stage=interviewed")) == 1
    assert len(get(client, auth_headers, "/api/workspace/candidates?source=google_form")) == 1
    assert len(get(client, auth_headers, "/api/workspace/candidates?min_score=70")) == 1


def test_searching_finds_a_candidate_by_name_e_mail_or_job(client, auth_headers):
    backend = make_job("Backend Developer")
    shortlisted(make_candidate(backend, "Maya Rahman", score=82))
    shortlisted(make_candidate(backend, "Arif Khan", score=61))

    assert [r["name"] for r in get(client, auth_headers, "/api/workspace/candidates?q=maya")] == ["Maya Rahman"]
    assert [r["name"] for r in get(client, auth_headers, "/api/workspace/candidates?q=arif@example.com")] == ["Arif Khan"]
    assert len(get(client, auth_headers, "/api/workspace/candidates?q=backend")) == 2


def test_each_candidate_carries_their_stage_rank_and_interview(client, auth_headers):
    job = make_job("Backend Developer")
    first = make_candidate(job, "Maya Rahman", score=82)
    second = make_candidate(job, "Arif Khan", score=61)
    make_interview(first, status="ended", lines=4)
    shortlisted(second)

    rows = {row["name"]: row for row in get(client, auth_headers, "/api/workspace/candidates")}
    assert rows["Maya Rahman"]["rank"] == 1
    assert rows["Maya Rahman"]["stage"] == "interviewed"
    assert rows["Maya Rahman"]["transcript_lines"] == 4
    assert rows["Arif Khan"]["rank"] == 2
    assert rows["Arif Khan"]["stage"] == "interview"


def test_sorting_by_name_added_or_job(client, auth_headers):
    job = make_job("Backend Developer")
    shortlisted(make_candidate(job, "Zara Noor", score=50))
    shortlisted(make_candidate(job, "Abir Das", score=90))

    by_name = [r["name"] for r in get(client, auth_headers, "/api/workspace/candidates?sort=name")]
    assert by_name == ["Abir Das", "Zara Noor"]


# ---------- Interviews across every job ----------


def test_interviews_are_listed_with_their_candidate_and_job(client, auth_headers):
    job = make_job("Backend Developer")
    candidate = make_candidate(job, "Maya Rahman", score=82)
    make_interview(candidate, lines=6)

    rows = get(client, auth_headers, "/api/workspace/interviews")
    assert len(rows) == 1
    assert rows[0]["candidate_name"] == "Maya Rahman"
    assert rows[0]["job_title"] == "Backend Developer"
    assert rows[0]["transcript_lines"] == 6


def test_interviews_can_be_split_into_upcoming_live_and_past(client, auth_headers):
    job = make_job("Backend Developer")
    make_interview(make_candidate(job, "Maya Rahman", score=82), status="scheduled")
    make_interview(make_candidate(job, "Arif Khan", score=61), status="live")
    make_interview(make_candidate(job, "Rafi Islam", score=55), status="ended")

    assert len(get(client, auth_headers, "/api/workspace/interviews?state=upcoming")) == 1
    assert len(get(client, auth_headers, "/api/workspace/interviews?state=live")) == 1
    assert len(get(client, auth_headers, "/api/workspace/interviews?state=past")) == 1
    assert len(get(client, auth_headers, "/api/workspace/interviews")) == 3


def test_an_interview_whose_time_has_passed_is_marked_overdue(client, auth_headers):
    job = make_job("Backend Developer")
    make_interview(make_candidate(job, "Maya Rahman", score=82), status="scheduled", hours=-3)

    assert get(client, auth_headers, "/api/workspace/interviews")[0]["overdue"] is True


# ---------- Jobs with their numbers ----------


def test_each_job_shows_how_many_cvs_are_waiting_and_the_best_score(client, auth_headers):
    job = make_job("Backend Developer")
    make_candidate(job, "Maya Rahman", score=82)
    make_candidate(job, "Tanvir Ahmed", status="uploaded")

    row = get(client, auth_headers, "/api/workspace/jobs")[0]
    assert row["candidates"] == 2
    assert row["waiting"] == 1
    assert row["screened"] == 1
    assert row["top_score"] == 82


def test_jobs_can_be_filtered_by_draft_or_published(client, auth_headers):
    make_job("Backend Developer", status="published")
    make_job("Product Designer", status="draft")

    assert len(get(client, auth_headers, "/api/workspace/jobs?status=draft")) == 1
    assert len(get(client, auth_headers, "/api/workspace/jobs?status=published")) == 1


# ---------- The dashboard ----------


def cancel_interview(candidate_id: int) -> None:
    """An interview that was cancelled before it started: ended, but never started."""
    with SessionLocal() as db:
        db.add(
            InterviewSession(
                candidate_id=candidate_id,
                scheduled_at=in_hours(-2),
                invite_token=f"cancelled-{candidate_id}",
                invite_expires_at=in_hours(22),
                status="ended",
                ended_at=in_hours(-3),
            )
        )
        db.commit()


def test_the_dashboard_counts_the_whole_pipeline(client, auth_headers):
    job = make_job("Backend Developer")
    best = make_candidate(job, "Maya Rahman", score=80)
    make_candidate(job, "Arif Khan", score=60)
    make_candidate(job, "Tanvir Ahmed", status="uploaded")
    make_interview(best, status="ended")

    body = get(client, auth_headers, "/api/workspace/overview")
    assert body["candidates_total"] == 3
    assert body["waiting_to_screen"] == 1
    assert body["passed_screening"] == 2
    assert body["ready_total"] == 1  # Arif passed and has no interview yet
    assert body["interviews_done"] == 1
    assert [step["label"] for step in body["funnel"]] == [
        "CVs received", "Screened", "Passed screening", "Invited", "Interviewed"
    ]
    assert [step["value"] for step in body["funnel"]] == [3, 2, 2, 1, 1]


def test_a_cancelled_interview_does_not_count_as_held(client, auth_headers):
    job = make_job("Backend Developer")
    cancel_interview(make_candidate(job, "Maya Rahman", score=80))

    body = get(client, auth_headers, "/api/workspace/overview")
    assert body["interviews_done"] == 0
    assert body["funnel"][-1]["value"] == 0
    assert get(client, auth_headers, "/api/workspace/candidates") == []  # back to screened: no longer on the shortlist


def test_the_dashboard_says_what_to_do_next(client, auth_headers):
    job = make_job("Backend Developer")
    make_candidate(job, "Tanvir Ahmed", status="uploaded")

    todo = get(client, auth_headers, "/api/workspace/overview")["todo"]
    assert any("not screened" in item["text"] for item in todo)
    assert all(item["to"].startswith("/") for item in todo)


def test_a_leading_candidate_without_an_interview_is_flagged(client, auth_headers):
    job = make_job("Backend Developer")
    make_candidate(job, "Maya Rahman", score=91)

    todo = get(client, auth_headers, "/api/workspace/overview")["todo"]
    assert any("Maya Rahman" in item["text"] for item in todo)


def test_an_interview_that_did_not_start_is_flagged_not_listed_as_next(client, auth_headers):
    job = make_job("Backend Developer")
    candidate = make_candidate(job, "Maya Rahman", score=82)
    make_interview(candidate, status="scheduled", hours=-3)

    body = get(client, auth_headers, "/api/workspace/overview")
    assert body["upcoming"] == []
    assert body["next_interview"] is None
    flagged = [item for item in body["todo"] if "did not start" in item["text"]]
    assert flagged and flagged[0]["to"] == f"/candidates/{candidate}"


def test_an_interview_nobody_ended_is_flagged(client, auth_headers):
    job = make_job("Backend Developer")
    make_interview(make_candidate(job, "Maya Rahman", score=82), status="live", hours=-5)

    body = get(client, auth_headers, "/api/workspace/overview")
    assert body["upcoming"] == []
    assert any("never ended" in item["text"] for item in body["todo"])


def test_the_dashboard_lists_the_next_interviews(client, auth_headers):
    job = make_job("Backend Developer")
    make_interview(make_candidate(job, "Maya Rahman", score=82), hours=1)
    make_interview(make_candidate(job, "Arif Khan", score=61), hours=5)

    body = get(client, auth_headers, "/api/workspace/overview")
    assert [row["candidate_name"] for row in body["upcoming"]] == ["Maya Rahman", "Arif Khan"]
    assert body["next_interview"]["candidate_name"] == "Maya Rahman"
    assert body["interviews_week"] == 2


def test_each_open_job_shows_its_progress_and_next_step(client, auth_headers):
    waiting = make_job("Backend Developer")
    make_candidate(waiting, "Maya Rahman", score=82)
    make_candidate(waiting, "Tanvir Ahmed", status="uploaded")
    ready = make_job("Data Engineer")
    make_candidate(ready, "Arif Khan", score=61)
    make_job("Product Designer", status="draft")

    jobs = {job["title"]: job for job in get(client, auth_headers, "/api/workspace/overview")["jobs"]}
    assert set(jobs) == {"Backend Developer", "Data Engineer"}  # drafts are not open
    assert jobs["Backend Developer"]["candidates"] == 2
    assert jobs["Backend Developer"]["leader_name"] == "Maya Rahman"
    assert jobs["Backend Developer"]["next_step"] == "Screen 1 CV"
    assert jobs["Data Engineer"]["next_step"] == "Invite Arif Khan"


def test_who_to_invite_is_listed_per_job_best_first(client, auth_headers):
    job = make_job("Backend Developer")
    for name, score in (("Maya Rahman", 90), ("Arif Khan", 80), ("Rafi Islam", 70), ("Zara Noor", 60)):
        make_candidate(job, name, score=score)
    invited = make_candidate(job, "Abir Das", score=95)
    make_interview(invited)

    ready = get(client, auth_headers, "/api/workspace/overview")["ready_to_invite"]
    assert [p["name"] for p in ready] == ["Maya Rahman", "Arif Khan", "Rafi Islam"]  # top 3, no one already invited


def test_recent_interviews_list_only_the_ones_that_took_place(client, auth_headers):
    job = make_job("Backend Developer")
    make_interview(make_candidate(job, "Maya Rahman", score=82), status="ended", lines=3)
    cancel_interview(make_candidate(job, "Arif Khan", score=61))

    recent = get(client, auth_headers, "/api/workspace/overview")["recent_interviews"]
    assert [row["candidate_name"] for row in recent] == ["Maya Rahman"]


def test_an_empty_workspace_answers_without_breaking(client, auth_headers):
    body = get(client, auth_headers, "/api/workspace/overview")
    assert body["candidates_total"] == 0
    assert body["next_interview"] is None
    assert body["jobs"] == []
    assert body["todo"] == []


def test_these_views_need_a_login(client):
    for path in ("candidates", "interviews", "jobs", "overview"):
        assert client.get(f"/api/workspace/{path}").status_code == 401


# ---------- Sorting the interviews page ----------


def test_interviews_can_be_sorted(client, auth_headers):
    from datetime import datetime, timedelta, timezone

    from app.db import SessionLocal
    from app.models import Candidate, CandidateScore, InterviewSession, JobProfile

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        jobs = [JobProfile(title="Backend"), JobProfile(title="Analyst")]
        db.add_all(jobs)
        db.flush()
        people = [("Zara", jobs[0], 70, 3), ("Adnan", jobs[1], 90, 1), ("Mitu", jobs[0], 80, 2)]
        for name, job, score, hours in people:
            c = Candidate(job_profile_id=job.id, name=name, email="x@example.com", cv_filename="cv.pdf", status="screened")
            db.add(c)
            db.flush()
            db.add(CandidateScore(candidate_id=c.id, technical_skills=score, experience=score, qualifications=score, jd_match=score, overall=score, justification={}))
            db.add(InterviewSession(candidate_id=c.id, scheduled_at=now + timedelta(hours=hours), invite_token=f"t-{name}", invite_expires_at=now + timedelta(days=2)))
        db.commit()

    def names(sort):
        rows = client.get("/api/workspace/interviews", params={"sort": sort}, headers=auth_headers).json()
        return [r["candidate_name"] for r in rows]

    assert names("soonest") == ["Adnan", "Mitu", "Zara"]
    assert names("latest") == ["Zara", "Mitu", "Adnan"]
    assert names("candidate") == ["Adnan", "Mitu", "Zara"]
    assert names("score") == ["Adnan", "Mitu", "Zara"]
    assert names("job") == ["Adnan", "Mitu", "Zara"]  # Analyst before Backend, then by time
    rows = client.get("/api/workspace/interviews", headers=auth_headers).json()
    assert rows[0]["overall"] == 90 and rows[0]["duration_minutes"] == 60
