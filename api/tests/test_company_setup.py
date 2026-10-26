"""Tests for setting up the company in the first sign-up: the sign-up form also asks for the company's
name and contact e-mail, but only while the company is not set up yet."""

import pytest

from app import company_profile
from app.db import SessionLocal
from app.settings import settings

ACCOUNT = {"full_name": "Ayesha Rahman", "email": "ayesha@example.com", "password": "a-strong-password-1", "company_code": "join-us"}
COMPANY = {"company_name": "WellDev", "contact_email": "hr@welldev.example"}


@pytest.fixture
def signup_open(monkeypatch):
    monkeypatch.setattr(settings, "signup_code", ACCOUNT["company_code"])
    monkeypatch.setattr(settings, "signup_email_domains", "")


def company():
    with SessionLocal() as db:
        return company_profile.current(db)


def test_the_sign_up_form_is_told_to_ask_for_the_company_on_a_new_install(client, signup_open):
    options = client.get("/api/auth/options").json()
    assert options["company_setup_needed"] is True
    assert "company" not in options  # a yes or no only: the name itself is never public


def test_the_first_sign_up_sets_up_the_company(client, signup_open):
    response = client.post("/api/auth/signup", json={**ACCOUNT, **COMPANY})
    assert response.status_code == 201
    details = company()
    assert (details.name, details.contact_email) == ("WellDev", "hr@welldev.example")
    assert details.sender_name == "WellDev Hiring"  # what candidates see in "From"
    assert client.get("/api/auth/options").json()["company_setup_needed"] is False
    token = response.json()["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["company"] == "WellDev"


def test_the_first_sign_up_needs_the_company_name(client, signup_open):
    response = client.post("/api/auth/signup", json=ACCOUNT)
    assert response.status_code == 400
    assert "company's name" in response.json()["detail"]
    # Nothing half-done: no account was made, so the same person can simply try again.
    assert client.post("/api/auth/signup", json={**ACCOUNT, **COMPANY}).status_code == 201


def test_the_first_sign_up_needs_a_contact_email(client, signup_open):
    response = client.post("/api/auth/signup", json={**ACCOUNT, "company_name": "WellDev"})
    assert response.status_code == 400
    assert "contact e-mail" in response.json()["detail"]


def test_a_wrong_contact_address_is_refused(client, signup_open):
    response = client.post("/api/auth/signup", json={**ACCOUNT, **COMPANY, "contact_email": "not-an-address"})
    assert response.status_code == 400
    assert "looks wrong" in response.json()["detail"]


def test_a_later_sign_up_cannot_change_the_company(client, signup_open):
    client.post("/api/auth/signup", json={**ACCOUNT, **COMPANY})
    second = {**ACCOUNT, "email": "rafi@example.com", "full_name": "Rafi Islam", "company_name": "Someone Else"}
    assert client.post("/api/auth/signup", json=second).status_code == 201
    assert company().name == "WellDev"


def test_the_email_preview_is_gone(client, auth_headers):
    assert client.get("/api/company/email-preview", headers=auth_headers).status_code in (404, 405)
