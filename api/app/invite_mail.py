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
from email.utils import formataddr, parseaddr
from urllib.parse import urlparse
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


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _ics_fold(line: str) -> str:
    """Calendar files may not have lines longer than 75 bytes: longer ones continue on the next line."""
    raw = line.encode("utf-8")
    parts = []
    while len(raw) > 75:
        cut = 75
        while cut > 0 and (raw[cut] & 0xC0) == 0x80:  # never cut inside a multi-byte letter
            cut -= 1
        parts.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    parts.append(raw.decode("utf-8"))
    return "\r\n".join(parts)


def organizer_address(server: MailServer) -> str:
    return parseaddr(sender(server))[1] or server.user


def calendar_invite(
    session: InterviewSession,
    candidate: Candidate,
    job: JobProfile,
    server: MailServer,
    method: str = "REQUEST",
) -> str:
    """The candidate's own calendar entry (an .ics file), so the interview lands in Gmail Calendar,
    Outlook or Apple Calendar on whatever device they use. It carries only the time and their
    private link. method is REQUEST to add or move the entry, CANCEL to remove it.
    """
    start = session.scheduled_at.astimezone(timezone.utc)
    end = start + timedelta(minutes=settings.interview_minutes)
    stamp = datetime.now(timezone.utc)
    company = " ".join(settings.company_name.split())
    title = " ".join(job.title.split())
    link = invite_link(session.invite_token)
    host = urlparse(settings.public_base_url).hostname or "talentsight"
    cancelled = method == "CANCEL"
    when = "%Y%m%dT%H%M%SZ"
    description = (
        f"Video interview for the {title} position at {company}.\nJoin: {link}\n"
        f"The link opens {settings.join_early_minutes} minutes before the start. It is made only for you."
    )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TalentSight//Interviews//EN",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:interview-{session.id}@{host}",
        f"DTSTAMP:{stamp:{when}}",
        # A higher SEQUENCE tells the calendar this replaces the earlier version of the same entry.
        f"SEQUENCE:{int(stamp.timestamp())}",
        f"DTSTART:{start:{when}}",
        f"DTEND:{end:{when}}",
        f"SUMMARY:{_ics_escape(f'Interview at {company}: {title}')}",
        f"DESCRIPTION:{_ics_escape(description)}",
        f"LOCATION:{_ics_escape(link)}",
        f"URL:{link}",
        f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}",
        f"ORGANIZER;CN={_ics_escape(company + ' Hiring')}:mailto:{organizer_address(server)}",
        f"ATTENDEE;CN={_ics_escape(candidate.name.strip() or candidate.email)};ROLE=REQ-PARTICIPANT;RSVP=FALSE:mailto:{candidate.email.strip()}",
    ]
    if not cancelled:
        lines += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "DESCRIPTION:Interview starts soon",
            "TRIGGER:-PT15M",
            "END:VALARM",
        ]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"


def attach_calendar_invite(message: EmailMessage, ics: str, method: str) -> None:
    """Added twice, the way Google does it: as an alternative body, so Gmail and Outlook show their
    own "add to calendar" card, and as invite.ics, for apps that only understand attachments."""
    message.add_alternative(ics, subtype="calendar", params={"method": method})
    message.add_attachment(ics.encode("utf-8"), maintype="application", subtype="ics", filename="invite.ics")


def build_message(
    session: InterviewSession, candidate: Candidate, job: JobProfile, rescheduled: bool, server: MailServer
) -> EmailMessage:
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
    attach_calendar_invite(message, calendar_invite(session, candidate, job, server), "REQUEST")
    return message


def build_cancellation(session: InterviewSession, candidate: Candidate, job: JobProfile, server: MailServer) -> EmailMessage:
    """Tells the candidate the interview will not happen, and removes it from their calendar."""
    title = " ".join(job.title.split())
    company = " ".join(settings.company_name.split())
    greeting = f"Hello {candidate.name.strip()}," if candidate.name.strip() else "Hello,"
    when = when_text(session.scheduled_at)
    text = (
        f"The video interview with {company} for the {title} position, planned for {when}, has been cancelled. "
        "The link you were sent no longer works. If a new time is agreed, you will get a new e-mail."
    )
    signature = f"The {company} hiring team"

    message = EmailMessage()
    message["Subject"] = f"Interview cancelled: {title} at {company}"
    message["To"] = candidate.email.strip()
    message.set_content(f"{greeting}\n\n{text}\n\n{signature}\n")
    message.add_alternative(f"<p>{escape(greeting)}</p><p>{escape(text)}</p><p>{escape(signature)}</p>", subtype="html")
    attach_calendar_invite(message, calendar_invite(session, candidate, job, server, method="CANCEL"), "CANCEL")
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


