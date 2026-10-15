"""The interview invitation e-mail (Module 7).

The AI writes only the wording: the subject, the opening and the closing sentence (mail_writer.py, with
its system prompt, and checked by code afterwards). Everything that must be exact is made here, in plain
code: the date, time, length, the candidate's own link, the button, the rules and the calendar file.
The AI never sees the link or the time. If the AI is off or down, a fixed wording is used.

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

from app import company_profile, mail_template, mail_writer, schedule_rules
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
    """The From line. MAIL_FROM when it is set, otherwise the sender name from the Settings page
    and the mailbox that logs in.

    Gmail and Microsoft 365 only send as the mailbox that logged in (or an alias of it), so the
    address itself is always the SMTP login. Only the name in front of it is free to choose.
    """
    if settings.mail_from.strip():
        return settings.mail_from.strip()
    return formataddr((company_profile.current().sender_name, server.user))


def reply_to() -> str:
    """Where a candidate's reply goes: the contact person from the Settings page, if one is set."""
    details = company_profile.current()
    if not details.contact_email:
        return ""
    return formataddr((details.contact_name or details.name, details.contact_email))


def invite_link(token: str) -> str:
    """The page the candidate opens (Task 7.2.2 builds that page)."""
    return f"{settings.public_base_url.rstrip('/')}/join/{token}"


def when_text(moment: datetime) -> str:
    """'Monday, 12 October 2026 at 15:30 (UTC+06:00)' in the time zone set in the settings."""
    minutes = settings.interview_utc_offset_minutes
    local = moment.astimezone(timezone(timedelta(minutes=minutes)))
    sign = "+" if minutes >= 0 else "-"
    return f"{local:%A, %d %B %Y at %H:%M} (UTC{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d})"


def _local(moment: datetime) -> datetime:
    return moment.astimezone(timezone(timedelta(minutes=settings.interview_utc_offset_minutes)))


def _clock(moment: datetime) -> str:
    return f"{moment:%I:%M %p}".lstrip("0")


def zone_text() -> str:
    minutes = settings.interview_utc_offset_minutes
    sign = "+" if minutes >= 0 else "-"
    return f"UTC{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def date_and_time(start: datetime, minutes: int) -> tuple[str, str]:
    """('Thursday, 16 October 2026', '10:15 AM - 11:15 AM (UTC+06:00)') in the configured time zone."""
    begin = _local(start)
    end = begin + timedelta(minutes=minutes)
    return f"{begin:%A, %d %B %Y}", f"{_clock(begin)} - {_clock(end)} ({zone_text()})"


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
    end = start + timedelta(minutes=schedule_rules.minutes_of(session))
    stamp = datetime.now(timezone.utc)
    company_name = company_profile.current().name
    title = " ".join(job.title.split())
    link = invite_link(session.invite_token)
    host = urlparse(settings.public_base_url).hostname or "talentsight"
    cancelled = method == "CANCEL"
    when = "%Y%m%dT%H%M%SZ"
    description = (
        f"Video interview for the {title} position at {company_name}.\nJoin: {link}\n"
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
        f"SUMMARY:{_ics_escape(f'Interview at {company_name}: {title}')}",
        f"DESCRIPTION:{_ics_escape(description)}",
        f"LOCATION:{_ics_escape(link)}",
        f"URL:{link}",
        f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}",
        f"ORGANIZER;CN={_ics_escape(company_profile.current().sender_name)}:mailto:{organizer_address(server)}",
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


def _contact_line(details: company_profile.Company) -> tuple[str, str]:
    """'For any question, contact ...' as plain text and as HTML. Empty when no contact is set."""
    if not details.contact_email:
        return "", ""
    who = details.contact_name or f"the {details.name} hiring team"
    text = f"For any question, contact {who} at {details.contact_email}."
    html = mail_template.paragraph(f"For any question, contact {who} at ").replace(
        "</p>", f'<a href="mailto:{escape(details.contact_email)}" style="color:{mail_template.ACCENT}">{escape(details.contact_email)}</a>.</p>'
    )
    return text, html


def _footer(details: company_profile.Company) -> tuple[str, str]:
    text = (
        "If this e-mail is not meant for you, you can safely ignore it.\n"
        f"Sent by {details.name} with TalentSight."
    )
    return text, escape(text).replace("\n", "<br>")


