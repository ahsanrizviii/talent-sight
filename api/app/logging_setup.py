import json
import logging
import sys
import traceback
from datetime import datetime, timezone

SAFE_FIELDS = ("event", "path", "status_code", "error_type", "thread_id", "job_id")

class JsonFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in SAFE_FIELDS:
            if hasattr(record, field):
                entry[field] = getattr(record, field)
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