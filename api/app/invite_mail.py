"""The interview invitation e-mail (Module 7).

The link and the text are made here, in plain code: no AI is involved, so the message is the
same every time and can never contain anything but the job, the time and the candidate's own link.

Every message goes to the candidate's real address through the company's own mail server
(SMTP_HOST, SMTP_USER, SMTP_PASSWORD). That can be Gmail, Google Workspace, Microsoft 365 or any
other SMTP server. There is no test inbox in between: what the hiring team sends is what arrives.
"""

import logging
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr
from html import escape

from app.models import Candidate, InterviewSession, JobProfile
from app.settings import settings

log = logging.getLogger("talentsight")

EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class MailServer:
    host: str
    port: int
    user: str
    password: str


def mail_server() -> MailServer | None:
    """The server to send through, or None when e-mail is not set up.

    SMTP_HOST and friends come first. An older .env that only has GMAIL_USER and
    GMAIL_APP_PASSWORD still works: that is simply Gmail's own server.
    """
    if settings.smtp_host.strip():
        return MailServer(settings.smtp_host.strip(), settings.smtp_port, settings.smtp_user.strip(), settings.smtp_password)
    if settings.gmail_user.strip() and settings.gmail_app_password:
        return MailServer("smtp.gmail.com", 587, settings.gmail_user.strip(), settings.gmail_app_password)
    return None


def sender(server: MailServer) -> str:
    """The From line. MAIL_FROM when it is set, otherwise the company name and the login address.

    Gmail and Microsoft 365 only send as the mailbox that logged in (or an alias of it), so the
    login address is the safe default.
    """
    if settings.mail_from.strip():
        return settings.mail_from.strip()
    return formataddr((f"{settings.company_name} Hiring", server.user))


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
    company = " ".join(settings.company_name.split())
    greeting = f"Hello {candidate.name.strip()}," if candidate.name.strip() else "Hello,"
    link = invite_link(session.invite_token)
    when = when_text(session.scheduled_at)
    intro = (
        f"Your video interview with {company} for the {title} position has been moved to a new time."
        if rescheduled
        else f"{company} invites you to a video interview for the {title} position."
    )
    rules = (
        f"The link opens {settings.join_early_minutes} minutes before the start time. "
        "It is made only for you, so please do not share it. "
        "You need a camera, a microphone and an up-to-date browser."
    )
    signature = f"The {company} hiring team"

    message = EmailMessage()
    message["Subject"] = f"{'Interview rescheduled' if rescheduled else 'Interview invitation'}: {title} at {company}"
    message["To"] = candidate.email.strip()
    message.set_content(f"{greeting}\n\n{intro}\n\nWhen: {when}\nJoin: {link}\n\n{rules}\n\nGood luck!\n{signature}\n")
    message.add_alternative(
        f"<p>{escape(greeting)}</p><p>{escape(intro)}</p>"
        f"<p><strong>When:</strong> {escape(when)}</p>"
        f'<p><a href="{escape(link)}">Join your interview</a></p>'
        f"<p>{escape(rules)}</p><p>Good luck!<br>{escape(signature)}</p>",
        subtype="html",
    )
    return message


def deliver(message: EmailMessage, server: MailServer) -> None:
    """Hands the message to the mail server. Port 465 is encrypted from the start; any other
    port is upgraded with STARTTLS before the password is sent."""
    context = ssl.create_default_context()
    if server.port == 465:
        smtp = smtplib.SMTP_SSL(server.host, server.port, timeout=20, context=context)
    else:
        smtp = smtplib.SMTP(server.host, server.port, timeout=20)
    with smtp:
        if server.port != 465:
            smtp.starttls(context=context)
        if server.user:
            smtp.login(server.user, server.password)
        smtp.send_message(message)


def send_invite(session: InterviewSession, candidate: Candidate, job: JobProfile, rescheduled: bool = False) -> str:
    """Sends the invitation. Returns "" when it was sent, otherwise a short reason. Never raises."""
    address = candidate.email.strip()
    server = mail_server()
    if not address:
        reason = "This candidate has no e-mail address. Copy the link and send it yourself."
    elif not EMAIL_SHAPE.match(address):
        reason = "The candidate's e-mail address looks wrong. Copy the link and send it yourself."
    elif server is None:
        reason = "E-mail is not set up (SMTP_HOST is empty). Copy the link and send it yourself."
    else:
        try:
            message = build_message(session, candidate, job, rescheduled)
            message["From"] = sender(server)
            deliver(message, server)
        except smtplib.SMTPAuthenticationError as error:
            log.warning(
                "invite e-mail refused the login",
                exc_info=error,
                extra={"event": "invite_email_failed", "session_id": session.id, "candidate_id": candidate.id},
            )
            return "The mail server refused the login. Check SMTP_USER and SMTP_PASSWORD, then send it again."
        except (OSError, smtplib.SMTPException, ValueError) as error:
            log.warning(
                "invite e-mail failed",
                exc_info=error,
                extra={"event": "invite_email_failed", "session_id": session.id, "candidate_id": candidate.id},
            )
            return "The e-mail could not be sent. Copy the link and send it yourself."
        log.info(
            "invite e-mail sent",
            extra={"event": "invite_email_sent", "session_id": session.id, "candidate_id": candidate.id, "via": server.host},
        )
        return ""

    log.warning("invite e-mail not sent", extra={"event": "invite_email_skipped", "session_id": session.id, "reason": reason})
    return reason
