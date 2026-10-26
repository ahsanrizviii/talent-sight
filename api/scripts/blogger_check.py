"""Checks the Blogger connection step by step, and can post a job that never reached the blog.

    docker compose exec api python -m scripts.blogger_check              checks the connection
    docker compose exec api python -m scripts.blogger_check --post 9     posts job 9 if it is not on the blog
"""

import argparse

import httpx

from app import blogger
from app.db import SessionLocal
from app.models import JobProfile
from app.settings import settings

API = "https://www.googleapis.com/blogger/v3/blogs"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Blogger posting.")
    parser.add_argument("--post", type=int, metavar="JOB_ID", help="post this job if it is missing from the blog")
    args = parser.parse_args()

    for name in ("blogger_blog_id", "google_client_id", "google_client_secret", "google_refresh_token", "blogger_blog_url"):
        print(f"{name.upper()}: {'set' if getattr(settings, name) else 'EMPTY'}")
    if not blogger.is_enabled():
        print("FAILED: BLOGGER_BLOG_ID is empty, so posting is switched off.")
        return 1

    token = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": settings.google_refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    body = token.json()
    if token.status_code != 200:
        print(f"FAILED at the Google login: {token.status_code} {body.get('error')} - {body.get('error_description')}")
        return 1
    print("Google login: OK")
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    blog = httpx.get(f"{API}/{settings.blogger_blog_id}", headers=headers, timeout=30)
    if blog.status_code != 200:
        print(f"FAILED at the blog: {blog.status_code} {blog.text[:300]}")
        return 1
    print(f"Blog: OK ({blog.json().get('name')})")

    if args.post is None:
        print("Everything works. If a job is missing from the blog, run again with --post <job number>.")
        return 0

    with SessionLocal() as db:
        job = db.get(JobProfile, args.post)
        if job is None or not job.slug:
            print(f"There is no published job {args.post}.")
            return 1
        found = httpx.get(
            f"{API}/{settings.blogger_blog_id}/posts",
            headers=headers,
            params={"labels": job.slug, "fetchBodies": "false"},
            timeout=30,
        )
        if found.json().get("items"):
            print(f"Job {job.id} is already on the blog. Nothing posted.")
            return 0
        try:
            text = blogger.call_tool("publish_job", {"title": job.title, "html": blogger.build_post_html(job), "label": job.slug})
        except Exception as error:
            print(f"FAILED while posting: {type(error).__name__}: {str(error)[:400]}")
            return 1
        print(f"Posted: {text}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())