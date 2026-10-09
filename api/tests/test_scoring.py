"""Tests for candidate scoring (Module 6). FakeLLM replaces the real language model."""

from tests.fakes import GOOD_PROFILE, scores, use_fake_llm
from tests.test_screening_agent import run_agent, verdicts


def test_passing_candidate_gets_four_scores_with_justifications(monkeypatch):
    use_fake_llm(monkeypatch, [GOOD_PROFILE], [verdicts("met", "met")], [scores(80, 70, 90, 75)])
    result = run_agent()
    assert {d: s["score"] for d, s in result["scores"].items()} == {
        "technical_skills": 80,
        "experience": 70,
        "qualifications": 90,
        "jd_match": 75,
    }
    assert result["scores"]["experience"]["justification"] == "3 years as a backend engineer."


def test_excluded_candidate_is_not_scored(monkeypatch):
    fake = use_fake_llm(monkeypatch, [GOOD_PROFILE], [verdicts("unmet", "met")])
    result = run_agent()
    assert "scores" not in result
    assert len(fake.prompts) == 2  # profile + matching; no scoring call


def test_score_outside_0_to_100_is_asked_again(monkeypatch):
    use_fake_llm(monkeypatch, [GOOD_PROFILE], [verdicts("met", "met")], [scores(150, 70, 90, 75), scores(80, 70, 90, 75)])
    assert run_agent()["scores"]["technical_skills"]["score"] == 80


# ---------- Task 6.1.2: the weighted total ----------

from app.scoring import aggregate  # noqa: E402

WEIGHTS = {"technical_skills": 40, "experience": 30, "qualifications": 15, "jd_match": 15}


def test_total_is_the_weighted_average():
    numbers = {"technical_skills": 80, "experience": 70, "qualifications": 90, "jd_match": 75}
    assert aggregate(numbers, WEIGHTS) == 77.8  # (80*40 + 70*30 + 90*15 + 75*15) / 100 = 77.75
    assert aggregate(numbers, {**WEIGHTS, "technical_skills": 70, "experience": 0}) == 80.8  # 80.75


def test_same_scores_always_give_the_same_total():
    numbers = {"technical_skills": 63, "experience": 71, "qualifications": 88, "jd_match": 59}
    assert len({aggregate(numbers, WEIGHTS) for _ in range(100)}) == 1

# ---------- Task 6.1.3: the ranked shortlist ----------

from scripts.make_sample_cvs import make_pdf  # noqa: E402
from tests.fakes import ALL_MET, NO_PYTHON  # noqa: E402
from tests.test_jobs import JOB  # noqa: E402

CV = ["Priya Saha", "SKILLS", "Python, FastAPI, PostgreSQL"] + ["Built REST APIs."] * 10


def screened_job(client, headers, count: int) -> int:
    job_id = client.post("/api/jobs", json=JOB, headers=headers).json()["id"]
    files = [("files", (f"cv{i}.pdf", make_pdf(CV))) for i in range(count)]
    client.post(f"/api/jobs/{job_id}/candidates", files=files, headers=headers)
    client.post(f"/api/jobs/{job_id}/screening", headers=headers)
    return job_id


def test_candidates_are_ranked_by_total_score(client, auth_headers, monkeypatch):
    use_fake_llm(
        monkeypatch,
        [GOOD_PROFILE] * 3,
        [ALL_MET, ALL_MET, NO_PYTHON],
        [scores(60, 60, 60, 60), scores(90, 80, 90, 85)],
    )
    job_id = screened_job(client, auth_headers, 3)
    rows = client.get(f"/api/jobs/{job_id}/candidates", headers=auth_headers).json()
    assert [(r["status"], r["rank"], r["overall"]) for r in rows] == [
        ("screened", 1, 86.3),  # 86.25
        ("screened", 2, 60.0),
        ("excluded", None, None),  # excluded candidates are not scored
    ]


def test_new_weights_change_the_total_without_asking_the_ai(client, auth_headers, monkeypatch):
    fake = use_fake_llm(monkeypatch, [GOOD_PROFILE], [ALL_MET], [scores(80, 70, 90, 75)])
    job_id = screened_job(client, auth_headers, 1)
    calls = len(fake.prompts)
    new_weights = {"technical_skills": 25, "experience": 25, "qualifications": 25, "jd_match": 25}
    client.put(f"/api/jobs/{job_id}", json={**JOB, "weights": new_weights}, headers=auth_headers)
    row = client.get(f"/api/jobs/{job_id}/candidates", headers=auth_headers).json()[0]
    assert row["overall"] == 78.8  # (80 + 70 + 90 + 75) / 4 = 78.75
    assert len(fake.prompts) == calls  # no new AI call

# ---------- Task 6.2.2: the score breakdown and the original CV ----------


def test_breakdown_shows_each_dimension_with_its_weight(client, auth_headers, monkeypatch):
    use_fake_llm(monkeypatch, [GOOD_PROFILE], [ALL_MET], [scores(80, 70, 90, 75)])
    job_id = screened_job(client, auth_headers, 1)
    candidate_id = client.get(f"/api/jobs/{job_id}/candidates", headers=auth_headers).json()[0]["id"]
    score = client.get(f"/api/candidates/{candidate_id}", headers=auth_headers).json()["score"]
    assert score["overall"] == 77.8
    technical = score["dimensions"][0]
    assert (technical["label"], technical["score"], technical["weight"], technical["contribution"]) == (
        "Technical skills",
        80,
        40,
        32.0,
    )
    assert technical["justification"] == "Python, FastAPI and PostgreSQL in the CV."


def test_original_cv_can_be_opened(client, auth_headers, monkeypatch):
    use_fake_llm(monkeypatch, [GOOD_PROFILE], [ALL_MET])
    job_id = screened_job(client, auth_headers, 1)
    candidate_id = client.get(f"/api/jobs/{job_id}/candidates", headers=auth_headers).json()[0]["id"]
    response = client.get(f"/api/candidates/{candidate_id}/cv", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")