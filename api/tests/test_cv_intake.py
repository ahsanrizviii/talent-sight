from pathlib import Path

from app.settings import settings
from scripts.make_sample_cvs import make_docx, make_pdf
from tests.test_jobs import JOB

CV = [
    "Priya Saha",
    "Email: priya.saha@example.com",
    "SKILLS",
    "Python, FastAPI, PostgreSQL, Docker",
] + ["Built REST APIs."] * 10


def new_job(client, headers) -> int:
    return client.post("/api/jobs", json=JOB, headers=headers).json()["id"]


def upload(client, headers, job_id, *files):
    return client.post(
        f"/api/jobs/{job_id}/candidates",
        files=[("files", f) for f in files],
        headers=headers,
    )


def test_upload_needs_login(client, auth_headers):
    job_id = new_job(client, auth_headers)
    assert upload(client, {}, job_id, ("cv.pdf", make_pdf(CV))).status_code == 401


def test_batch_upload_checks_each_file_on_its_own(client, auth_headers):
    job_id = new_job(client, auth_headers)
    results = upload(
        client,
        auth_headers,
        job_id,
        ("priya.pdf", make_pdf(CV)),
        ("priya.docx", make_docx(CV)),
        ("notes.txt", b"hello"),
        ("virus.pdf", b"MZ\x90\x00 not a pdf"),
        ("empty.docx", b""),
    ).json()
    assert [r["ok"] for r in results] == [True, True, False, False, False]
    assert results[2]["error"] == "Only PDF and DOCX files are accepted."
    assert results[3]["error"] == "The file is not a real PDF file."
    assert results[4]["error"] == "The file is empty."

    candidates = client.get(
        f"/api/jobs/{job_id}/candidates", headers=auth_headers
    ).json()
    assert len(candidates) == 2
    assert {c["status"] for c in candidates} == {"uploaded"}


def test_too_big_file_is_refused(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "cv_max_mb", 1)
    job_id = new_job(client, auth_headers)
    big = make_pdf(CV) + b" " * (1024 * 1024)
    result = upload(client, auth_headers, job_id, ("big.pdf", big)).json()[0]
    assert result == {
        "filename": "big.pdf",
        "ok": False,
        "candidate_id": None,
        "error": "The file is larger than 1 MB.",
    }


def test_folder_names_in_file_names_are_removed(client, auth_headers):
    job_id = new_job(client, auth_headers)
    result = upload(
        client,
        auth_headers,
        job_id,
        ("../../etc/priya.pdf", make_pdf(CV)),
    ).json()[0]
    assert result["filename"] == "priya.pdf"


def test_delete_removes_the_candidate_and_the_file(client, auth_headers):
    job_id = new_job(client, auth_headers)
    candidate_id = upload(
        client, auth_headers, job_id, ("priya.pdf", make_pdf(CV))
    ).json()[0]["candidate_id"]
    stored = list(Path(settings.cv_upload_dir).rglob("*.pdf"))
    assert len(stored) == 1
    assert client.delete(
        f"/api/candidates/{candidate_id}", headers=auth_headers
    ).status_code == 204
    assert client.get(
        f"/api/candidates/{candidate_id}", headers=auth_headers
    ).status_code == 404
    assert not stored[0].exists()