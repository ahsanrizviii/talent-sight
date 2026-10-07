import os

import httpx
from mcp.server.mcpserver import MCPServer

server = MCPServer("blogger", instructions="Publishes and removes job posts on the TalentSight Blogger blog.")

BLOGGER_API = "https://www.googleapis.com/blogger/v3/blogs"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TIMEOUT = 30  


def auth_header() -> dict[str, str]:

    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def posts_url() -> str:
    return f"{BLOGGER_API}/{os.environ['BLOGGER_BLOG_ID']}/posts"


@server.tool()
def publish_job(title: str, html: str, label: str) -> str:

    response = httpx.post(
        posts_url(),
        headers=auth_header(),
        json={"title": title, "content": html, "labels": [label]},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["url"]


@server.tool()
def remove_job(label: str) -> int:
    """Deletes every post that has this label and returns how many were deleted."""
    headers = auth_header()
    found = httpx.get(posts_url(), headers=headers, params={"labels": label, "fetchBodies": "false"}, timeout=TIMEOUT)
    found.raise_for_status()
    posts = found.json().get("items", [])
    for post in posts:
        httpx.delete(f"{posts_url()}/{post['id']}", headers=headers, timeout=TIMEOUT).raise_for_status()
    return len(posts)


if __name__ == "__main__":
    server.run()  
