"""The hiring process of one job after screening: interview rounds, the report and onboarding.

A job has one or more interview rounds (job.interview_rounds, written in the JD chat or the job form).
Round 1 is booked from the shortlist ("Invite top candidates"). When a round has finished, the hiring
team closes it: they see everyone ranked by their interview score (F9) and choose who passes, by a
pass mark, by the top N, or by hand. Those who pass are booked into the next round and invited; the
others get a rejection e-mail. After the last round the candidates who passed reach the report stage.
There the team picks who is selected for onboarding; the rest get a rejection e-mail.

Everything here is plain code: who passes is the hiring team's choice, never the AI's. The AI only
writes the wording of the e-mails (mail_writer.py) and does the analysis it already did before.
"""

import logging
import time
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import agent_runs, assessment, claim_check, evaluation, interview_quality, interview_scoring, invite_mail, round_info
from app.db import SessionLocal
from app.interview_context import analysis_of
from app.models import (
    Assessment,
    Candidate,
    CandidateEmail,
    CandidateScore,
    ClaimCheck,
    HiringDecision,
    InterviewEvaluation,
    InterviewQuality,
    InterviewScore,
    InterviewSession,
    InviteBatch,
    InviteDelivery,
    JobProfile,
    OnboardingCheck,
    RoundClosure,
    RoundDecision,
)
from app.round_progress import interview_score_of

log = logging.getLogger("talentsight.hiring_rounds")

PAUSE_SECONDS = 1.0  # between two e-mails, so the mail server does not see a burst


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def held(session: InterviewSession) -> bool:
    """The interview really took place (a cancelled one ends without ever starting)."""
    return session.status == "ended" and session.started_at is not None


def cancelled(session: InterviewSession) -> bool:
    return session.status == "ended" and session.started_at is None


def find_round(job: JobProfile, number: int) -> dict:
    if not 1 <= number <= round_info.total_rounds(job):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This job has no such interview round.")
    return round_info.round_of(job, number)


def closure_of(db: Session, job_id: int, number: int) -> RoundClosure | None:
    return db.scalar(select(RoundClosure).where(RoundClosure.job_profile_id == job_id, RoundClosure.round_number == number))


def round_sessions(db: Session, job_id: int, number: int) -> dict[int, InterviewSession]:
    """The interview of each candidate in this round. When a candidate has more than one (a cancelled
    one and a new one), the newest that was not cancelled counts."""
    sessions = db.scalars(
        select(InterviewSession)
        .join(Candidate, InterviewSession.candidate_id == Candidate.id)
        .where(Candidate.job_profile_id == job_id, InterviewSession.round_number == number)
        .order_by(InterviewSession.id)
    ).all()
    chosen: dict[int, InterviewSession] = {}
    for session in sessions:
        current = chosen.get(session.candidate_id)
        if current is None or not cancelled(session) or cancelled(current):
            chosen[session.candidate_id] = session
    return chosen


def run_states(db: Session, model, session_ids: list[int]) -> dict[int, str]:
    """{session id: running | done | failed} for one kind of analysis."""
    if not session_ids:
        return {}
    rows = db.execute(select(model.session_id, model.status).where(model.session_id.in_(session_ids))).all()
    return {session_id: state for session_id, state in rows}


# ---------- One round ----------


