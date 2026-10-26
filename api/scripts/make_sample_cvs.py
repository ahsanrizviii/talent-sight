"""Makes 20 sample CVs (fictional people) to test screening: 10 PDF, 9 DOCX and 1 scanned PDF.

Run: docker compose exec api python -m scripts.make_sample_cvs /data/cv_uploads/samples
Then: docker compose cp api:/data/cv_uploads/samples ./sample-cvs

They fit the job "Mid-level Backend Developer": Python, SQL, 3+ years, a CS degree.
"""
import io
import sys
from pathlib import Path

from docx import Document
from PIL import Image, ImageDraw, ImageFont

# name, years, skills, degree. Some miss a mandatory requirement on purpose.
PEOPLE = [
    ("Ayesha Rahman", 5, "Python, Django, PostgreSQL, Docker, REST APIs", "BSc in Computer Science and Engineering"),
    ("Tanvir Hasan", 4, "Python, FastAPI, MySQL, Redis", "BSc in Computer Science"),
    ("Nusrat Jahan", 3, "Python, Flask, SQL Server, Git", "BSc in Software Engineering"),
    ("Rafiq Ahmed", 7, "Java, Spring Boot, Oracle SQL, Kubernetes", "BSc in Computer Science"),
    ("Sadia Islam", 2, "Python, pandas, SQLite", "BSc in Computer Science"),
    ("Imran Chowdhury", 6, "Python, Django, PostgreSQL, AWS, Docker", "MSc in Computer Science"),
    ("Farhana Akter", 4, "PHP, Laravel, MySQL", "BSc in Information Technology"),
    ("Mahmud Karim", 3, "Python, FastAPI, PostgreSQL, Celery", "BSc in Electrical and Electronic Engineering"),
    ("Shirin Sultana", 8, "Python, Go, PostgreSQL, Docker, Terraform", "BSc in Computer Science"),
    ("Arif Hossain", 1, "JavaScript, React, Node.js", "Diploma in Computer Technology"),
    ("Lamia Haque", 5, "C#, .NET, SQL Server", "BSc in Computer Science"),
    ("Zahid Hasan", 3, "Python, Django, MySQL, Docker", "BSc in Computer Science and Engineering"),
    ("Mitu Rani Das", 4, "Python, Flask, MongoDB", "BSc in Computer Science"),
    ("Kamrul Islam", 6, "Python, FastAPI, PostgreSQL, Kafka", "BSc in Computer Science"),
    ("Rumana Ferdous", 3, "Python, SQL, data pipelines, Airflow", "BSc in Statistics"),
    ("Sabbir Rahman", 5, "Ruby on Rails, PostgreSQL", "BSc in Computer Science"),
    ("Tahmina Begum", 2, "Python, Django, PostgreSQL", "BSc in Computer Science"),
    ("Nayeem Uddin", 9, "Python, Java, Oracle, microservices, Docker", "MSc in Software Engineering"),
    ("Priya Saha", 3, "Python, FastAPI, PostgreSQL, Docker", "BSc in Computer Science"),
    ("Jamil Akhtar", 4, "Python, SQL, REST APIs, Linux", "BSc in Computer Science"),
]


def cv_lines(index: int, name: str, years: int, skills: str, degree: str) -> list[str]:
    email = name.lower().replace(" ", ".") + "@example.com"
    return [
        name,
        f"Email: {email} Phone: +880 1700-0000{index:02d}",
        "",
        "SUMMARY",
        f"Software developer with {years} years of experience.",
        "",
        "SKILLS",
        skills,
        "",
        "EXPERIENCE",
        f"Software Engineer, Example Tech Ltd, Dhaka ({2026 - years} - present)",
        f"Built and maintained backend services using {skills.split(', ')[0]}.",
        "",
        "EDUCATION",
        f"{degree}, Example University, {2026 - years - 1}",
        "",
        "PROJECTS",
        "Internal HR portal: designed the database and the REST API.",
    ]


def make_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with a real text layer, written by hand (no extra library needed)."""

    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    text = (
        "BT /F1 11 Tf 50 790 Td 15 TL "
        + " ".join(f"({escape(line)}) Tj T*" for line in lines)
        + " ET"
    )
    stream = text.encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def make_docx(lines: list[str]) -> bytes:
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_scanned_pdf(lines: list[str]) -> bytes:
    """A PDF that is only a picture of the text, like a scanned paper CV (needs OCR)."""
    image = Image.new("L", (1240, 1754), 255)  # an A4 page at 150 dots per inch
    draw, font = ImageDraw.Draw(image), ImageFont.load_default(size=30)
    for number, line in enumerate(lines):
        draw.text((90, 90 + number * 46), line, fill=0, font=font)
    buffer = io.BytesIO()
    image.save(buffer, "PDF", resolution=150)
    return buffer.getvalue()


def main(folder: str) -> None:
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    for index, (name, years, skills, degree) in enumerate(PEOPLE, start=1):
        lines = cv_lines(index, name, years, skills, degree)
        stem = f"{index:02d}-{name.lower().replace(' ', '-')}"
        if index == 20:
            (out / f"{stem}-scanned.pdf").write_bytes(make_scanned_pdf(lines))
        elif index % 2:
            (out / f"{stem}.pdf").write_bytes(make_pdf(lines))
        else:
            (out / f"{stem}.docx").write_bytes(make_docx(lines))
    print(f"20 sample CVs written to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sample-cvs")