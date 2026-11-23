"""
document_reader.py - Extracts plain text from uploaded documents.

Supported: PDF (PyMuPDF), DOCX (python-docx), TXT and MD (read as text).
"""

import io
from pathlib import Path

import docx       # python-docx
import pymupdf    # PyMuPDF

SUPPORTED_TYPES = ["pdf", "docx", "txt", "md"]


def extract_text(file_name: str, file_bytes: bytes) -> str:
    """Return the text of a document given its name and raw bytes."""
    extension = Path(file_name).suffix.lower().lstrip(".")

    if extension == "pdf":
        text = _read_pdf(file_bytes)
    elif extension == "docx":
        text = _read_docx(file_bytes)
    elif extension in ("txt", "md"):
        # utf-8-sig also removes the invisible "BOM" some editors add.
        text = file_bytes.decode("utf-8-sig", errors="replace")
    else:
        raise ValueError(f"Unsupported file type '.{extension}'. "
                         f"Use one of: {', '.join(SUPPORTED_TYPES)}")

    text = text.strip()
    if not text:
        raise ValueError(f"No text found in {file_name}. (Scanned PDFs without a "
                         "text layer can't be read - OCR is not supported.)")
    return text


def _read_pdf(file_bytes: bytes) -> str:
    with pymupdf.open(stream=file_bytes, filetype="pdf") as pdf:
        return "\n\n".join(page.get_text() for page in pdf)


def _read_docx(file_bytes: bytes) -> str:
    document = docx.Document(io.BytesIO(file_bytes))
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    # Tables are common in requirement documents - keep their text too,
    # one row per line with cells separated by " | ".
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)
