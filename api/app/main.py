import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.agents.jd_agent import get_jd_agent
from app.db import init_db
from app.knowledge import load_policies
from app.logging_setup import setup_logging
from app.routers import auth, health, invites, jd_chat, jobs, public
from app.seed import seed_interviewer

setup_logging()
log = logging.getLogger("talentsight")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_interviewer()
    load_policies()

    get_jd_agent()

    log.info("api started", extra={"event": "startup"})
    yield


app = FastAPI(
    title="TalentSight API",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


@app.middleware("http")
async def hide_unexpected_errors(request: Request, call_next):

    try:
        return await call_next(request)
    except Exception as error:
        log.error(
            "unexpected error",
            exc_info=error,
            extra={"event": "unhandled_error", "path": request.url.path},
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Something went wrong. Please try again."},
        )

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(invites.router)
app.include_router(jobs.router)
app.include_router(jd_chat.router)
app.include_router(public.router)