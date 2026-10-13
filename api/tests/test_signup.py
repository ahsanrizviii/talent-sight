"""Opening an account (UI refresh).

Sign-up belongs to the company: it needs the company code from .env, and it can be narrowed
to the company's own e-mail domains. These tests never touch the real .env; they set the
settings themselves.
"""

import pytest

from app.settings import settings

NEW_ACCOUNT = {
    "full_name": "Nadia Hasan",
    "email": "nadia.hasan@bjitgroup.com",
    "password": "a-good-password",
    "company_code": "bjit-hiring-2026",
}


@pytest.fixture
def signup_open(monkeypatch):
    monkeypatch.setattr(settings, "signup_code", NEW_ACCOUNT["company_code"])
    monkeypatch.setattr(settings, "signup_email_domains", "")


def test_the_login_page_is_told_whether_sign_up_is_open(client, signup_open):
    options = client.get("/api/auth/options").json()
    assert options["signup_open"] is True
    assert options["company"] == settings.company_name


def test_sign_up_is_closed_when_no_company_code_is_set(client, monkeypatch):
    monkeypatch.setattr(settings, "signup_code", "")

    assert client.get("/api/auth/options").json()["signup_open"] is False

    response = client.post("/api/auth/signup", json=NEW_ACCOUNT)
    assert response.status_code == 400
    assert "switched off" in response.json()["detail"]


def test_a_new_account_can_be_made_and_used_at_once(client, signup_open):
    response = client.post("/api/auth/signup", json=NEW_ACCOUNT)
    assert response.status_code == 201

    token = response.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["email"] == NEW_ACCOUNT["email"]
    assert me["name"] == "Nadia Hasan"

    # ...and the password works on the normal login form too
    again = client.post(
        "/api/auth/login",
        json={"email": NEW_ACCOUNT["email"], "password": NEW_ACCOUNT["password"]},
    )
    assert again.status_code == 200


def test_the_wrong_company_code_is_refused(client, signup_open):
    response = client.post("/api/auth/signup", json={**NEW_ACCOUNT, "company_code": "guessed-it"})
    assert response.status_code == 400
    assert "company code" in response.json()["detail"]


def test_an_address_outside_the_company_is_refused(client, signup_open, monkeypatch):
    monkeypatch.setattr(settings, "signup_email_domains", "bjitgroup.com")

    response = client.post("/api/auth/signup", json={**NEW_ACCOUNT, "email": "someone@example.com"})
    assert response.status_code == 400
    assert "work e-mail" in response.json()["detail"]

    assert client.post("/api/auth/signup", json=NEW_ACCOUNT).status_code == 201


def test_a_short_password_is_refused(client, signup_open):
    response = client.post("/api/auth/signup", json={**NEW_ACCOUNT, "password": "short"})
    assert response.status_code == 400
    assert "8 characters" in response.json()["detail"]


def test_the_same_address_cannot_sign_up_twice(client, signup_open):
    assert client.post("/api/auth/signup", json=NEW_ACCOUNT).status_code == 201

    response = client.post("/api/auth/signup", json={**NEW_ACCOUNT, "full_name": "Someone Else"})
    assert response.status_code == 400
    assert "already an account" in response.json()["detail"]


def test_an_account_made_before_sign_up_existed_still_has_a_name(client, auth_headers):
    """The seeded interviewer has no profile row. The e-mail name is used instead of an empty box."""
    me = client.get("/api/auth/me", headers=auth_headers).json()
    assert me["name"]
    assert me["name"] == settings.seed_interviewer_email.split("@")[0]
