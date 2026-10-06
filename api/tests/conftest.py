import os

import psycopg
import pytest
from sqlalchemy.engine import make_url

real_url = make_url(os.environ["DATABASE_URL"])
test_url = real_url.set(database=f"{real_url.database}_test")

# Create the test database once, if it does not exist yet.
with psycopg.connect(
    real_url.set(drivername="postgresql").render_as_string(hide_password=False),
    autocommit=True,
) as conn:
    found = conn.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (test_url.database,)
    ).fetchone()
    if not found:
        conn.execute(f'CREATE DATABASE "{test_url.database}"')

os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)

from fastapi.testclient import TestClient  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture
def client():
    """A fake browser for the API. Every test starts with empty tables."""
    Base.metadata.drop_all(engine)
    with TestClient(app) as test_client:  
        yield test_client