"""Tests for applications through the Google Form. Google itself is replaced by fakes."""
from app import blogger, google_api, google_form
from app.models import JobProfile
from app.settings import settings
from scripts.make_sample_cvs import make_pdf
from tests.test_jobs import JOB

FORM_URL = "https://docs.google.com/forms/d/e/FORM/viewform"
CV = [
    "Priya Saha",
    "SKILLS",
    "Python, FastAPI, PostgreSQL",
] + ["Built REST APIs."] * 10


def response(response_id: str, job_code: str, *file_ids: str) -> dict:
    """One form response, in the shape the Google Forms API sends it."""
    return {
        "responseId": response_id,
        "respondentEmail": f"{response_id}@example.com",
        "answers": {
            "q1": {
                "questionId": "q1",
                "textAnswers": {"answers": [{"value": job_code}]},
            },
            "q2": {
                "questionId": "q2",
                "fileUploadAnswers": {
                    "answers": [
                        {"fileId": f, "fileName": f"{f}.pdf"} for f in file_ids
                    ]
                },
            },
        },
    }


def turn_form_on(monkeypatch, responses: list[dict], files: dict[str, bytes]):
    monkeypatch.setattr(settings, "google_form_id", "FORM-ID")
    monkeypatch.setattr(settings, "google_form_url", FORM_URL)
    monkeypatch.setattr(settings, "google_form_job_field", "entry.111")
    monkeypatch.setattr(settings, "google_refresh_token", "test")
    monkeypatch.setattr(google_api, "form_responses", lambda form_id: responses)
    monkeypatch.setattr(
        google_api,
        "download_file",
        lambda file_id, max_bytes: (f"{file_id}.pdf", files[file_id]),
    )


def published_job(client, headers) -> dict:
    job_id = client.post("/api/jobs", json=JOB, headers=headers).json()["id"]
    return client.post(f"/api/jobs/{job_id}/publish", headers=headers).json()


def test_apply_link_has_the_job_code_filled_in(monkeypatch):
    assert google_form.apply_url("backend-developer-7") is None  # no form set up

    monkeypatch.setattr(settings, "google_form_url", FORM_URL)
    monkeypatch.setattr(settings, "google_form_job_field", "entry.111")
    assert google_form.apply_url("backend-developer-7") == (
        f"{FORM_URL}?usp=pp_url&entry.111=backend-developer-7"
    )


def test_job_post_and_blog_post_link_to_the_form(client, auth_headers, monkeypatch):
    turn_form_on(monkeypatch, [], {})
    job = published_job(client, auth_headers)

    public = client.get(f"/api/public/jobs/{job['slug']}").json()
    assert public["apply_url"].endswith(f"entry.111={job['slug']}")

    post = blogger.build_post_html(JobProfile(**{**JOB, "slug": job["slug"]}))
    assert "Apply with the application form" in post


def test_import_takes_only_this_jobs_cvs_and_only_once(client, auth_headers, monkeypatch):
    responses = []
    turn_form_on(
        monkeypatch,
        responses,
        {"f1": make_pdf(CV), "f2": make_pdf(CV), "f3": b"not a pdf"},
    )
    job = published_job(client, auth_headers)
    responses += [
        response("r1", job["slug"], "f1"),
        response("r2", "another-job-9", "f2"),
        response("r3", job["slug"], "f3"),
    ]

    first = client.post(
        f"/api/jobs/{job['id']}/candidates/import", headers=auth_headers
    ).json()
    assert first["imported"] == 1 and first["skipped"] == 0
    assert first["failed"] == [
        {"filename": "f3.pdf", "error": "The file is not a real PDF file."}
    ]

    candidates = client.get(
        f"/api/jobs/{job['id']}/candidates", headers=auth_headers
    ).json()
    assert [(c["source"], c["email"]) for c in candidates] == [
        ("google_form", "r1@example.com")
    ]

    again = client.post(
        f"/api/jobs/{job['id']}/candidates/import", headers=auth_headers
    ).json()
    # never imported twice
    assert again["imported"] == 0 and again["skipped"] == 1


def test_import_needs_the_form_and_a_published_job(client, auth_headers, monkeypatch):
    job_id = client.post("/api/jobs", json=JOB, headers=auth_headers).json()["id"]

    not_set_up = client.post(
        f"/api/jobs/{job_id}/candidates/import", headers=auth_headers
    )
    assert not_set_up.status_code == 400

    turn_form_on(monkeypatch, [], {})
    draft = client.post(
        f"/api/jobs/{job_id}/candidates/import", headers=auth_headers
    )
    assert draft.json()["detail"] == (
        "Publish the job first: applicants need its link."
    )


def test_google_failure_is_a_clear_error(client, auth_headers, monkeypatch):
    turn_form_on(monkeypatch, [], {})

    def broken(form_id):
        raise google_api.GoogleError(
            "Google sign-in failed. The refresh token may have expired."
        )

    monkeypatch.setattr(google_api, "form_responses", broken)
    job = published_job(client, auth_headers)

    answer = client.post(
        f"/api/jobs/{job['id']}/candidates/import", headers=auth_headers
    )
    assert answer.status_code == 502
    assert "refresh token" in answer.json()["detail"]