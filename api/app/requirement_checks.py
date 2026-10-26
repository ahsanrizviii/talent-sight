"""Which job requirements an interview can test (hiring rounds update). Plain code, no AI.

Degrees, certificates and written skills cannot be shown in a spoken interview: the CV screening
scores them, and the hiring team checks the documents on the onboarding day. So the interview
analysis marks them "documents" instead of "not explored", and they never count against the
interview coverage, the interview score, the quality review or the report's follow-ups.
"""

import re

# The coverage status of a requirement that is checked with documents, not in the interview.
DOCUMENTS = "documents"

DOCUMENT_WORDS = re.compile(
    r"(?<![a-z])(degree|bachelor'?s?|master'?s?|diploma|certificat\w*|certified|written)(?![a-z])",
    re.IGNORECASE,
)


def checked_by_documents(requirement: dict) -> bool:
    """True for a qualification, or a requirement that names a degree, a certificate or a written skill.
    HR topics are never document checks."""
    kind = requirement.get("kind")
    if kind == "hr_topic":
        return False
    return kind == "qualification" or bool(DOCUMENT_WORDS.search(str(requirement.get("requirement") or "")))


def interview_items(coverage: list[dict]) -> list[dict]:
    """The coverage lines an interview can explore: everything except the document checks (also in an
    analysis made before document checks existed, where a degree could still say "weak")."""
    return [item for item in coverage or [] if item.get("status") != DOCUMENTS and not checked_by_documents(item)]