def round_rows(db: Session, job: JobProfile, number: int) -> list[dict]:
    """Everyone in this round, ranked by their interview score: scored first (highest first),
    then held but not scored yet, then still waiting, then cancelled."""
    sessions = round_sessions(db, job.id, number)
    ids = [s.id for s in sessions.values()]
    analysis = run_states(db, InterviewEvaluation, ids)
    scoring = run_states(db, InterviewScore, ids)
    quality = run_states(db, InterviewQuality, ids)
    decisions = {
        candidate_id: outcome
        for candidate_id, outcome in db.execute(
            select(RoundDecision.candidate_id, RoundDecision.outcome).where(
                RoundDecision.job_profile_id == job.id, RoundDecision.round_number == number
            )
        ).all()
    }
    cv_scores = {
        candidate_id: overall
        for candidate_id, overall in db.execute(
            select(CandidateScore.candidate_id, CandidateScore.overall).where(CandidateScore.candidate_id.in_(list(sessions)))
        ).all()
    } if sessions else {}

    rows = []
    for candidate_id, session in sessions.items():
        candidate = db.get(Candidate, candidate_id)
        rows.append({
            "candidate_id": candidate_id,
            "name": candidate.name or candidate.cv_filename,
            "email": candidate.email,
            "session_id": session.id,
            "interview_status": session.status,
            "attended": held(session),
            "cancelled": cancelled(session),
            "scheduled_at": session.scheduled_at,
            "started_at": session.started_at,
            "score": interview_score_of(db, session.id),
            "cv_score": cv_scores.get(candidate_id),
            "analysis_status": analysis.get(session.id, ""),
            "score_status": scoring.get(session.id, ""),
            "quality_status": quality.get(session.id, ""),
            "decision": decisions.get(candidate_id, ""),
            "rank": None,
        })

    def order(row: dict):
        if row["score"] is not None:
            group = 0
        elif row["attended"]:
            group = 1
        elif not row["cancelled"]:
            group = 2
        else:
            group = 3
        return (group, -(row["score"] or 0), row["name"].lower())

    rows.sort(key=order)
    for place, row in enumerate((r for r in rows if r["score"] is not None), start=1):
        row["rank"] = place
    return rows


def round_view(db: Session, job: JobProfile, number: int) -> dict:
    this_round = find_round(job, number)
    rows = round_rows(db, job, number)
    closure = closure_of(db, job.id, number)
    if closure is not None:
        state = "closed"
    elif rows:
        state = "open"
    else:
        state = "not_started"
    return {
        **this_round,
        "total": round_info.total_rounds(job),
        "is_last": number == round_info.total_rounds(job),
        "state": state,
        "closure": None if closure is None else {
            "rule": closure.rule,
            "value": closure.value,
            "passed": closure.passed,
            "rejected": closure.rejected,
            "closed_at": closure.closed_at,
        },
        "invited": len(rows),
        "waiting": sum(1 for r in rows if r["interview_status"] in ("scheduled", "live")),
        "held": sum(1 for r in rows if r["attended"]),
        "scored": sum(1 for r in rows if r["score"] is not None),
        "rows": rows,
    }


