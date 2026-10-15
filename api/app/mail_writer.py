"""The AI writes the wording of the interview invitation e-mail.

The AI gets a SYSTEM PROMPT (MAIL_PROMPT below: the rules for tone and content, the same for every
candidate) and a short USER PROMPT with the facts (company, candidate, position, first invitation or
moved). It writes three things: the subject, a short opening, and a short closing sentence.

Everything that must be exact is NOT written by the AI. The date, time, length, the private link, the
join button, the rules, the contact line and the calendar file are all filled in by plain code in
invite_mail.py. The AI never sees the link, the time or any score.

Two guards make this safe:
1. The AI's text is checked before it is used. It is refused when it has a number, a link, an
   e-mail address or a line break in the wrong place, or is too short or too long.
2. When the AI is off, down, or refused, the e-mail uses the fixed wording (plain_wording). So an
   invitation is always sent, and a bulk send never stops because the AI is busy.
"""

import logging
import re

from pydantic import BaseModel, Field

from app import company_profile
from app.llm import LLMUnavailable, ask_llm
from app.settings import settings

log = logging.getLogger("talentsight")


class InviteWording(BaseModel):
    subject: str = Field(description="The e-mail subject, one line, with the company name and the position")
    intro: str = Field(description="2 to 3 sentences shown under the greeting")
    closing: str = Field(description="One sentence shown before the sign-off")


MAIL_PROMPT = (
    "You write the wording of a formal interview invitation e-mail for the HR team of a company. "
    "Write in plain, polite, professional English: warm, but not casual and not salesy. "
    "You write only three parts. (1) subject: one line with the company name and the position. "
    "(2) intro: 2 to 3 sentences shown right under the greeting. (3) closing: one short sentence shown "
    "before the sign-off. "
    "The e-mail already contains the greeting, a table with the date, time and length, the join button "
    "and link, the rules, the contact line and the sign-off, all written by the system. So never write "
    "dates, times, lengths, numbers, links, e-mail addresses, or names of other people. Never mention scores, "
    "the candidate's CV, or how they compared with others. "
    "Use the company name and the position you are given, exactly as given. "
    "If the situation is 'first invitation': thank the candidate for applying and invite them to an online "
    "video interview as the next step. "
    "If the situation is 'moved': say the interview has been moved to a new time, that the link stays the "
    "same, and that the new details are below. "
    "Do not promise a job. Do not ask the candidate to reply or confirm."
)

# What the e-mail says when the AI is off, down, or its text was refused.
def plain_wording(company: str, title: str, rescheduled: bool) -> InviteWording:
    if rescheduled:
        return InviteWording(
            subject=f"Interview rescheduled at {company}: {title}",
            intro=(
                f"Your video interview for the {title} position has been moved to a new time. "
                "Your link stays the same. Please see the new details below."
            ),
            closing="We look forward to meeting you.",
        )
    return InviteWording(
        subject=f"Invitation for Interview at {company}: {title}",
        intro=(
            f"We hope this e-mail finds you well. Thank you for applying for the {title} position. "
            "As the next step of our selection process, we would like to invite you to a video interview."
        ),
        closing="We look forward to meeting you.",
    )


def _facts(company: str, name: str, title: str, rescheduled: bool) -> str:
    situation = "moved" if rescheduled else "first invitation"
    return (
        f"Company: {company}\nCandidate: {name or 'not known'}\nPosition: {title}\n"
        f"Interview: online video interview\nSituation: {situation}"
    )


def problem_with(wording: InviteWording, company: str, name: str, title: str) -> str:
    """Why this text may not be used, or "" when it is fine. The checks are plain code, not the AI."""
    parts = {"subject": wording.subject, "intro": wording.intro, "closing": wording.closing}
    for label, text in parts.items():
        if "http" in text.lower() or "www." in text.lower() or "@" in text:
            return f"the {label} has a link or an e-mail address"
        # Numbers are only allowed when they belong to the company or the position (for example "Java 17").
        rest = text
        for allowed in (company, title, name):
            if allowed:
                rest = re.sub(re.escape(allowed), "", rest, flags=re.IGNORECASE)
        if re.search(r"\d", rest):
            return f"the {label} has a number (dates and times are filled in by the system)"
    if "\n" in wording.subject.strip() or not 8 <= len(wording.subject.strip()) <= 120:
        return "the subject is not one sensible line"
    if not 40 <= len(wording.intro.strip()) <= 700:
        return "the intro has the wrong length"
    if not 5 <= len(wording.closing.strip()) <= 200:
        return "the closing has the wrong length"
    return ""


def write_invite(candidate_name: str, job_title: str, rescheduled: bool) -> tuple[InviteWording, str]:
    """The wording for one invitation, and where it came from: "ai" or "template". Never raises."""
    company = company_profile.current().name
    title = company_profile.one_line(job_title)[:120]
    name = company_profile.one_line(candidate_name)[:80]
    fallback = plain_wording(company, title, rescheduled)

    if not settings.ai_mail or not settings.groq_api_key.strip():
        return fallback, "template"
    try:
        wording = ask_llm(MAIL_PROMPT, _facts(company, name, title, rescheduled), InviteWording)
    except LLMUnavailable:
        log.warning("invite wording: AI not available, fixed wording used", extra={"event": "invite_wording_fallback", "why": "ai_down"})
        return fallback, "template"

    wording = InviteWording(
        subject=company_profile.one_line(wording.subject),
        intro=company_profile.one_line(wording.intro),
        closing=company_profile.one_line(wording.closing),
    )
    why = problem_with(wording, company, name, title)
    if why:
        log.warning(f"invite wording refused: {why}", extra={"event": "invite_wording_fallback", "why": why})
        return fallback, "template"
    log.info("invite wording written by the AI", extra={"event": "invite_wording_ai"})
    return wording, "ai"
