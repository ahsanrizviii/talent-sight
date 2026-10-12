"""The interview invitation e-mail (Module 7).

The link and the text are made here, in plain code: no AI is involved, so the message is the
same every time and can never contain anything but the job, the time and the candidate's own link.
Where it goes: a real Gmail address gets a real e-mail through Gmail (when GMAIL_USER is set);
every other address (sample CVs, made-up domains) goes to Mailpit, the fake inbox at http://localhost:8025.
"""

import logging
import re
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape

from app.models import Candidate, InterviewSession, JobProfile
from app.settings import settings

log = logging.getLogger("talentsight")

EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def invite_link(token: str) -> str:
    """The page the candidate opens (Task 7.2.2 builds that page)."""
    return f"{settings.public_base_url.rstrip('/')}/join/{token}"


def when_text(moment: datetime) -> str:
    """'Monday, 12 October 2026 at 15:30 (UTC+06:00)' in the time zone set in the settings."""
    minutes = settings.interview_utc_offset_minutes
    local = moment.astimezone(timezone(timedelta(minutes=minutes)))
    sign = "+" if minutes >= 0 else "-"
    return f"{local:%A, %d %B %Y at %H:%M} (UTC{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d})"


def build_message(session: InterviewSession, candidate: Candidate, job: JobProfile, rescheduled: bool) -> EmailMessage:
    title = " ".join(job.title.split())  # one line: no line break can sneak into the subject
    greeting = f"Hello {candidate.name.strip()}," if candidate.name.strip() else "Hello,"
    link = invite_link(session.invite_token)
    when = when_text(session.scheduled_at)
    intro = (
        f"Your video interview for the {title} position has been moved to a new time."
        if rescheduled
        else f"You are invited to a video interview for the {title} position."
    )
    rules = (
        f"The link opens {settings.join_early_minutes} minutes before the start time. "
        "It is made only for you, so please do not share it. "
        "You need a camera, a microphone and an up-to-date browser."
    )

    message = EmailMessage()
    message["Subject"] = f"{'Interview rescheduled' if rescheduled else 'Interview invitation'}: {title}"
    message["From"] = settings.mail_from
    message["To"] = candidate.email.strip()
    message.set_content(f"{greeting}\n\n{intro}\n\nWhen: {when}\nJoin: {link}\n\n{rules}\n\nGood luck!\nThe TalentSight hiring team\n")
    message.add_alternative(
        f"<p>{escape(greeting)}</p><p>{escape(intro)}</p>"
        f"<p><strong>When:</strong> {escape(when)}</p>"
        f'<p><a href="{escape(link)}">Join your interview</a></p>'
        f"<p>{escape(rules)}</p><p>Good luck!<br>The TalentSight hiring team</p>",
        subtype="html",
    )
    return message


def _split(text: str) -> set[str]:
    return {part.strip().lower() for part in text.split(",") if part.strip()}


def goes_to_gmail(address: str) -> bool:
    """True when this address should get a real e-mail through Gmail instead of Mailpit."""
    if not settings.gmail_user or not settings.gmail_app_password:
        return False  # Gmail not set up: everything stays in Mailpit
    address = address.lower()
    only_to = _split(settings.real_mail_only_to)
    if only_to:
        return address in only_to  # safety list: real mail only to these people
    return address.rsplit("@", 1)[-1] in _split(settings.real_mail_domains)


def _deliver(message: EmailMessage, address: str) -> str:
    """Hands the message to Gmail or to Mailpit. Returns which one, for the log."""
    if goes_to_gmail(address):
        # Gmail only sends as the signed-in account, so the From address must be that account.
        del message["From"]
        message["From"] = f"TalentSight <{settings.gmail_user}>"
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())  # encrypt before sending the password
            smtp.login(settings.gmail_user, settings.gmail_app_password)
            smtp.send_message(message)
        return "gmail"
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.send_message(message)
    return "mailpit"


def send_invite(session: InterviewSession, candidate: Candidate, job: JobProfile, rescheduled: bool = False) -> str:
    """Sends the invitation. Returns "" when it was sent, otherwise a short reason. Never raises."""
    address = candidate.email.strip()
    if not address:
        reason = "This candidate has no e-mail address. Copy the link and send it yourself."
    elif not EMAIL_SHAPE.match(address):
        reason = "The candidate's e-mail address looks wrong. Copy the link and send it yourself."
    elif not settings.smtp_host and not goes_to_gmail(address):
        reason = "E-mail is switched off (SMTP_HOST is empty). Copy the link and send it yourself."
    else:
        try:
            message = build_message(session, candidate, job, rescheduled)
            via = _deliver(message, address)
        except (OSError, smtplib.SMTPException, ValueError) as error:
            log.warning(
                "invite e-mail failed",
                exc_info=error,
                extra={"event": "invite_email_failed", "session_id": session.id, "candidate_id": candidate.id},
            )
            return "The e-mail could not be sent. Copy the link and send it yourself."
        log.info("invite e-mail sent", extra={"event": "invite_email_sent", "session_id": session.id, "candidate_id": candidate.id, "via": via})
        return ""

    log.warning("invite e-mail not sent", extra={"event": "invite_email_skipped", "session_id": session.id, "reason": reason})
    return reason