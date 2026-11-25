"""
artefacts/document.py - A tiny document model, rendered to Markdown and DOCX,
so each document's content is written once.

A Document is a list of blocks:
  ("heading", level, text) | ("para", text) | ("bullets", [text])
  ("table", [headers], [[cells]]) | ("note", text)
"""

import io

import docx
from docx.shared import Pt, RGBColor


def _plain(text: str) -> str:
    """Markdown emphasis markers are not shown in Word."""
    return text.replace("**", "")


class Document:
    def __init__(self, title: str, subtitle: str = ""):
        self.title = title
        self.subtitle = subtitle
        self.blocks: list[tuple] = []

    def heading(self, text: str, level: int = 1):
        self.blocks.append(("heading", level, text))

    def para(self, text: str):
        if text:
            self.blocks.append(("para", text))

    def bullets(self, items):
        items = [i for i in items if i]
        if items:
            self.blocks.append(("bullets", items))

    def table(self, headers: list[str], rows: list[list]):
        self.blocks.append(("table", headers, [[str(c) if c is not None else "" for c in r] for r in rows]))

    def note(self, text: str):
        self.blocks.append(("note", text))

    # ------------------------------------------------------------ Markdown --
    def to_markdown(self) -> str:
        out = [f"# {self.title}"]
        if self.subtitle:
            out.append(f"_{self.subtitle}_")
        for block in self.blocks:
            kind = block[0]
            if kind == "heading":
                out.append(f"{'#' * (block[1] + 1)} {block[2]}")
            elif kind == "para":
                out.append(block[1])
            elif kind == "note":
                out.append(f"> {block[1]}")
            elif kind == "bullets":
                out.append("\n".join(f"- {item}" for item in block[1]))
            elif kind == "table":
                headers, rows = block[1], block[2]

                def cell(value):
                    return str(value).replace("|", "\\|").replace("\n", "<br>")
                lines = ["| " + " | ".join(map(cell, headers)) + " |",
                         "|" + "---|" * len(headers)]
                lines += ["| " + " | ".join(map(cell, row)) + " |" for row in rows]
                out.append("\n".join(lines))
        return "\n\n".join(out) + "\n"

    # ---------------------------------------------------------------- DOCX --
    def to_docx(self) -> bytes:
        document = docx.Document()
        document.add_heading(self.title, level=0)
        if self.subtitle:
            run = document.add_paragraph().add_run(self.subtitle)
            run.italic = True
        for block in self.blocks:
            kind = block[0]
            if kind == "heading":
                document.add_heading(block[2], level=min(block[1], 4))
            elif kind == "para":
                document.add_paragraph(_plain(block[1]))
            elif kind == "note":
                run = document.add_paragraph().add_run(_plain(block[1]))
                run.italic = True
                run.font.color.rgb = RGBColor(0x8A, 0x4B, 0x00)
            elif kind == "bullets":
                for item in block[1]:
                    document.add_paragraph(_plain(item), style="List Bullet")
            elif kind == "table":
                headers, rows = block[1], block[2]
                table = document.add_table(rows=1, cols=len(headers))
                table.style = "Table Grid"
                for cell, header in zip(table.rows[0].cells, headers):
                    cell.text = header
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.bold = True
                for row in rows:
                    cells = table.add_row().cells
                    for cell, value in zip(cells, row):
                        cell.text = value
                for row in table.rows:
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            for run in paragraph.runs:
                                run.font.size = Pt(9)
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()