def close_round(
    db: Session,
    job: JobProfile,
    number: int,
    passed_ids: list[int],
    rule: str,
    value: float | None,
    start_date: date | None,
    interviewer_id: int | None,
) -> dict:
    """Closes the round with the hiring team's choice. Commits. Returns what was done; the caller
    starts the e-mails in the background (deliver_batch for the next round, deliver_emails)."""
    from app.routers.invite_batches import book_round  # here: that router imports the interview router

    find_round(job, number)
    if closure_of(db, job.id, number) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This round is already closed.")
    if number > 1 and closure_of(db, job.id, number - 1) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Close round {number - 1} first.")
    rows = round_rows(db, job, number)
    if not rows:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nobody has been invited to this round yet.")
    waiting = [r for r in rows if r["interview_status"] in ("scheduled", "live")]
    if waiting:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{len(waiting)} interview(s) in this round have not finished yet. Hold or cancel them first (Interviews page).",
        )
    in_round = {r["candidate_id"] for r in rows}
    chosen = set(passed_ids)
    if not chosen <= in_round:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Some of the chosen candidates are not in this round.")
    last = number == round_info.total_rounds(job)
    if chosen and not last:
        if start_date is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pick the first interview day of the next round.")
        if start_date < date.today():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The first interview day cannot be in the past.")

    passing = [r for r in rows if r["candidate_id"] in chosen]  # in ranking order: the best gets the earliest slot
    failing = [r for r in rows if r["candidate_id"] not in chosen]
    for row in rows:
        db.add(RoundDecision(
            job_profile_id=job.id,
            candidate_id=row["candidate_id"],
            round_number=number,
            outcome="passed" if row["candidate_id"] in chosen else "rejected",
            score=row["score"],
        ))
    for row in failing:
        # Only candidates who really sat the interview are told they took part in it. Someone whose
        # interview was cancelled or never took place gets the "could not take place" e-mail instead.
        kind = "rejection" if row["attended"] else "not_held"
        db.add(CandidateEmail(job_profile_id=job.id, candidate_id=row["candidate_id"], kind=kind, round_number=number))
    db.add(RoundClosure(
        job_profile_id=job.id, round_number=number, rule=rule, value=value,
        passed=len(passing), rejected=len(failing), closed_by=interviewer_id,
    ))
    db.commit()
    log.info("round closed", extra={"event": "round_closed", "job_id": job.id, "round": number, "count": len(rows)})

    batch_id, booked, not_placed = None, 0, 0
    if passing and not last:
        batch, not_placed = book_round(db, job.id, [r["candidate_id"] for r in passing], start_date, number + 1, interviewer_id)
        if batch is not None:
            batch_id, booked = batch.id, batch.total
    return {
        "passed": len(passing),
        "rejected": len(failing),
        "next_round": None if last else number + 1,
        "batch_id": batch_id,
        "booked": booked,
        "not_placed": not_placed,
    }


def analyse_sessions(session_ids: list[int]) -> None:
    """For each finished interview: the answer analysis, then the interview score and the quality
    review, one after the other (both need the analysis). Runs in the background. Each part that is
    already done is skipped, and a problem with one interview never stops the others."""
    for session_id in session_ids:
        try:
            with SessionLocal() as db:
                session = db.get(InterviewSession, session_id)
                if session is None or not held(session):
                    continue
                if analysis_of(db, session_id) is None:
                    row = evaluation.start_evaluation(db, session)
                    row_id = row.id
                else:
                    row_id = None
            if row_id is not None:
                evaluation.run_evaluation(row_id)

            for model, first_step, runner in (
                (InterviewScore, interview_scoring.FIRST_STEP, interview_scoring.run_scoring),
                (InterviewQuality, interview_quality.FIRST_STEP, interview_quality.run_review),
            ):
                with SessionLocal() as db:
                    session = db.get(InterviewSession, session_id)
                    if session is None:
                        break
                    existing = agent_runs.row_of(db, model, session_id)
                    if existing is not None and existing.status in ("done", "running"):
                        continue
                    row_id = agent_runs.start(db, model, session, first_step).id
                runner(row_id)
        except HTTPException as refused:  # no transcript, already running...: this interview is skipped
            log.info(f"analysis skipped: {refused.detail}", extra={"event": "round_analysis_skipped", "session_id": session_id})
        except Exception as crash:
            log.error("round analysis failed", exc_info=crash, extra={"event": "round_analysis_failed", "session_id": session_id})


def sessions_to_analyse(db: Session, job: JobProfile, number: int) -> list[int]:
    """The finished interviews of this round that still miss their analysis, score or quality review."""
    return [
        r["session_id"]
        for r in round_rows(db, job, number)
        if r["attended"] and (r["analysis_status"] != "done" or r["score_status"] != "done" or r["quality_status"] != "done")
        and "running" not in (r["analysis_status"], r["score_status"], r["quality_status"])
    ]


# ---------- The report stage ----------


def finalists(db: Session, job: JobProfile) -> list[Candidate]:
    """Candidates who passed the job's last interview round."""
    last = round_info.total_rounds(job)
    ids = db.scalars(
        select(RoundDecision.candidate_id).where(
            RoundDecision.job_profile_id == job.id, RoundDecision.round_number == last, RoundDecision.outcome == "passed"
        )
    ).all()
    return [db.get(Candidate, candidate_id) for candidate_id in ids]


