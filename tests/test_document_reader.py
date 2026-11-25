import io

import docx
import pymupdf
import pytest

from document_reader import extract_text


def test_txt_with_bom():
    assert extract_text("a.txt", "﻿Hello".encode("utf-8")) == "Hello"


def test_md_is_read_as_text():
    assert extract_text("a.MD", b"# Title\nBody") == "# Title\nBody"


def test_unsupported_extension():
    with pytest.raises(ValueError, match="Unsupported"):
        extract_text("a.xlsx", b"data")


def test_empty_document_raises():
    with pytest.raises(ValueError, match="No text found"):
        extract_text("a.txt", b"   \n ")


def test_docx_paragraphs_and_tables():
    document = docx.Document()
    document.add_paragraph("Loan limit policy")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Max amount"
    table.rows[0].cells[1].text = "50,000"
    buffer = io.BytesIO()
    document.save(buffer)

    text = extract_text("spec.docx", buffer.getvalue())
    assert "Loan limit policy" in text
    assert "Max amount | 50,000" in text


def test_pdf_text_layer():
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "KYC must be completed")
    data = pdf.tobytes()
    pdf.close()
    assert "KYC must be completed" in extract_text("doc.pdf", data)
