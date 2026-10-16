from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.models import Base
from app.settings import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db() -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    # create_all makes new tables but never new columns, so a column added to an existing table
    # is added here by hand. "IF NOT EXISTS" makes it safe to run at every start.
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE interview_sessions ADD COLUMN IF NOT EXISTS duration_minutes INTEGER"))
                # Module 10: the assessments table existed since Module 2 without these columns.
        connection.execute(text("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'done'"))
        connection.execute(text("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS step VARCHAR(200) NOT NULL DEFAULT ''"))
        connection.execute(text("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS error TEXT NOT NULL DEFAULT ''"))
        connection.execute(text("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ"))
        connection.execute(text("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS seconds DOUBLE PRECISION"))