def report_rows(db: Session, job: JobProfile) -> list[dict]:
    """The finalists with their CV score, their score in each round and their consolidated
    assessment, ranked by the assessment's weighted total (not assessed yet: last)."""
    rounds = round_info.rounds_of(job)
    rows = []
    for candidate in finalists(db, job):
        scores = {
            number: score
            for number, score in db.execute(
                select(RoundDecision.round_number, RoundDecision.score).where(RoundDecision.candidate_id == candidate.id)
            ).all()
        }
        cv = db.scalar(select(CandidateScore).where(CandidateScore.candidate_id == candidate.id))
        report = db.scalar(select(Assessment).where(Assessment.candidate_id == candidate.id))
        claims = db.scalar(select(ClaimCheck).where(ClaimCheck.candidate_id == candidate.id))
        decision = db.scalar(select(HiringDecision).where(HiringDecision.candidate_id == candidate.id))
        position = (report.report or {}).get("position", {}) if report is not None and report.status == "done" else {}
        rows.append({
            "candidate_id": candidate.id,
            "name": candidate.name or candidate.cv_filename,
            "email": candidate.email,
            "cv_score": cv.overall if cv else None,
            "round_scores": [{"number": r["number"], "name": r["name"], "score": scores.get(r["number"])} for r in rounds],
            "assessment_status": report.status if report is not None else "",
            "report_score": position.get("overall"),
            "position": position.get("label", ""),
            "claims_status": claims.status if claims is not None else "",
            "claims_flagged": sum(
                1 for c in ((claims.result or {}).get("claims", []) if claims is not None else [])
                if c.get("status") in ("contradicted", "unsubstantiated")
            ),
            "decision": decision.decision if decision else "",
            "rank": None,
        })
    rows.sort(key=lambda r: (r["report_score"] is None, -(r["report_score"] or 0), r["name"].lower()))
    for place, row in enumerate((r for r in rows if r["report_score"] is not None), start=1):
        row["rank"] = place
    return rows


def assess_candidates(candidate_ids: list[int]) -> None:
    """The consolidated assessment, then the CV claim check, for each finalist that misses them.
    Runs in the background, one candidate after the other; a problem with one never stops the rest."""
    for candidate_id in candidate_ids:
        for start, runner, model in (
            (assessment.start_assessment, assessment.run_assessment, Assessment),
            (claim_check.start_check, claim_check.run_check, ClaimCheck),
        ):
            try:
                with SessionLocal() as db:
                    candidate = db.get(Candidate, candidate_id)
                    if candidate is None:
                        break
                    existing = db.scalar(select(model).where(model.candidate_id == candidate_id))
                    if existing is not None and existing.status in ("done", "running"):
                        continue
                    row_id = start(db, candidate).id
                runner(row_id)
            except HTTPException as refused:
                log.info(f"assessment skipped: {refused.detail}", extra={"event": "report_skipped", "candidate_id": candidate_id})
            except Exception as crash:
                log.error("report run failed", exc_info=crash, extra={"event": "report_failed", "candidate_id": candidate_id})


def decide_report(
    db: Session, job: JobProfile, selected_ids: list[int], onboarding_date: date | None, interviewer_id: int | None
) -> dict:
    """Selected finalists go to onboarding; every other finalist without a decision is rejected.
    Commits and queues the e-mails; the caller sends them in the background (deliver_emails)."""
    rows = [r for r in report_rows(db, job) if not r["decision"]]
    if not rows:
        raise HTTPException(status.HTTP_409_CONFLICT, "There is nobody waiting for a decision in the report stage.")
    open_ids = {r["candidate_id"] for r in rows}
    chosen = set(selected_ids)
    if not chosen <= open_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Some of the chosen candidates are not waiting for a decision.")
    for row in rows:
        picked = row["candidate_id"] in chosen
        db.add(HiringDecision(
            job_profile_id=job.id,
            candidate_id=row["candidate_id"],
            decision="onboarding" if picked else "rejected",
            report_score=row["report_score"],
            onboarding_date=onboarding_date if picked else None,
            decided_by=interviewer_id,
        ))
        db.add(CandidateEmail(
            job_profile_id=job.id,
            candidate_id=row["candidate_id"],
            kind="onboarding" if picked else "rejection",
            round_number=None,
        ))
    db.commit()
    log.info("report decided", extra={"event": "report_decided", "job_id": job.id, "count": len(rows)})
    return {"selected": len(chosen), "rejected": len(rows) - len(chosen)}


