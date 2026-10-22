"""Tests for what the onboarding tab says is on file before the check starts (Task 13.5.3).

The face reader is the fake from test_identity.py, so no real face model is used.
"""

from tests.test_identity import consent, enrolled, fake_faces, live_interview  # noqa: F401  (fake_faces is a fixture)


def state(client, headers, candidate_id: int) -> dict:
    return client.get(f"/api/candidates/{candidate_id}/onboarding-check", headers=headers).json()


def test_the_tab_says_what_face_data_is_on_file(client, auth_headers):
    candidate_id = enrolled(client)
    found = state(client, auth_headers, candidate_id)
    assert found["templates_on_file"] == 3
    assert found["templates_taken_at"] and found["templates_expire_at"] and found["templates_interview_at"]
    assert found["consent"] is True and found["check"] is None


def test_a_candidate_who_said_no_has_nothing_on_file_and_the_reason_is_known(client, auth_headers):
    _, token, candidate_id = live_interview()
    consent(client, token, answer=False)
    found = state(client, auth_headers, candidate_id)
    assert found["templates_on_file"] == 0 and found["consent"] is False
    assert found["templates_taken_at"] is None


def test_before_any_interview_nothing_is_on_file(client, auth_headers):
    _, _, candidate_id = live_interview()
    found = state(client, auth_headers, candidate_id)
    assert found["interview_held"] is False and found["consent"] is None and found["templates_on_file"] == 0
