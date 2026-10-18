import json
import logging
import re
import sys
import traceback
from datetime import datetime, timezone

SAFE_FIELDS = ("event", "path", "status_code", "error_type", "thread_id", "job_id",
"candidate_id", "count", "seconds", "session_id", "speaker")

# Invite links (/join/<token>, /api/invites/<token>, /api/ws/invite/<token>) are a candidate's
# private key to their interview, so no log line ever shows the token itself (N22).
SECRET_IN_PATH = re.compile(r"(/(?:invites?|join)/)[^/?\s\"']+")


def hide_secrets(text: str) -> str:
    """'/api/invites/AbC123/join' -> '/api/invites/***/join'."""
    return SECRET_IN_PATH.sub(r"\1***", text)


class HideSecrets(logging.Filter):
    """Masks invite tokens in the web server's own log lines: uvicorn writes every request path."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = hide_secrets(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(hide_secrets(arg) if isinstance(arg, str) else arg for arg in record.args)
        return True

class JsonFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": hide_secrets(record.getMessage()),
        }
        for field in SAFE_FIELDS:
            if hasattr(record, field):
                value = getattr(record, field)
                entry[field] = hide_secrets(value) if isinstance(value, str) else value
        if record.exc_info:
            error = record.exc_info[1]
            entry["error_type"] = type(error).__name__
            steps = traceback.extract_tb(error.__traceback__)
            if steps:
                entry["where"] = f"{steps[-1].filename}:{steps[-1].lineno}"
        return json.dumps(entry)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

        # uvicorn has its own log handlers; the filter goes on its loggers so the request lines are masked too.
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(HideSecrets())