# ---------- Onboarding ----------


def onboarding_state(check: OnboardingCheck | None) -> str:
    """waiting (not checked yet) | in_progress | verified | not_confirmed | needs_decision"""
    if check is None:
        return "waiting"
    if check.decision == "not_confirmed":
        return "not_confirmed"
    if check.decision == "confirmed" or check.outcome == "match":
        return "verified"
    if check.status == "waiting":
        return "in_progress"
    return "needs_decision"


def onboarding_rows(db: Session, job_id: int | None = None) -> list[dict]:
    """Everyone selected for onboarding (one job, or every job), with their face check status."""
    query = select(HiringDecision).where(HiringDecision.decision == "onboarding").order_by(HiringDecision.decided_at.desc())
    if job_id is not None:
        query = query.where(HiringDecision.job_profile_id == job_id)
    rows = []
    for decision in db.scalars(query).all():
        candidate = db.get(Candidate, decision.candidate_id)
        job = db.get(JobProfile, decision.job_profile_id)
        check = db.scalar(select(OnboardingCheck).where(OnboardingCheck.candidate_id == candidate.id))
        rows.append({
            "candidate_id": candidate.id,
            "name": candidate.name or candidate.cv_filename,
            "email": candidate.email,
            "job_id": job.id,
            "job_title": job.title,
            "report_score": decision.report_score,
            "onboarding_date": decision.onboarding_date,
            "selected_at": decision.decided_at,
            "check_state": onboarding_state(check),
            "checked_at": check.checked_at if check else None,
            "best_score": check.best_score if check else None,
        })
    return rows


# ---------- E-mails ----------


def email_rows(db: Session, job: JobProfile) -> list[dict]:
    """Every e-mail this job has sent or queued: invitations (per round), rejections and onboarding
    e-mails, newest first, each with queued, sent or failed."""
    rows = []
    invitations = db.execute(
        select(InviteDelivery, InviteBatch, InterviewSession)
        .join(InviteBatch, InviteDelivery.batch_id == InviteBatch.id)
        .join(InterviewSession, InviteDelivery.session_id == InterviewSession.id)
        .where(InviteBatch.job_profile_id == job.id)
    ).all()
    for delivery, batch, session in invitations:
        candidate = db.get(Candidate, session.candidate_id)
        rows.append({
            "key": f"invite-{delivery.id}",
            "kind": "invitation",
            "candidate_id": candidate.id,
            "name": candidate.name or candidate.cv_filename,
            "email": candidate.email,
            "round_number": session.round_number or 1,
            "round_name": round_info.round_of(job, session.round_number or 1)["name"],
            "status": delivery.status,
            "error": delivery.error,
            "created_at": batch.created_at,
            "sent_at": delivery.sent_at,
        })
    for mail in db.scalars(select(CandidateEmail).where(CandidateEmail.job_profile_id == job.id)).all():
        candidate = db.get(Candidate, mail.candidate_id)
        rows.append({
            "key": f"mail-{mail.id}",
            "kind": mail.kind,
            "candidate_id": candidate.id,
            "name": candidate.name or candidate.cv_filename,
            "email": candidate.email,
            "round_number": mail.round_number,
            "round_name": round_info.round_of(job, mail.round_number)["name"] if mail.round_number else "After the report",
            "status": mail.status,
            "error": mail.error,
            "created_at": mail.created_at,
            "sent_at": mail.sent_at,
        })
    rows.sort(key=lambda r: (r["sent_at"] or r["created_at"]), reverse=True)
    return rows


