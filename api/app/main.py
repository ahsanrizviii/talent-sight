import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.identity import purge_expired_at_start
from app import agent_runs
from app.models import InterviewQuality, InterviewScore
from app.agents.jd_agent import get_jd_agent
from app.assessment import mark_interrupted_assessments
from app.claim_check import mark_interrupted_checks
from app.db import init_db
from app.evaluation import mark_interrupted_evaluations
from app.holiday_calendar import load_holiday_calendars
from app.knowledge import load_policies
from app import library as document_library
from app import litmus_run
from app.logging_setup import setup_logging
from app.references import load_references
from app.routers import (
    assessments,
    auth,
    candidates,
    claims,
    company,
    evaluations,
    health,
    identity,
    interview_chat,
    interview_quality,
    interview_score,
    interviews,
    invite_batches,
    invites,
    jd_chat,
    jobs,
    library,
    litmus,
    public,
    setup,
    transcripts,
    workspace,
)
from app.screening import mark_interrupted_runs
from app.seed import seed_interviewer

setup_logging()
log = logging.getLogger("talentsight")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once when the API starts, before it accepts any request.
    init_db()
    seed_interviewer()
    document_library.set_up()  # the Library volume is filled once from api/knowledge (Task 4.3.2 follow-up)
    load_policies()
    load_references()  # the skills reference documents for the Evaluation Agent (Module 9)
    mark_interrupted_runs()
    mark_interrupted_evaluations()
    mark_interrupted_assessments()  # the same for a consolidated assessment (Module 10)
    mark_interrupted_checks()  # and for a CV claim check (Module 13)
    agent_runs.mark_interrupted(InterviewQuality)  # and for an interview quality review (Module 13)
    agent_runs.mark_interrupted(InterviewScore)  # and for an interview score (Module 13)
    litmus_run.mark_interrupted()  # and for a Litmus check (F11)
    purge_expired_at_start()  # face templates past BIOMETRIC_RETENTION_DAYS are deleted (Module 13, F7)
    # The holiday calendar PDF(s) in knowledge/holidays: reading one (OCR + AI) takes about a minute,
    # so it runs in the background and the API is ready straight away. Files read before are skipped.
    threading.Thread(target=load_holiday_calendars, name="holiday-calendars", daemon=True).start()

    # Build the agent now: this also creates LangGraph's checkpoint tables. Doing it
    # here, before any request, matters: creating those tables waits until no other
    # database transaction is open, so doing it in the middle of a request would wait forever.
    get_jd_agent()

    log.info("api started", extra={"event": "startup"})
    yield


app = FastAPI(
    title="TalentSight API",
    description=(
        "TalentSight helps hiring teams find the right candidate faster by screening CVs, "
        "capturing interviews and turning both into one evidence-backed assessment."
    ),
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


@app.middleware("http")
async def hide_unexpected_errors(request: Request, call_next):
    """Wraps every request like a try/except.

    Errors we expected (wrong password, missing job...) are normal answers and pass through.
    Anything else is logged for us and the user only sees a plain message: no stack trace,
    file path or setting ever reaches the browser (N12).
    """
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
app.include_router(candidates.router)
app.include_router(interviews.router)
app.include_router(transcripts.router)
app.include_router(transcripts.pages)
app.include_router(workspace.router)
app.include_router(setup.router)
app.include_router(company.router)
app.include_router(invite_batches.router)
app.include_router(evaluations.router)
app.include_router(assessments.router)
app.include_router(claims.router)
app.include_router(interview_chat.router)
app.include_router(interview_quality.router)
app.include_router(interview_score.router)
app.include_router(identity.router)
app.include_router(identity.candidate_router)
app.include_router(litmus.router)
app.include_router(library.router)