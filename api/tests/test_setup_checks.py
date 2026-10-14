"""Tests for the setup check page: it must tell the truth about what is and is not working."""

import smtplib

import httpx
import pytest

from app import calendar_events, readiness
from app.settings import settings


def by_key(checks: list[dict]) -> dict:
    return {check["key"]: check for check in checks}


@pytest.fixture
def production_like(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_user", "hiring@example.com")
    monkeypatch.setattr(settings, "smtp_password", "pw")
    monkeypatch.setattr(settings, "public_base_url", "https://hiring.example.com")
    monkeypatch.setattr(settings, "livekit_url", "wss://example.livekit.cloud")


def test_the_page_needs_a_login(client):
    assert client.get("/api/setup/checks").status_code == 401
    assert client.post("/api/setup/test-email", json={"to": "a@b.com"}).status_code == 401


def test_a_laptop_setup_fails_the_checks_that_matter(client, auth_headers, monkeypatch):
    # Pin the laptop values, so the test gives the same result on every machine.
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:8080")
    monkeypatch.setattr(settings, "livekit_url", "ws://localhost:7880")
    checks = by_key(client.get("/api/setup/checks?probe=false", headers=auth_headers).json())
    assert checks["email"]["ok"] is False  # no SMTP_HOST in tests
    assert checks["link"]["ok"] is False and "https" in checks["link"]["detail"]
    assert checks["video"]["ok"] is False
    assert checks["link"]["fix"]  # every failure says what to change


def test_localhost_is_refused_even_over_https(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://localhost:8080")
    result = readiness.check_public_link(probe=False)
    assert result["ok"] is False and "this computer" in result["detail"]


def test_a_real_address_passes_without_probing(client, auth_headers, production_like):
    checks = by_key(client.get("/api/setup/checks?probe=false", headers=auth_headers).json())
    assert checks["email"]["ok"] and checks["link"]["ok"] and checks["video"]["ok"]


def test_probing_catches_a_tunnel_that_is_down(monkeypatch, production_like):
    def down(*args, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "get", down)
    result = readiness.check_public_link(probe=True)
    assert result["ok"] is False and "did not answer" in result["detail"]


def test_probing_passes_when_the_site_answers(monkeypatch, production_like):
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: httpx.Response(200, json={"status": "ok"}))
    assert readiness.check_public_link(probe=True)["ok"] is True
    assert readiness.check_video(probe=True)["ok"] is True


def test_probing_a_site_that_answers_with_an_error_fails_the_link(monkeypatch, production_like):
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: httpx.Response(502))
    assert readiness.check_public_link(probe=True)["ok"] is False


def test_probing_catches_a_wrong_mail_password(monkeypatch, production_like):
    class Refuses:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self, context=None):
            pass

        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"no")

    monkeypatch.setattr(smtplib, "SMTP", Refuses)
    result = readiness.check_email(probe=True)
    assert result["ok"] is False and "refused the login" in result["detail"]


def test_calendar_is_optional_and_says_how_to_connect(client, auth_headers):
    check = by_key(client.get("/api/setup/checks?probe=false", headers=auth_headers).json())["calendar"]
    assert check["ok"] is False and check["optional"] is True
    assert "GOOGLE_CALENDAR_ID" in check["fix"]


def test_calendar_probe_reports_a_missing_permission(monkeypatch):
    monkeypatch.setattr(settings, "google_calendar_id", "primary")
    monkeypatch.setattr(settings, "google_refresh_token", "token")
    monkeypatch.setattr(calendar_events, "auth_header", lambda: {})
    monkeypatch.setattr(httpx, "request", lambda *a, **k: httpx.Response(403, json={}))
    result = readiness.check_calendar(probe=True)
    assert result["ok"] is False and "calendar.events" in result["detail"]


def test_the_test_email_goes_to_the_address_given(client, auth_headers, production_like, monkeypatch):
    sent = []

    class Collects:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self, context=None):
            pass

        def login(self, user, password):
            pass

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr(smtplib, "SMTP", Collects)
    body = client.post("/api/setup/test-email", json={"to": "hr.person@example.com"}, headers=auth_headers).json()
    assert body == {"sent": True, "error": ""}
    assert sent[0]["To"] == "hr.person@example.com"


def test_the_test_email_refuses_a_wrong_address_and_missing_setup(client, auth_headers, production_like):
    bad = client.post("/api/setup/test-email", json={"to": "not an address"}, headers=auth_headers).json()
    assert bad["sent"] is False and "looks wrong" in bad["error"]


def test_the_test_email_without_a_mail_server_says_so(client, auth_headers):
    body = client.post("/api/setup/test-email", json={"to": "a@b.com"}, headers=auth_headers).json()
    assert body["sent"] is False and "not set up" in body["error"]