def deliver_emails(job_id: int) -> None:
    """Sends the job's queued rejection and onboarding e-mails, one by one. Runs in the background.
    Each result is saved at once, so the page shows progress and a restart loses nothing."""
    with SessionLocal() as db:
        waiting = db.scalars(
            select(CandidateEmail)
            .where(CandidateEmail.job_profile_id == job_id, CandidateEmail.status == "queued")
            .order_by(CandidateEmail.id)
        ).all()
        job = db.get(JobProfile, job_id)
        for index, mail in enumerate(waiting):
            candidate = db.get(Candidate, mail.candidate_id)
            if candidate is None or job is None:
                continue
            day = ""
            if mail.kind == "onboarding":
                decision = db.scalar(select(HiringDecision).where(HiringDecision.candidate_id == candidate.id))
                if decision is not None and decision.onboarding_date is not None:
                    day = decision.onboarding_date.strftime("%A, %d %B %Y")
            error = invite_mail.send_outcome(candidate, job, mail.kind, mail.round_number, day)
            mail.status = "sent" if error == "" else "failed"
            mail.error = error
            mail.sent_at = utcnow()
            db.commit()
            if index < len(waiting) - 1:
                time.sleep(PAUSE_SECONDS)
    log.info("candidate e-mails done", extra={"event": "candidate_emails_done", "job_id": job_id})


def queue_failed_again(db: Session, job: JobProfile) -> list[int]:
    """Puts every failed e-mail of the job back in the queue. Returns the invitation batches to send again.
    Commits; the caller runs deliver_batch for each batch and deliver_emails for the rest."""
    batches = set()
    for delivery, batch in db.execute(
        select(InviteDelivery, InviteBatch)
        .join(InviteBatch, InviteDelivery.batch_id == InviteBatch.id)
        .where(InviteBatch.job_profile_id == job.id, InviteDelivery.status == "failed")
    ).all():
        delivery.status, delivery.error = "queued", ""
        batches.add(batch.id)
    for mail in db.scalars(
        select(CandidateEmail).where(CandidateEmail.job_profile_id == job.id, CandidateEmail.status == "failed")
    ).all():
        mail.status, mail.error = "queued", ""
    db.commit()
    return sorted(batches)


# ---------- The job page: every stage in numbers ----------


def summary(db: Session, job: JobProfile) -> dict:
    """The numbers on the job page's stage bar."""
    candidates = db.scalars(select(Candidate).where(Candidate.job_profile_id == job.id)).all()
    mails = email_rows(db, job)
    rounds = []
    for this_round in round_info.rounds_of(job):
        view = round_view(db, job, this_round["number"])
        rounds.append({key: view[key] for key in (
            "number", "name", "focus", "state", "invited", "waiting", "held", "scored", "is_last"
        )} | {
            "passed": view["closure"]["passed"] if view["closure"] else None,
            "rejected": view["closure"]["rejected"] if view["closure"] else None,
        })
    report = report_rows(db, job)
    onboarding = onboarding_rows(db, job.id)
    return {
        "cvs": len(candidates),
        "screened": sum(1 for c in candidates if c.status in ("screened", "excluded")),
        "passed_screening": sum(1 for c in candidates if c.status == "screened"),
        "emails": {
            "total": len(mails),
            "sent": sum(1 for m in mails if m["status"] == "sent"),
            "queued": sum(1 for m in mails if m["status"] == "queued"),
            "failed": sum(1 for m in mails if m["status"] == "failed"),
        },
        "rounds": rounds,
        "finalists": len(report),
        "undecided": sum(1 for r in report if not r["decision"]),
        "selected": len(onboarding),
        "verified": sum(1 for r in onboarding if r["check_state"] == "verified"),
    }
