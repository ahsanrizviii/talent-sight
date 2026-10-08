import httpx

from app.settings import settings

TOKEN_URL = "https://oauth2.googleapis.com/token"
FORMS_API = "https://forms.googleapis.com/v1/forms"
DRIVE_API = "https://www.googleapis.com/drive/v3/files"
TIMEOUT = 30


class GoogleError(Exception):
    """Google could not be reached, or refused the request."""


def auth_header() -> dict[str, str]:
    """Swaps the long-lived refresh token for a one-hour access token."""
    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": settings.google_refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise GoogleError(
            "Google sign-in failed. The refresh token may have expired."
        )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def form_responses(form_id: str) -> list[dict]:
    """Every answer sent through the form, page by page."""
    headers = auth_header()
    responses, page_token = [], None
    while True:
        params = {"pageToken": page_token} if page_token else {}
        response = httpx.get(
            f"{FORMS_API}/{form_id}/responses",
            headers=headers,
            params=params,
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            raise GoogleError(
                f"Google Forms refused the request ({response.status_code})."
            )
        body = response.json()
        responses += body.get("responses", [])
        page_token = body.get("nextPageToken")
        if not page_token:
            return responses


def download_file(file_id: str, max_bytes: int) -> tuple[str, bytes]:
    """Returns (file name, file bytes) of one uploaded CV in Google Drive."""
    headers = auth_header()
    info = httpx.get(
        f"{DRIVE_API}/{file_id}",
        headers=headers,
        params={"fields": "name,size"},
        timeout=TIMEOUT,
    )
    if info.status_code != 200:
        raise GoogleError(f"Google Drive refused the request ({info.status_code}).")
    if int(info.json().get("size", 0)) > max_bytes:
        # too big: return one byte more than the limit so the normal size check refuses it
        return info.json()["name"], b"x" * (max_bytes + 1)
    content = httpx.get(
        f"{DRIVE_API}/{file_id}",
        headers=headers,
        params={"alt": "media"},
        timeout=60,
    )
    if content.status_code != 200:
        raise GoogleError(f"Google Drive refused the download ({content.status_code}).")
    return info.json()["name"], content.content