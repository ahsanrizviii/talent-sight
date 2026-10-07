JOB = {
    "title": "Mid-level Backend Developer",
    "description": "About the role ...",
    "required_skills": ["Python", "SQL"],
    "preferred_skills": ["Docker"],
    "qualifications": ["Bachelor's degree in Computer Science or equivalent experience"],
    "min_experience_years": 3,
    "selection_criteria": "Strong Python and database skills.",
    "weights": {
        "technical_skills": 40,
        "experience": 30,
        "qualifications": 15,
        "jd_match": 15,
    },
}


def test_jobs_need_login(client):
    assert client.get("/api/jobs").status_code == 401


def test_create_list_update_and_delete_a_job(client, auth_headers):
    created = client.post("/api/jobs", json=JOB, headers=auth_headers)
    assert created.status_code == 201
    job_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    assert len(client.get("/api/jobs", headers=auth_headers).json()) == 1

    changed = {**JOB, "title": "Senior Backend Developer", "min_experience_years": 5}
    updated = client.put(f"/api/jobs/{job_id}", json=changed, headers=auth_headers)
    assert updated.json()["title"] == "Senior Backend Developer"

    assert client.delete(f"/api/jobs/{job_id}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/jobs/{job_id}", headers=auth_headers).status_code == 404


def test_several_job_profiles_at_once(client, auth_headers):
    for title in ("Junior QA Engineer", "Senior Data Engineer", "Mid-level Frontend Developer"):
        client.post("/api/jobs", json={**JOB, "title": title}, headers=auth_headers)
    assert len(client.get("/api/jobs", headers=auth_headers).json()) == 3  


def test_weights_must_add_up_to_100(client, auth_headers):
    bad = {
        **JOB,
        "weights": {
            "technical_skills": 50,
            "experience": 30,
            "qualifications": 15,
            "jd_match": 15,
        },
    }
    response = client.post("/api/jobs", json=bad, headers=auth_headers)
    assert response.status_code == 422
    assert "add up to 100" in response.text


def test_at_least_one_required_skill(client, auth_headers):
    response = client.post(
        "/api/jobs",
        json={**JOB, "required_skills": []},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_published_job_is_public_without_weights(client, auth_headers):
    job_id = client.post("/api/jobs", json=JOB, headers=auth_headers).json()["id"]
    published = client.post(
        f"/api/jobs/{job_id}/publish",
        headers=auth_headers,
    ).json()
    assert published["slug"] == f"mid-level-backend-developer-{job_id}"

    public = client.get(f"/api/public/jobs/{published['slug']}")  
    assert public.status_code == 200
    assert public.json()["title"] == JOB["title"]
    assert "weights" not in public.json()
    assert "selection_criteria" not in public.json()


def test_draft_jobs_are_not_public(client, auth_headers):
    client.post("/api/jobs", json=JOB, headers=auth_headers)
    assert client.get("/api/public/jobs").json() == []