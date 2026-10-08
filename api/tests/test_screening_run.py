
from app.db import SessionLocal
from app.llm import LLMUnavailable
from app.models import ScreeningRun
from app.screening import mark_interrupted_runs
from scripts.make_sample_cvs import make_pdf
from tests.fakes import ALL_MET, GOOD_PROFILE, NO_PYTHON, use_fake_llm
from tests.test_jobs import JOB

CV = [
    "Priya Saha",
    "SKILLS",
    "Python, FastAPI, PostgreSQL",
] + ["Built REST APIs."] * 10


def job_with_cvs(client, headers, count: int = 1) -> int:
    job_id = client.post("/api/jobs", json=JOB, headers=headers).json()["id"]
    files = [("files", (f"cv{i}.pdf", make_pdf(CV))) for i in range(count)]
    client.post(f"/api/jobs/{job_id}/candidates", files=files, headers=headers)
    return job_id


def screen(client, headers, job_id: int) -> list[dict]:
    started = client.post(f"/api/jobs/{job_id}/screening", headers=headers)
    assert started.status_code == 202
    # TestClient runs background tasks before it returns, so the run is finished here.
    return client.get(f"/api/jobs/{job_id}/candidates", headers=headers).json()


def test_screened_candidate_is_saved_with_profile_and_verdicts(
    client, auth_headers, monkeypatch
):
    use_fake_llm(monkeypatch, [GOOD_PROFILE], [ALL_MET])
    candidate = screen(client, auth_headers, job_with_cvs(client, auth_headers))[0]
    assert (candidate["status"], candidate["name"], candidate["met"]) == (
        "screened",
        "Priya Saha",
        5,
    )

    detail = client.get(
        f"/api/candidates/{candidate['id']}", headers=auth_headers
    ).json()
    assert detail["profile"]["skills"] == ["Python", "FastAPI", "PostgreSQL"]
    assert [v["mandatory"] for v in detail["verdicts"]] == [
        True,
        True,
        True,
        True,
        False,
    ]


def test_excluded_candidate_is_kept_with_the_reason(client, auth_headers, monkeypatch):
    use_fake_llm(monkeypatch, [GOOD_PROFILE], [NO_PYTHON])
    candidate = screen(client, auth_headers, job_with_cvs(client, auth_headers))[0]
    assert candidate["status"] == "excluded"
    assert candidate["exclusion_reason"] == "Mandatory requirement not met: Python"


def test_one_failed_cv_does_not_stop_the_batch(client, auth_headers, monkeypatch):
    use_fake_llm(
        monkeypatch,
        [
            LLMUnavailable("The AI service is not available right now."),
            GOOD_PROFILE,
        ],
        [ALL_MET],
    )
    job_id = job_with_cvs(client, auth_headers, count=2)
    assert sorted(c["status"] for c in screen(client, auth_headers, job_id)) == [
        "failed",
        "screened",
    ]

    run = client.get(f"/api/jobs/{job_id}/screening", headers=auth_headers).json()
    assert (run["status"], run["total"], run["done"], run["failed"]) == (
        "done",
        2,
        2,
        1,
    )
    assert run["seconds"] is not None


def test_screening_again_only_when_asked(client, auth_headers, monkeypatch):
    use_fake_llm(monkeypatch, [GOOD_PROFILE, GOOD_PROFILE], [ALL_MET, NO_PYTHON])
    job_id = job_with_cvs(client, auth_headers)
    screen(client, auth_headers, job_id)

    nothing_new = client.post(f"/api/jobs/{job_id}/screening", headers=auth_headers)
    assert nothing_new.json()["detail"] == "There are no CVs to screen."

    client.post(
        f"/api/jobs/{job_id}/screening?again=true", headers=auth_headers
    )
    assert client.get(
        f"/api/jobs/{job_id}/candidates", headers=auth_headers
    ).json()[0]["status"] == "excluded"


def test_one_run_at_a_time_and_restart_safety(client, auth_headers):
    job_id = job_with_cvs(client, auth_headers)
    with SessionLocal() as db:
        db.add(ScreeningRun(job_profile_id=job_id, total=1))
        db.commit()

    assert (
        client.post(f"/api/jobs/{job_id}/screening", headers=auth_headers).status_code
        == 409
    )

    mark_interrupted_runs()
    assert (
        client.get(f"/api/jobs/{job_id}/screening", headers=auth_headers).json()[
            "status"
        ]
        == "interrupted"
    )


def test_screening_needs_login(client, auth_headers):
    job_id = job_with_cvs(client, auth_headers)
    assert client.post(f"/api/jobs/{job_id}/screening").status_code == 401