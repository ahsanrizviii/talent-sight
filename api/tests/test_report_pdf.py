"""Tests for the assessment report as a PDF file (Task 10.2.1). The AI is a fake, as in test_assessments.py."""

from io import BytesIO

from pypdf import PdfReader

from tests.test_assessments import assess, candidate, fake_ai  # noqa: F401  (fake_ai: the AI stays fake here too)


def pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)


def download(client, headers, candidate_id: int):
    return client.get(f"/api/candidates/{candidate_id}/assessment/pdf", headers=headers)


def test_the_report_downloads_as_a_pdf(client, auth_headers):
    candidate_id = candidate()
    assess(client, auth_headers, candidate_id)
    response = download(client, auth_headers, candidate_id)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="assessment-maya-rahman.pdf"'
    assert response.content.startswith(b"%PDF")


def test_the_pdf_holds_the_whole_report_with_its_evidence(client, auth_headers):
    candidate_id = candidate()
    assess(client, auth_headers, candidate_id)
    text = pdf_text(download(client, auth_headers, candidate_id).content)
    for expected in (
        "Candidate assessment: Maya Rahman",
        "Backend Developer",
        "Possible fit",
        "61.6 / 100",
        "Component scores",
        "Explains Python generators clearly. [Q2, R1]",
        "Evidence gaps",
        "Verify next",
        "Requirements: CV and interview side by side",
        "yields values one at a time",
        "Confidential: for the hiring team only",
    ):
        assert expected in text, expected


def test_letters_the_pdf_font_cannot_draw_do_not_break_it(client, auth_headers):
    candidate_id = candidate(name="Maya Rahman আরিফ 王")
    assess(client, auth_headers, candidate_id)
    response = download(client, auth_headers, candidate_id)
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="assessment-maya-rahman.pdf"'
    assert "Maya Rahman" in pdf_text(response.content)


def test_there_is_nothing_to_export_before_the_assessment(client, auth_headers):
    refused = download(client, auth_headers, candidate())
    assert refused.status_code == 400 and refused.json()["detail"] == "There is no finished assessment to export yet."


def test_the_pdf_is_for_interviewers_only(client, auth_headers):
    candidate_id = candidate()
    assess(client, auth_headers, candidate_id)
    assert client.get(f"/api/candidates/{candidate_id}/assessment/pdf").status_code == 401