def build_message(
    session: InterviewSession, candidate: Candidate, job: JobProfile, rescheduled: bool, server: MailServer
) -> EmailMessage:
    """The invitation, in the same shape as a formal test or interview invitation:
    greeting, what it is, a details block, one button, the rules, who to contact, and a footer.
    The wording (subject, opening, closing) comes from the AI; the facts are filled in here."""
    details = company_profile.current()
    title = company_profile.one_line(job.title)  # one line: no line break can sneak into the subject
    name = company_profile.one_line(candidate.name)
    link = invite_link(session.invite_token)
    minutes = schedule_rules.minutes_of(session)
    day, hours = date_and_time(session.scheduled_at, minutes)

    wording, written_by = mail_writer.write_invite(candidate.name, job.title, rescheduled)
    subject, intro, closing = wording.subject, wording.intro, wording.closing
    heading = f"Your interview at {details.name} has a new time" if rescheduled else f"Invitation for Interview at {details.name}"
    greeting = f"Dear {name}," if name else "Dear candidate,"
    rows = [
        ("Position", title),
        ("Date", day),
        ("Time", hours),
        ("Duration", f"{minutes} minutes"),
        ("Format", "Online video call"),
    ]
    rules = [
        f"The button works from {settings.join_early_minutes} minutes before the start time.",
        "The link is made only for you. Please do not share it.",
        "You need a camera, a microphone and an up-to-date browser (Chrome, Edge, Firefox or Safari).",
        "Nothing is recorded. What is said is only turned into text for the interviewer.",
    ]
    contact_text, contact_html = _contact_line(details)
    footer_text, footer_html = _footer(details)
    sign_off = f"Best regards,\nThe {details.name} hiring team"

    message = EmailMessage()
    message["Subject"] = subject
    message["To"] = candidate.email.strip()
    detail_lines = "\n".join(f"{label}: {value}" for label, value in rows)
    rule_lines = "\n".join(f"- {rule}" for rule in rules)
    message.set_content(
        f"{greeting}\n\n{intro}\n\nINTERVIEW DETAILS\n{detail_lines}\n\nJoin your interview: {link}\n\n"
        f"{rule_lines}\n\n{contact_text + chr(10) + chr(10) if contact_text else ''}"
        f"{closing}\n\n{sign_off}\n\n--\n{footer_text}\n"
    )
    body = (
        mail_template.paragraph(greeting)
        + mail_template.paragraph(intro)
        + mail_template.details_table(rows)
        + mail_template.button("Join your interview", link)
        + mail_template.notes(rules)
        + contact_html
        + mail_template.paragraph(closing)
        + mail_template.paragraph(sign_off).replace("\n", "<br>")
    )
    message.add_alternative(mail_template.page(details.name, heading, body, footer_html), subtype="html")
    attach_calendar_invite(message, calendar_invite(session, candidate, job, server), "REQUEST")
    message["X-TalentSight-Wording"] = written_by  # "ai" or "template": shows in the e-mail's headers
    return message


def build_cancellation(session: InterviewSession, candidate: Candidate, job: JobProfile, server: MailServer) -> EmailMessage:
    """Tells the candidate the interview will not happen, and removes it from their calendar."""
    details = company_profile.current()
    title = company_profile.one_line(job.title)
    name = company_profile.one_line(candidate.name)
    minutes = schedule_rules.minutes_of(session)
    day, hours = date_and_time(session.scheduled_at, minutes)
    greeting = f"Dear {name}," if name else "Dear candidate,"
    text = (
        f"We are sorry to tell you that your video interview for the {title} position has been cancelled. "
        "The link you were sent no longer works. If a new time is agreed, you will get a new e-mail."
    )
    rows = [("Position", title), ("Was planned for", f"{day}, {hours}")]
    contact_text, contact_html = _contact_line(details)
    footer_text, footer_html = _footer(details)
    sign_off = f"Best regards,\nThe {details.name} hiring team"

    message = EmailMessage()
    message["Subject"] = f"Interview cancelled at {details.name}: {title}"
    message["To"] = candidate.email.strip()
    message.set_content(
        f"{greeting}\n\n{text}\n\nPosition: {title}\nWas planned for: {day}, {hours}\n\n"
        f"{contact_text + chr(10) + chr(10) if contact_text else ''}{sign_off}\n\n--\n{footer_text}\n"
    )
    body = (
        mail_template.paragraph(greeting)
        + mail_template.paragraph(text)
        + mail_template.details_table(rows)
        + contact_html
        + mail_template.paragraph(sign_off).replace("\n", "<br>")
    )
    message.add_alternative(
        mail_template.page(details.name, f"Your interview at {details.name} is cancelled", body, footer_html), subtype="html"
    )
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
            if reply_to():
                message["Reply-To"] = reply_to()
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
    message = EmailMessage()
    message["Subject"] = f"Test e-mail from {company_profile.current().name} TalentSight"
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