def _send(session: InterviewSession, candidate: Candidate, job: JobProfile, make, what: str) -> str:
    """Builds and sends one message. Returns "" when sent, otherwise a short reason. Never raises.

    make(server) builds the message once the mail server is known.
    """
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
            message = make(server)
            message["From"] = sender(server)
            deliver(message, server)
        except smtplib.SMTPAuthenticationError as error:
            log.warning(
                f"{what} e-mail refused the login",
                exc_info=error,
                extra={"event": "invite_email_failed", "session_id": session.id, "candidate_id": candidate.id},
            )
            return "The mail server refused the login. Check SMTP_USER and SMTP_PASSWORD, then send it again."
        except (OSError, smtplib.SMTPException, ValueError) as error:
            log.warning(
                f"{what} e-mail failed",
                exc_info=error,
                extra={"event": "invite_email_failed", "session_id": session.id, "candidate_id": candidate.id},
            )
            return "The e-mail could not be sent. Copy the link and send it yourself."
        log.info(
            f"{what} e-mail sent",
            extra={"event": "invite_email_sent", "session_id": session.id, "candidate_id": candidate.id, "via": server.host},
        )
        return ""

    log.warning(f"{what} e-mail not sent", extra={"event": "invite_email_skipped", "session_id": session.id, "reason": reason})
    return reason


def send_invite(session: InterviewSession, candidate: Candidate, job: JobProfile, rescheduled: bool = False) -> str:
    """Sends the invitation. Returns "" when it was sent, otherwise a short reason. Never raises."""
    return _send(session, candidate, job, lambda server: build_message(session, candidate, job, rescheduled, server), "invite")


def send_cancellation(session: InterviewSession, candidate: Candidate, job: JobProfile) -> str:
    """Tells the candidate their interview was cancelled. Returns "" when sent, otherwise a reason."""
    return _send(session, candidate, job, lambda server: build_cancellation(session, candidate, job, server), "cancellation")


def check_login(server: MailServer) -> str:
    """For the setup page: connects and logs in without sending anything. Returns "" when it works."""
    try:
        context = ssl.create_default_context()
        if server.port == 465:
            smtp = smtplib.SMTP_SSL(server.host, server.port, timeout=10, context=context)
        else:
            smtp = smtplib.SMTP(server.host, server.port, timeout=10)
        with smtp:
            if server.port != 465:
                smtp.starttls(context=context)
            if server.user:
                smtp.login(server.user, server.password)
    except smtplib.SMTPAuthenticationError:
        return "The mail server refused the login. Check SMTP_USER and SMTP_PASSWORD."
    except (OSError, smtplib.SMTPException):
        return "The mail server could not be reached. Check SMTP_HOST and SMTP_PORT."
    return ""


def send_test(address: str) -> str:
    """One plain test message, so the hiring team can see an e-mail really arrives. "" = sent."""
    server = mail_server()
    if server is None:
        return "E-mail is not set up (SMTP_HOST is empty)."
    if not EMAIL_SHAPE.match(address.strip()):
        return "That e-mail address looks wrong."
    company = " ".join(settings.company_name.split())
    message = EmailMessage()
    message["Subject"] = f"Test e-mail from {company} TalentSight"
    message["To"] = address.strip()
    message["From"] = sender(server)
    message.set_content(
        "This is a test. If you can read it, interview invitations sent from TalentSight reach real inboxes.\n\n"
        "If it arrived in spam, mark it as not spam: candidates' invitations will then arrive normally too.\n"
    )
    try:
        deliver(message, server)
    except smtplib.SMTPAuthenticationError:
        return "The mail server refused the login. Check SMTP_USER and SMTP_PASSWORD."
    except (OSError, smtplib.SMTPException):
        return "The mail server could not be reached. Check SMTP_HOST and SMTP_PORT."
    return ""
