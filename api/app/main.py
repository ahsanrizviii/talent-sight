import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.db import init_db
from app.logging_setup import setup_logging
from app.routers import health

setup_logging()
log = logging.getLogger("talentsight")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("api started", extra={"event": "startup"})
    yield

app = FastAPI(
    title="TalentSight API",
    lifespan=lifespan,
    docs_url="/api/docs",
    openai_url="/api/openapi.json",
)

@app.middleware("http")
async def hide_unexpected_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as error:
        log.error("unexpected error", exc_info=error, extra={"event": "unhandled_error", "path": request.url.path})
        return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})

app.include_router(health.router)
