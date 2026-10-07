import asyncio

from mcp import Client

from app import blogger
from app.mcp_servers import blogger_server
from app.settings import settings
from tests.test_jobs import JOB

BLOG = "https://talentsight.blogspot.com"


def turn_posting_on(monkeypatch) -> list:
    monkeypatch.setattr(settings, "blogger_blog_id", "123")
    monkeypatch.setattr(settings, "blogger_blog_url", BLOG)
    calls = []

    def fake_call_tool(name, arguments):
        calls.append((name, arguments))
        return f"{BLOG}/2026/10/post.html"

    monkeypatch.setattr(blogger, "call_tool", fake_call_tool)
    return calls


def test_publishing_posts_the_job_on_the_blog(client, auth_headers, monkeypatch):
    calls = turn_posting_on(monkeypatch)
    job_id = client.post("/api/jobs", json=JOB, headers=auth_headers).json()["id"]

    published = client.post(f"/api/jobs/{job_id}/publish", headers=auth_headers).json()
    name, arguments = calls[0]
    assert name == "publish_job"
    assert arguments["title"] == JOB["title"]
    assert arguments["label"] == published["slug"]
    assert published["blog_url"] == f"{BLOG}/search/label/{published['slug']}"

    client.post(f"/api/jobs/{job_id}/publish", headers=auth_headers)
    assert len(calls) == 1 

    client.delete(f"/api/jobs/{job_id}", headers=auth_headers)
    assert calls[-1] == ("remove_job", {"label": published["slug"]})


def test_the_post_shows_only_public_fields_safely(client, auth_headers, monkeypatch):
    calls = turn_posting_on(monkeypatch)
    sneaky = {**JOB, "description": "Great role <script>alert(1)</script>"}
    job_id = client.post("/api/jobs", json=sneaky, headers=auth_headers).json()["id"]
    client.post(f"/api/jobs/{job_id}/publish", headers=auth_headers)

    post = calls[0][1]["html"]
    assert "<script>" not in post and "&lt;script&gt;" in post  
    assert "Demo vacancy" in post
    assert settings.careers_email in post
    assert JOB["selection_criteria"] not in post 


def test_a_blogger_failure_still_publishes_on_our_careers_page(client, auth_headers, monkeypatch):
    turn_posting_on(monkeypatch)

    def broken(name, arguments):
        raise RuntimeError("Blogger is down")

    monkeypatch.setattr(blogger, "call_tool", broken)
    job_id = client.post("/api/jobs", json=JOB, headers=auth_headers).json()["id"]
    response = client.post(f"/api/jobs/{job_id}/publish", headers=auth_headers)
    assert response.status_code == 200
    assert client.get(f"/api/public/jobs/{response.json()['slug']}").status_code == 200


def test_nothing_is_posted_when_posting_is_off(client, auth_headers):
    job_id = client.post("/api/jobs", json=JOB, headers=auth_headers).json()["id"]
    published = client.post(f"/api/jobs/{job_id}/publish", headers=auth_headers).json()
    assert published["blog_url"] is None


class FakeResponse:
    def __init__(self, body: dict):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeHttp:

    def __init__(self):
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        if url == blogger_server.TOKEN_URL:
            return FakeResponse({"access_token": "short-lived-token"})
        return FakeResponse({"url": f"{BLOG}/2026/10/post.html"})

    def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return FakeResponse({"items": [{"id": "1"}, {"id": "2"}]})

    def delete(self, url, **kwargs):
        self.requests.append(("DELETE", url, kwargs))
        return FakeResponse({})


def test_mcp_server_publishes_and_removes_posts(monkeypatch):
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        monkeypatch.setenv(name, "test")
    monkeypatch.setenv("BLOGGER_BLOG_ID", "123")
    http = FakeHttp()
    monkeypatch.setattr(blogger_server, "httpx", http)

    async def use_the_tools():
        async with Client(blogger_server.server) as client:  
            tools = {tool.name for tool in (await client.list_tools()).tools}
            posted = await client.call_tool("publish_job", {"title": "QA", "html": "<p>Hi</p>", "label": "qa-1"})
            removed = await client.call_tool("remove_job", {"label": "qa-1"})
        return tools, posted, removed

    tools, posted, removed = asyncio.run(use_the_tools())
    assert tools == {"publish_job", "remove_job"}
    assert posted.content[0].text == f"{BLOG}/2026/10/post.html"
    assert removed.content[0].text == "2"

    method, url, request = http.requests[1]  
    assert (method, url) == ("POST", f"{blogger_server.BLOGGER_API}/123/posts")
    assert request["json"]["labels"] == ["qa-1"]
    assert request["headers"] == {"Authorization": "Bearer short-lived-token"}
    assert [r[0] for r in http.requests].count("DELETE") == 2


def test_the_api_can_start_the_mcp_server():

    async def list_tools():
        async with Client(blogger.server_parameters()) as client:
            return {tool.name for tool in (await client.list_tools()).tools}

    assert asyncio.run(list_tools()) == {"publish_job", "remove_job"}
