"""
artefacts/bundle.py - Every artefact of a run as {file name: bytes}, plus a ZIP.
"""

import io
import zipfile

import audit_log
from artefacts import documents, process_flow, registers
from artefacts.data import collect

# File name -> description (also the order of the download buttons).
DESCRIPTIONS = {
    "srs.docx": "Software Requirements Specification (IEEE 830 structure, Word)",
    "srs.md": "Software Requirements Specification (Markdown)",
    "user_stories.md": "User stories with acceptance criteria",
    "use_cases.md": "Use-case descriptions",
    "process_flowchart.md": "Process workflow flowchart linked to requirement IDs (Mermaid in Markdown)",
    "process_flowchart.mmd": "Process workflow flowchart (Mermaid source)",
    "data_interface_requirements.md": "Data and interface requirements",
    "traceability_matrix.xlsx": "Requirements traceability matrix (Excel)",
    "traceability_matrix.csv": "Requirements traceability matrix (CSV)",
    "compliance_control_matrix.xlsx": "Compliance-control matrix (Excel)",
    "compliance_control_matrix.csv": "Compliance-control matrix (CSV)",
    "risk_register.xlsx": "Threat and risk register (Excel)",
    "risk_register.csv": "Threat and risk register (CSV)",
    "assumptions_dependencies.xlsx": "Assumptions and dependencies register (Excel)",
    "assumptions_dependencies.csv": "Assumptions and dependencies register (CSV)",
    "open_issues.xlsx": "Open-issues list (Excel)",
    "open_issues.csv": "Open-issues list (CSV)",
}


def generate(result, user: str | None = None) -> dict[str, bytes]:
    data = collect(result)
    srs = documents.srs(data)
    flow = process_flow.build_flow(data.requirements, "Loan application" if "loan" in data.scenario.lower()
                                   else "Process")
    files = {
        "srs.docx": srs.to_docx(),
        "srs.md": srs.to_markdown().encode("utf-8"),
        "user_stories.md": documents.user_stories(data).to_markdown().encode("utf-8"),
        "use_cases.md": documents.use_cases(data).to_markdown().encode("utf-8"),
        "process_flowchart.md": process_flow.to_markdown(flow, "Loan" if "loan" in data.scenario.lower()
                                                         else "Business", data.status_note).encode("utf-8"),
        "process_flowchart.mmd": process_flow.to_mermaid(flow).encode("utf-8"),
        "data_interface_requirements.md": documents.data_interface_requirements(data).to_markdown().encode("utf-8"),
    }
    for name, builder in registers.ALL_REGISTERS:
        table = builder(data)
        files[f"{name}.xlsx"] = registers.to_xlsx(table, data)
        files[f"{name}.csv"] = registers.to_csv(table)
    audit_log.log_event(result.run_id, "artefacts_generated", user=user, draft=data.draft,
                        requirements=len(data.requirements), files=sorted(files))
    return {name: files[name] for name in DESCRIPTIONS}


def zip_all(files: dict[str, bytes], run_id: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(f"artefacts_{run_id}/{name}", content)
    return buffer.getvalue()
