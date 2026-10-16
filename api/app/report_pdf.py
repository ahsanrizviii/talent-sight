"""The assessment report as a PDF file (Module 10, Task 10.2.1).

Built on the server with ReportLab, so the file looks the same on every computer and can be
attached to an e-mail or printed. It holds exactly what the report screen shows, evidence ids
included, and the numbered evidence at the end so every tag can be looked up on paper.
"""

from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#1d1f24")
FAINT = colors.HexColor("#6b6f78")
LINE = colors.HexColor("#d9dbe0")
TONE = {"strong_fit": "#2f7d4f", "possible_fit": "#a8681c", "weak_fit": "#b23b35"}
VERDICT = {"met": "Met", "partially_met": "Partly met", "unmet": "Unmet"}
INTERVIEW = {"explored": "Explored", "weak": "Weak evidence", "not_explored": "Not explored"}

TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=INK, spaceAfter=3)
SUB = ParagraphStyle("sub", fontName="Helvetica", fontSize=9.5, leading=13, textColor=FAINT, spaceAfter=12)
HEAD = ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=INK, spaceBefore=12, spaceAfter=5)
BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8.5, leading=11.5, textColor=FAINT)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8.5, leading=11)
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=10, bulletIndent=0, spaceAfter=3)


def safe(text) -> str:
    """Text for a Paragraph: XML special characters escaped, and characters the built-in PDF
    fonts cannot draw (for example Bangla or Chinese) shown as "?" instead of an empty box."""
    plain = " ".join(str(text or "").split())
    return escape(plain.encode("cp1252", errors="replace").decode("cp1252"))


def cite(ids: list[str]) -> str:
    return f' <font color="#6b6f78" size="8">[{", ".join(ids)}]</font>' if ids else ""


def when(value: str | None) -> str:
    if not value:
        return ""
    return datetime.fromisoformat(value).strftime("%d %b %Y")


def table(rows: list[list], widths: list[float]) -> Table:
    grid = Table(rows, colWidths=widths, repeatRows=1)
    grid.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), FAINT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return grid


def findings(title: str, items: list[dict]) -> list:
    parts = [Paragraph(safe(title), HEAD)]
    if not items:
        return parts + [Paragraph("Nothing to report.", SMALL)]
    return parts + [Paragraph(safe(item["text"]) + cite(item["evidence"]), BULLET, bulletText="•") for item in items]


def footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(FAINT)
    canvas.drawString(18 * mm, 10 * mm, "TalentSight · Confidential: for the hiring team only")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {document.page}")
    canvas.restoreState()


def build_pdf(report: dict, finished_at: datetime | None = None) -> bytes:
    """The whole report as PDF bytes."""
    position = report["position"]
    width = A4[0] - 36 * mm
    story: list = [
        Paragraph(f"Candidate assessment: {safe(report['candidate']['name'])}", TITLE),
        Paragraph(
            f"{safe(report['job']['title'])} · interview held {when(report['interview']['held_at'])}"
            + (f" · assessed {finished_at.strftime('%d %b %Y')}" if finished_at else ""),
            SUB,
        ),
        Paragraph(
            f'<font color="{TONE[position["code"]]}"><b>{safe(position["label"])}</b></font>'
            f" &nbsp; {position['overall']:g} / 100",
            ParagraphStyle("verdict", parent=TITLE, fontSize=15, leading=19),
        ),
    ]
    story += [Paragraph(safe(reason), SMALL) for reason in position["reasons"]]
    story += [Spacer(1, 6), Paragraph(safe(report["summary"]["text"]) + cite(report["summary"]["evidence"]), BODY)]

    story.append(Paragraph("Component scores", HEAD))
    rows = [["Part", "From", "Score", "Weight", "Adds", "Evidence"]]
    for part in report["components"]:
        rows.append([
            Paragraph(safe(part["label"]), CELL),
            "CV" if part["source"] == "cv" else "Interview",
            f"{part['score']:g}",
            f"{part['weight']}%",
            f"{part['contribution']:g}",
            Paragraph(safe(", ".join(part["evidence"])), CELL),
        ])
    story.append(table(rows, [0.32 * width, 0.11 * width, 0.09 * width, 0.09 * width, 0.08 * width, 0.31 * width]))

    story += findings("Strengths", report["strengths"])
    story += findings("Weaknesses", report["weaknesses"])
    gaps = [{"text": g["text"] + (" (must have)" if g["mandatory"] else ""), "evidence": g["evidence"]} for g in report["gaps"]]
    story += findings("Evidence gaps", gaps)
    story += findings("Verify next", report["follow_ups"])

    story.append(Paragraph("Requirements: CV and interview side by side", HEAD))
    rows = [["Requirement", "CV", "Interview", "Evidence"]]
    for line in report["requirements"]:
        interview = INTERVIEW.get(line["interview"], "—")
        if line["best_score"] is not None:
            interview += f" ({line['best_score']})"
        ids = ([f"R{line['n']}"] if line["cv"] else []) + ([f"C{line['n']}"] if line["interview"] else [])
        rows.append([
            Paragraph(safe(line["requirement"]) + (" <i>(must have)</i>" if line["mandatory"] else ""), CELL),
            VERDICT.get(line["cv"], "—"),
            interview,
            ", ".join(ids),
        ])
    story.append(table(rows, [0.46 * width, 0.15 * width, 0.24 * width, 0.15 * width]))

    rows = [["Id", "From", "What it says"]]
    for item in report["evidence"]:
        source = "CV" if item["source"] == "cv" else f"Interview{', ' + item['at'] if item['at'] else ''}"
        rows.append([item["id"], source, Paragraph(f"<b>{safe(item['label'])}</b><br/>{safe(item['text'])}", CELL)])
    story.append(KeepTogether([Paragraph("Evidence", HEAD), Paragraph("Every tag in this report points to one of these lines.", SMALL)]))
    story.append(table(rows, [0.08 * width, 0.17 * width, 0.75 * width]))

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title="Candidate assessment", author="TalentSight",
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()