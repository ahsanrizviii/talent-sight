"""The AI writes the wording of the candidate e-mails: the interview invitation (for each round),
the rejection and the onboarding e-mail.

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
    "If the situation is 'next round': congratulate the candidate on passing the previous round and invite them "
    "to the next one. When a round name is given, use it exactly as given in the subject and the intro, and say "
    "in a few words what the round covers when that is given. "
    "Do not promise a job. Do not ask the candidate to reply or confirm."
)

# What the e-mail says when the AI is off, down, or its text was refused.
def plain_wording(company: str, title: str, rescheduled: bool, round_name: str = "", next_round: bool = False) -> InviteWording:
    what = f"the {round_name}" if round_name else "a video interview"
    if rescheduled:
        return InviteWording(
            subject=f"Interview rescheduled at {company}: {title}",
            intro=(
                f"Your video interview for the {title} position has been moved to a new time. "
                "Your link stays the same. Please see the new details below."
            ),
            closing="We look forward to meeting you.",
        )
    if next_round:
        return InviteWording(
            subject=f"Next interview at {company}: {title}" + (f", {round_name}" if round_name else ""),
            intro=(
                f"Congratulations on passing the previous round for the {title} position. "
                f"We would like to invite you to {what}, the next step of our selection process."
            ),
            closing="We look forward to meeting you again.",
        )
    return InviteWording(
        subject=f"Invitation for Interview at {company}: {title}",
        intro=(
            f"We hope this e-mail finds you well. Thank you for applying for the {title} position. "
            f"As the next step of our selection process, we would like to invite you to {what}."
        ),
        closing="We look forward to meeting you.",
    )


def _facts(company: str, name: str, title: str, rescheduled: bool, round_name: str = "", round_focus: str = "", next_round: bool = False) -> str:
    situation = "moved" if rescheduled else "next round" if next_round else "first invitation"
    facts = (
        f"Company: {company}\nCandidate: {name or 'not known'}\nPosition: {title}\n"
        f"Interview: online video interview\nSituation: {situation}"
    )
    if round_name:
        facts += f"\nRound name: {round_name}"
    if round_focus:
        facts += f"\nWhat the round covers: {round_focus}"
    return facts


def problem_with(wording: InviteWording, company: str, name: str, title: str, *extra_allowed: str) -> str:
    """Why this text may not be used, or "" when it is fine. The checks are plain code, not the AI."""
    parts = {"subject": wording.subject, "intro": wording.intro, "closing": wording.closing}
    for label, text in parts.items():
        if "http" in text.lower() or "www." in text.lower() or "@" in text:
            return f"the {label} has a link or an e-mail address"
        # Numbers are only allowed when they belong to the company, the position or the round
        # (for example "Java 17" or "Technical round 1").
        rest = text
        for allowed in (company, title, name, *extra_allowed):
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


def write_invite(
    candidate_name: str,
    job_title: str,
    rescheduled: bool,
    round_name: str = "",
    round_focus: str = "",
    next_round: bool = False,
) -> tuple[InviteWording, str]:
    """The wording for one invitation, and where it came from: "ai" or "template". Never raises.
    round_name and round_focus say which interview round it is; next_round = a round after the first."""
    company = company_profile.current().name
    title = company_profile.one_line(job_title)[:120]
    name = company_profile.one_line(candidate_name)[:80]
    round_name = company_profile.one_line(round_name)[:80]
    round_focus = company_profile.one_line(round_focus)[:300]
    fallback = plain_wording(company, title, rescheduled, round_name, next_round)

    if not settings.ai_mail or not settings.groq_api_key.strip():
        return fallback, "template"
    try:
        wording = ask_llm(MAIL_PROMPT, _facts(company, name, title, rescheduled, round_name, round_focus, next_round), InviteWording)
    except LLMUnavailable:
        log.warning("invite wording: AI not available, fixed wording used", extra={"event": "invite_wording_fallback", "why": "ai_down"})
        return fallback, "template"

    wording = InviteWording(
        subject=company_profile.one_line(wording.subject),
        intro=company_profile.one_line(wording.intro),
        closing=company_profile.one_line(wording.closing),
    )
    why = problem_with(wording, company, name, title, round_name, round_focus)
    if why:
        log.warning(f"invite wording refused: {why}", extra={"event": "invite_wording_fallback", "why": why})
        return fallback, "template"
    log.info("invite wording written by the AI", extra={"event": "invite_wording_ai"})
    return wording, "ai"


# ---------- The rejection and the onboarding e-mail ----------

OUTCOME_PROMPT = (
    "You write the wording of a short, formal e-mail from the HR team of a company to a job candidate. "
    "Write in plain, polite, professional English: warm and respectful, not casual and not salesy. "
    "You write only three parts. (1) subject: one line with the company name and the position. "
    "(2) intro: 2 to 4 sentences shown right under the greeting. (3) closing: one short sentence shown "
    "before the sign-off. The greeting, the contact line and the sign-off are written by the system. "
    "Never write dates, times, numbers, links, e-mail addresses, or names of other people. Never mention "
    "scores, rankings, the CV, other candidates or the reasons for the decision. "
    "Use the company name, the position and the round name you are given, exactly as given. "
    "If the situation is 'not selected': thank the candidate for their time and interest, say kindly that the "
    "company will not continue with their application for this position (after the round named, when one is "
    "given), and wish them well. Do not invite them to reply. "
    "If the situation is 'selected': congratulate the candidate on being selected for the position, say the "
    "hiring team will contact them about the next steps and their first day, and ask them to bring their "
    "original photo ID on their first day for a short identity check. Do not ask them to reply or confirm."
)


def plain_outcome(company: str, title: str, kind: str, round_name: str = "") -> InviteWording:
    """The fixed wording of a rejection or an onboarding e-mail, used when the AI is off or refused."""
    if kind == "onboarding":
        return InviteWording(
            subject=f"Congratulations from {company}: {title}",
            intro=(
                f"We are pleased to tell you that you have been selected for the {title} position. "
                "Our hiring team will contact you about the next steps and your first day. "
                "Please bring your original photo ID on your first day for a short identity check."
            ),
            closing="We look forward to welcoming you to the team.",
        )
    after = f" after the {round_name}" if round_name else " after our final review"
    return InviteWording(
        subject=f"Your application at {company}: {title}",
        intro=(
            f"Thank you for your time and interest in the {title} position. "
            f"We regret to tell you that we will not continue with your application{after}. "
            "We wish you every success in your search."
        ),
        closing="Thank you again for considering us.",
    )


def write_outcome(candidate_name: str, job_title: str, kind: str, round_name: str = "") -> tuple[InviteWording, str]:
    """The wording of a rejection (kind "rejection") or onboarding e-mail, and "ai" or "template". Never raises."""
    company = company_profile.current().name
    title = company_profile.one_line(job_title)[:120]
    name = company_profile.one_line(candidate_name)[:80]
    round_name = company_profile.one_line(round_name)[:80]
    fallback = plain_outcome(company, title, kind, round_name)

    if not settings.ai_mail or not settings.groq_api_key.strip():
        return fallback, "template"
    situation = "selected" if kind == "onboarding" else "not selected"
    facts = f"Company: {company}\nCandidate: {name or 'not known'}\nPosition: {title}\nSituation: {situation}"
    if round_name and kind != "onboarding":
        facts += f"\nLast round they took part in: {round_name}"
    try:
        wording = ask_llm(OUTCOME_PROMPT, facts, InviteWording)
    except LLMUnavailable:
        log.warning("outcome wording: AI not available, fixed wording used", extra={"event": "outcome_wording_fallback", "why": "ai_down"})
        return fallback, "template"

    wording = InviteWording(
        subject=company_profile.one_line(wording.subject),
        intro=company_profile.one_line(wording.intro),
        closing=company_profile.one_line(wording.closing),
    )
    why = problem_with(wording, company, name, title, round_name)
    if why:
        log.warning(f"outcome wording refused: {why}", extra={"event": "outcome_wording_fallback", "why": why})
        return fallback, "template"
    return wording, "ai"
