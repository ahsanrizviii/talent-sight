import asyncio
import html
import logging
import sys
from pathlib import Path
from urllib.parse import quote

from mcp import Client, StdioServerParameters
from app.google_form import apply_url
from app.models import JobProfile
from app.settings import settings

log = logging.getLogger("talentsight.blogger")

DEMO_NOTE = "Demo vacancy from the TalentSight training project. This is not a real job opening."


def is_enabled() -> bool:
    return bool(settings.blogger_blog_id)

def blog_url_for(slug: str | None) -> str | None:
    if not slug or not is_enabled() or not settings.blogger_blog_url:
        return None
    return f"{settings.blogger_blog_url.rstrip('/')}/search/label/{quote(slug)}"


def build_post_html(job: JobProfile) -> str:

    def items(values: list[str]) -> str:
        return "".join(f"<li>{html.escape(value)}</li>" for value in values)

    parts = [
        f"<p><em>{html.escape(DEMO_NOTE)}</em></p>",
        f"<p>{html.escape(job.description).replace(chr(10), '<br>')}</p>",
        f"<h3>Required skills</h3><ul>{items(job.required_skills)}</ul>",
    ]
    if job.preferred_skills:
        parts.append(f"<h3>Nice to have</h3><ul>{items(job.preferred_skills)}</ul>")
    if job.qualifications:
        parts.append(f"<h3>Qualifications</h3><ul>{items(job.qualifications)}</ul>")
    parts.append(f"<p>Minimum experience: {job.min_experience_years} years</p>")
    form = apply_url(job.slug)
    if form:
        parts.append(
            f'<p><a href="{html.escape(form)}">Apply with the application form</a> '
            f"(upload your CV as PDF or DOCX).</p>"
        )
    else:
        parts.append(
            f"<p>How to apply: send your CV to "
            f"{html.escape(settings.careers_email)}</p>"
        )
    return "\n".join(parts)


def server_parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_servers.blogger_server"],
        cwd=Path(__file__).resolve().parent.parent,  # the folder that holds the "app" package
        env={
            "BLOGGER_BLOG_ID": settings.blogger_blog_id,
            "GOOGLE_CLIENT_ID": settings.google_client_id,
            "GOOGLE_CLIENT_SECRET": settings.google_client_secret,
            "GOOGLE_REFRESH_TOKEN": settings.google_refresh_token,
        },
    )


async def _call_tool(name: str, arguments: dict) -> str:
    async with Client(server_parameters(), read_timeout_seconds=60) as client:
        result = await client.call_tool(name, arguments)
    text = " ".join(block.text for block in result.content if getattr(block, "text", None))
    if result.is_error:
        raise RuntimeError(text or f"MCP tool {name} failed")
    return text


def call_tool(name: str, arguments: dict) -> str:
    return asyncio.run(_call_tool(name, arguments))


def post_job(job: JobProfile) -> str | None:
    if not is_enabled():
        return None
    try:
        text = call_tool("publish_job", {"title": job.title, "html": build_post_html(job), "label": job.slug})
    except Exception as error:  # posting is an extra: never let it break publishing
        log.warning("blogger post failed", extra={"event": "blogger_failed", "error_type": type(error).__name__})
        return None
    url = text.strip() or blog_url_for(job.slug) or ""
    log.info(f"job posted on blogger, tool said {text!r}, using {url!r}", extra={"event": "blogger_posted", "job_id": job.id})
    return url


def remove_job(slug: str | None) -> None:
    if not slug or not is_enabled():
        return
    try:
        call_tool("remove_job", {"label": slug})
    except Exception as error:
        log.warning("blogger delete failed", extra={"event": "blogger_failed", "error_type": type(error).__name__})
