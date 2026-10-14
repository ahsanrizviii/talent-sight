"""Keeping the "Write a job with AI" chats (UI refresh).

The team asked to be able to read back how each job was written. These tests use the same
fake language model as the agent tests, so no AI call is ever made.
"""

from tests.test_jd_agent import COMPLETE_BRIEF, GOOD_DRAFT, INCOMPLETE_BRIEF, reply, start, use_fake_llm


def history(client, headers, thread_id: str) -> dict:
    response = client.get(f"/api/jd-chat/{thread_id}/history", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_finished_chat_is_kept_with_both_sides_of_the_conversation(client, auth_headers, monkeypatch):
    use_fake_llm(monkeypatch, [COMPLETE_BRIEF], [GOOD_DRAFT])
    chat = start(client, auth_headers, "Mid-level Python backend developer, 3 years, SQL")
    done = reply(client, auth_headers, chat, approve=True)

    kept = history(client, auth_headers, chat["thread_id"])
    assert kept["status"] == "done"
    assert kept["job_id"] == done["job_id"]
    assert kept["brief"].startswith("Mid-level Python backend developer")

    said = [(line["role"], line["text"]) for line in kept["lines"]]
    assert said[0][0] == "recruiter"
    assert said[0][1].startswith("Mid-level Python backend developer")
    assert said[1][0] == "assistant"
    assert "draft" in said[1][1].lower()
    assert "Saved the job profile" in said[-1][1]


def test_the_questions_the_ai_asked_are_kept_too(client, auth_headers, monkeypatch):
    use_fake_llm(monkeypatch, [INCOMPLETE_BRIEF, COMPLETE_BRIEF], [GOOD_DRAFT])
    chat = start(client, auth_headers, "We need a backend developer")
    reply(client, auth_headers, chat, text="3 years, Python and SQL")

    lines = history(client, auth_headers, chat["thread_id"])["lines"]
    assert "How many years of experience?" in lines[1]["text"]
    assert lines[2]["text"] == "3 years, Python and SQL"


def test_the_chat_is_named_after_the_job_once_there_is_a_draft(client, auth_headers, monkeypatch):
    use_fake_llm(monkeypatch, [COMPLETE_BRIEF], [GOOD_DRAFT])
    chat = start(client, auth_headers, "Mid-level Python backend developer, 3 years, SQL")

    assert history(client, auth_headers, chat["thread_id"])["title"] == "Mid-level Backend Developer"


def test_every_chat_is_listed_newest_first_and_can_be_found_by_job(client, auth_headers, monkeypatch):
    use_fake_llm(monkeypatch, [COMPLETE_BRIEF, COMPLETE_BRIEF], [GOOD_DRAFT, GOOD_DRAFT])
    first = start(client, auth_headers, "Mid-level Python backend developer, 3 years, SQL")
    done = reply(client, auth_headers, first, approve=True)
    start(client, auth_headers, "A second role: data engineer with Python and SQL")

    listed = client.get("/api/jd-chat", headers=auth_headers).json()
    assert len(listed) == 2
    assert all(row["messages"] >= 2 for row in listed)

    for_job = client.get(f"/api/jd-chat?job_id={done['job_id']}", headers=auth_headers).json()
    assert [row["thread_id"] for row in for_job] == [first["thread_id"]]


def test_a_failed_chat_keeps_the_reason(client, auth_headers, monkeypatch):
    from app.llm import LLMUnavailable

    use_fake_llm(monkeypatch, [LLMUnavailable("The AI service is not available right now. Please try again.")], [])
    chat = start(client, auth_headers, "Python backend developer, 3 years, SQL")

    kept = history(client, auth_headers, chat["thread_id"])
    assert kept["status"] == "failed"
    assert "not available" in kept["lines"][-1]["text"]


def test_a_chat_that_was_never_kept_answers_404(client, auth_headers):
    assert client.get("/api/jd-chat/not-a-real-thread/history", headers=auth_headers).status_code == 404


def test_the_history_needs_a_login(client):
    assert client.get("/api/jd-chat").status_code == 401
