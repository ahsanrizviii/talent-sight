"""The look of every e-mail TalentSight sends to candidates.

E-mail apps (Gmail, Outlook, Apple Mail) ignore most modern web styling, so the layout is built the
old, safe way: tables and inline styles. Every value that comes from data goes through escape(), so a
name or job title can never inject HTML.
"""

from html import escape

INK = "#1f2329"
MUTED = "#5f6670"
LINE = "#e6e2dc"
ACCENT = "#b8702f"  # TalentSight amber, darkened so white text on it is easy to read
WASH = "#fbf5ee"


def details_table(rows: list[tuple[str, str]]) -> str:
    """The 'Interview details' block: one label and value per line."""
    cells = "".join(
        f'<tr><td style="padding:6px 16px 6px 0;color:{MUTED};font-size:14px;white-space:nowrap;vertical-align:top">{escape(label)}</td>'
        f'<td style="padding:6px 0;color:{INK};font-size:14px;font-weight:600">{escape(value)}</td></tr>'
        for label, value in rows
    )
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;background:{WASH};'
        f'border:1px solid {LINE};border-radius:10px;margin:18px 0"><tr><td style="padding:14px 18px">'
        f'<div style="font-size:12px;letter-spacing:0.08em;color:{ACCENT};font-weight:700;margin-bottom:6px">INTERVIEW DETAILS</div>'
        f'<table role="presentation" cellpadding="0" cellspacing="0">{cells}</table></td></tr></table>'
    )


def button(label: str, link: str) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:22px 0 8px"><tr>'
        f'<td style="background:{ACCENT};border-radius:8px">'
        f'<a href="{escape(link)}" style="display:inline-block;padding:12px 26px;color:#ffffff;'
        f'font-size:15px;font-weight:600;text-decoration:none">{escape(label)}</a></td></tr></table>'
        f'<p style="margin:0 0 18px;font-size:12px;color:{MUTED}">If the button does not work, copy this link into your browser:<br>'
        f'<a href="{escape(link)}" style="color:{ACCENT};word-break:break-all">{escape(link)}</a></p>'
    )


def paragraph(text: str) -> str:
    return f'<p style="margin:0 0 14px;font-size:15px;line-height:1.55;color:{INK}">{escape(text)}</p>'


def notes(items: list[str]) -> str:
    lines = "".join(f'<li style="margin:0 0 6px">{escape(item)}</li>' for item in items)
    return f'<ul style="margin:0 0 16px;padding-left:20px;font-size:14px;line-height:1.5;color:{MUTED}">{lines}</ul>'


def page(company: str, heading: str, body: str, footer: str) -> str:
    """The frame: company name on top, a white card with the message, a small footer under it."""
    return (
        '<!doctype html><html><body style="margin:0;padding:0;background:#f3f1ee">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f1ee;padding:24px 12px">'
        '<tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;font-family:Arial,Helvetica,sans-serif">'
        f'<tr><td style="padding:4px 4px 14px;font-size:18px;font-weight:700;color:{INK}">{escape(company)}'
        f'<span style="font-size:12px;font-weight:400;color:{MUTED}">&nbsp;&nbsp;via TalentSight</span></td></tr>'
        f'<tr><td style="background:#ffffff;border:1px solid {LINE};border-radius:12px;padding:28px 28px 20px">'
        f'<h1 style="margin:0 0 18px;font-size:21px;line-height:1.3;color:{INK}">{escape(heading)}</h1>'
        f"{body}</td></tr>"
        f'<tr><td style="padding:16px 6px;font-size:12px;line-height:1.5;color:{MUTED};text-align:center">{footer}</td></tr>'
        "</table></td></tr></table></body></html>"
    )
