"""Tests for the input validation, log and error review (Task 11.1.2: N8, N12, N22)."""

import json
import logging

import pytest

from app.logging_setup import JsonFormatter, hide_secrets
from app.main import app
from tests.test_jobs import JOB

TOKEN = "Zk3Q9xVb-7Lm_2pRtYwA5sCdE1fGhJkL0nOq"


# ---------- Logs: no invite tokens, no personal data (N22) ----------


@pytest.mark.parametrize(
    ("path", "shown"),
    [
        (f"/api/invite/{TOKEN}", "/api/invite/***"),
        (f"/api/invite/{TOKEN}/join", "/api/invite/***/join"),
        (f"/api/ws/invite/{TOKEN}/audio", "/api/ws/invite/***/audio"),
        (f"/join/{TOKEN}?from=mail", "/join/***?from=mail"),
        ("/api/jobs/3/candidates", "/api/jobs/3/candidates"),  # nothing secret: left as it is
    ],
)
def test_invite_tokens_are_hidden_in_paths(path, shown):
    assert hide_secrets(path) == shown


def test_the_web_servers_request_lines_are_masked():
    # This is how uvicorn logs one request: client, method, path, HTTP version, status.
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("172.18.0.5:50112", "POST", f"/api/invite/{TOKEN}/join", "1.1", 200), None,
    )
    logging.getLogger("uvicorn.access").filter(record)
    assert TOKEN not in record.getMessage()
    assert "/api/invite/***/join" in record.getMessage()


def test_a_json_log_line_keeps_only_safe_fields():
    record = logging.LogRecord("talentsight", logging.INFO, __file__, 1, f"opened /join/{TOKEN}", None, None)
    record.event, record.candidate_id = "test", 7
    record.email, record.cv_text = "maya@example.com", "Maya Rahman, 12 Road, Dhaka"  # must never be written
    line = JsonFormatter().format(record)
    entry = json.loads(line)
    assert entry["message"] == "opened /join/***" and entry["candidate_id"] == 7
    assert "maya@example.com" not in line and "Maya Rahman" not in line and TOKEN not in line


def test_an_unexpected_error_on_a_candidate_link_logs_no_token(client, caplog):
    def crash(invite_token: str):
        raise RuntimeError("secret detail")

    app.add_api_route("/api/test/invite/{invite_token}", crash)
    response = client.get(f"/api/test/invite/{TOKEN}")
    assert response.json() == {"detail": "Something went wrong. Please try again."}  # N12
    # Our own log lines (the test client's request log is not part of the app).
    lines = [JsonFormatter().format(record) for record in caplog.records if record.name.startswith("talentsight")]
    crash_line = next(json.loads(line) for line in lines if '"unhandled_error"' in line)
    assert crash_line["path"] == "/api/test/invite/***" and crash_line["error_type"] == "RuntimeError"
    assert not any(TOKEN in line or "secret detail" in line for line in lines)


# ---------- Inputs (N8) ----------


def test_a_skill_must_be_a_short_item(client, auth_headers):
    pasted_paragraph = {**JOB, "required_skills": ["Python", "x" * 201]}
    assert client.post("/api/jobs", json=pasted_paragraph, headers=auth_headers).status_code == 422
    empty_item = {**JOB, "preferred_skills": [""]}
    assert client.post("/api/jobs", json=empty_item, headers=auth_headers).status_code == 422


def test_company_details_have_limits(client, auth_headers):
    too_long = {"company_name": "A" * 121}
    assert client.put("/api/company", json=too_long, headers=auth_headers).status_code == 422
    assert client.put("/api/company", json={"company_name": ""}, headers=auth_headers).status_code == 422


def test_the_test_mail_address_has_limits(client, auth_headers):
    assert client.post("/api/setup/test-email", json={"to": "x" * 300}, headers=auth_headers).status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "/api/workspace/candidates?stage=hired",
        "/api/workspace/candidates?source=linkedin",
        "/api/workspace/candidates?sort=salary",
        "/api/workspace/interviews?state=tomorrow",
        "/api/workspace/interviews?sort=random",
        "/api/workspace/jobs?status=archived",
    ],
)
def test_list_filters_only_take_known_values(client, auth_headers, url):
    assert client.get(url, headers=auth_headers).status_code == 422