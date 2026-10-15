"""Reads the text out of a CV file (WBS 5.2).

PDF: the text layer first. A scanned PDF has (almost) no text layer, so its pages
are turned into images and read with OCR (Tesseract). DOCX: paragraphs and tables.
"""
import re
from pathlib import Path

import pypdfium2
import pytesseract
from docx import Document
from pypdf import PdfReader

MIN_TEXT = 100
OCR_PAGES = 5


class CVReadError(ValueError):
    """No text could be read from the file. The message says why, for the interviewer."""


def tidy(text: str) -> str:
    """Removes extra spaces and empty lines."""
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def pdf_text(path: Path) -> str:
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise CVReadError("The PDF is password-protected.")
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def pdf_ocr(path: Path, lang: str = "eng") -> str:
    """lang is the Tesseract language, for example "eng", or "ben+eng" for Bangla and English."""
    pdf = pypdfium2.PdfDocument(path)
    try:
        pages = []
        for index in range(min(len(pdf), OCR_PAGES)):
            image = pdf[index].render(scale=300 / 72).to_pil()
            pages.append(pytesseract.image_to_string(image, lang=lang))
        return "\n".join(pages)
    finally:
        pdf.close()


def docx_text(path: Path) -> str:
    document = Document(path)
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def extract_text(path: Path) -> tuple[str, str]:
    """Returns (text, method). method is "text", or "ocr" for a scanned PDF."""
    try:
        if path.suffix == ".docx":
            text, method = tidy(docx_text(path)), "text"
        else:
            text, method = tidy(pdf_text(path)), "text"
        if len(text) < MIN_TEXT:
            text, method = tidy(pdf_ocr(path)), "ocr"
    except CVReadError:
        raise
    except Exception as error:
        raise CVReadError("The file is damaged or cannot be opened.") from error

    if not text:
        raise CVReadError("No text was found in the file.")
    return text, method