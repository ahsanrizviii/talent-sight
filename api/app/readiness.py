"""The setup check: does everything an interview needs actually work, before anyone is invited?

Each check answers one plain question for the hiring team. With probe=False a check only reads
the settings (instant, used on the dashboard); with probe=True it really connects, which is the
only way to know a candidate on another device can get in.
"""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

from app import calendar_events, invite_mail
from app.settings import settings

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "livekit", "mailpit", "db", "api", "web"}


def _is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in LOCAL_HOSTS or host.endswith(".local") or host.endswith(".internal")


def _result(key: str, label: str, ok: bool, detail: str, fix: str = "", optional: bool = False) -> dict:
    return {"key": key, "label": label, "ok": ok, "detail": detail, "fix": "" if ok else fix, "optional": optional}


def _reaches(url: str, accept=lambda status: True) -> bool:
    try:
        return accept(httpx.get(url, timeout=6, follow_redirects=True).status_code)
    except httpx.HTTPError:
        return False


def check_email(probe: bool) -> dict:
    label = "E-mail to candidates"
    server = invite_mail.mail_server()
    if server is None:
        return _result("email", label, False, "No mail server is set up, so no invitation is sent.",
                       "Set SMTP_HOST, SMTP_USER and SMTP_PASSWORD in .env, then restart.")
    if probe:
        problem = invite_mail.check_login(server)
        if problem:
            return _result("email", label, False, problem, "Fix the SMTP_ lines in .env, then restart.")
    return _result("email", label, True, f"Sending through {server.host} as {invite_mail.organizer_address(server)}.")


def check_public_link(probe: bool) -> dict:
    label = "Candidate link works on any device"
    url = settings.public_base_url.strip()
    if not url.lower().startswith("https://"):
        return _result("link", label, False,
                       "The link is not https. Browsers refuse the camera and microphone on a page that is not https.",
                       "Set PUBLIC_BASE_URL to your public https address.")
    if _is_local(url):
        return _result("link", label, False, "The link points at this computer, so nobody else can open it.",
                       "Set PUBLIC_BASE_URL to your public https address.")
    if probe and not _reaches(f"{url.rstrip('/')}/api/health", lambda status: status == 200):
        return _result("link", label, False, f"{url} did not answer. The tunnel or the domain is down, or it points at another site.",
                       "Start the tunnel (or fix the domain) and check PUBLIC_BASE_URL.")
    return _result("link", label, True, f"Candidates open {url}." + (" It answers from the internet." if probe else ""))


def check_video(probe: bool) -> dict:
    label = "Video call reachable"
    url = settings.livekit_url.strip()
    if not url.lower().startswith("wss://"):
        return _result("video", label, False,
                       "The video server address is not wss://. A candidate's browser cannot connect to it from another device.",
                       "Set LIVEKIT_URL, LIVEKIT_SERVER_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET to a hosted LiveKit project.")
    if _is_local(url):
        return _result("video", label, False, "The video server is on this computer only.",
                       "Use a hosted LiveKit project.")
    if probe and not _reaches("https://" + url[len("wss://"):]):
        return _result("video", label, False, "The video server did not answer.", "Check LIVEKIT_URL and your internet connection.")
    return _result("video", label, True, "Candidates connect straight to the video server." + (" It answers." if probe else ""))


def check_calendar(probe: bool) -> dict:
    label = "Google Calendar"
    if not calendar_events.enabled():
        return _result("calendar", label, False, "Not connected: interviews are not added to a calendar.",
                       "Set GOOGLE_CALENDAR_ID=primary and give the Google token the calendar permission.",
                       optional=True)
    if probe:
        works, detail = calendar_events.check_access()
        return _result("calendar", label, works, detail, "Make a new Google token with the calendar.events permission.", optional=True)
    return _result("calendar", label, True, "Interviews are added to the company calendar.", optional=True)


def check_speech() -> dict:
    ok = bool(settings.assemblyai_api_key.strip())
    return _result("speech", "Live transcript", ok, "Both speakers are transcribed as they talk." if ok else "No speech key, so interviews are not transcribed.",
                   "Set ASSEMBLYAI_API_KEY in .env.", optional=True)


def check_ai() -> dict:
    ok = bool(settings.groq_api_key.strip())
    return _result("ai", "AI for jobs and screening", ok, "A language model key is set." if ok else "No AI key, so jobs cannot be written and CVs cannot be screened.",
                   "Set GROQ_API_KEY in .env.")


def run_checks(probe: bool) -> list[dict]:
    """Every check, in the order the page shows them. The slow ones run side by side."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(fn, probe) for fn in (check_email, check_public_link, check_video, check_calendar)]
        results = [job.result() for job in jobs]
    return results + [check_speech(), check_ai()]
