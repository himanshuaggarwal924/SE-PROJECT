"""
artefacts/registers.py - Tabular artefacts (rows) and their XLSX / CSV writers.

  traceability_matrix()      requirement -> source stakeholder/statement ->
                             citations -> compliance controls -> SDLC factor
                             evidence -> tests / acceptance criteria
  compliance_control_matrix()
  risk_register()            threats (from security/privacy/integration
                             categories) + requirement, compliance and quality risks
  assumptions_dependencies()
  open_issues()              unresolved quality issues and clarification questions
"""

import csv
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from artefacts.data import ArtefactData

LEVEL = {"High": 3, "Medium": 2, "Low": 1}
THREATS = {"security": "Unauthorised access or tampering", "privacy": "Disclosure of personal data",
           "integration": "Interface spoofing or corrupted data exchange",
           "availability/reliability": "Service outage (denial of service)",
           "data-management": "Loss or corruption of records"}


class Table:
    def __init__(self, name: str, headers: list[str], rows: list[list]):
        self.name, self.headers = name, headers
        self.rows = [[("" if c is None else c) for c in row] for row in rows]


def traceability_matrix(data: ArtefactData) -> Table:
    rows = []
    for r in data.requirements:
        mapping = data.mapping(r.id)
        rows.append([r.id, r.kind.replace("_", "-"), r.statement, r.source_stakeholder or "—",
                     data.source_statement(r), "; ".join(data.citations(r)) or "—",
                     "; ".join(data.citation(c) for c in r.applicable_rules) or "—",
                     "; ".join(mapping.required_controls) if mapping else "—",
                     "; ".join(data.factor_evidence(r.id)) or "—",
                     "\n".join(data.acceptance_tests(r)) or "—",
                     r.priority, r.risk_level, round(r.confidence, 2), data.approval(r), r.version])
    return Table("Traceability matrix",
                 ["Requirement", "Type", "Statement", "Source stakeholder", "Source statement", "Citations",
                  "Applicable rules", "Compliance controls", "SDLC factor evidence",
                  "Tests / acceptance criteria", "Priority", "Risk", "Confidence", "Approval", "Version"], rows)


def compliance_control_matrix(data: ArtefactData) -> Table:
    rows = []
    included = {r.id for r in data.requirements}
    for m in (data.compliance.mappings if data.compliance else []):
        if m.requirement_id not in included:
            continue
        rows.append([m.requirement_id, "; ".join(data.citation(c) for c in m.applicable_rules) or "—",
                     "; ".join(m.required_controls) or "—", "; ".join(data.citation(c) for c in m.evidence) or "—",
                     "; ".join(m.compliance_gaps) or "—", "; ".join(m.approval_checkpoints) or "—",
                     "; ".join(m.retention_reporting_obligations) or "—", m.impact,
                     "yes" if m.requires_compliance_officer_approval else "no", data.approval(m)])
    for s in (data.compliance.suggested_requirements if data.compliance else []):
        rows.append([s.id, "; ".join(data.citation(c) for c in s.sources) or "—", s.statement, "—",
                     s.rationale, "—", "—", "High", "yes", s.status])
    return Table("Compliance-control matrix",
                 ["Requirement", "Rules (KB)", "Required controls", "Evidence", "Gaps", "Approval checkpoints",
                  "Retention / reporting", "Impact", "Officer approval needed", "Status"], rows)


def _rating(likelihood: str, impact: str) -> str:
    score = LEVEL[likelihood] * LEVEL[impact]
    return f"{score} ({'High' if score >= 6 else 'Medium' if score >= 3 else 'Low'})"


def risk_register(data: ArtefactData) -> Table:
    rows = []

    def add(source, kind, description, likelihood, impact, mitigation, owner):
        rows.append([f"R-{len(rows) + 1:02d}", source, kind, description, likelihood, impact,
                     _rating(likelihood, impact), mitigation, owner, "Open"])

    for r in data.requirements:
        mapping = data.mapping(r.id)
        controls = "; ".join(mapping.required_controls) if mapping and mapping.required_controls else ""
        for category, threat in THREATS.items():
            if category in r.categories:
                add(r.id, "Threat", f"{threat} affecting: {r.statement}",
                    "Medium" if r.risk_level != "High" else "High", r.risk_level,
                    controls or "; ".join(data.acceptance_tests(r))[:300] or "Define controls", data.owner(r))
        if r.confidence < 0.6 or r.needs_human_review:
            add(r.id, "Requirement risk", f"Requirement may be wrong or unsupported (confidence {r.confidence:.2f})",
                "High", r.risk_level, "Confirm with the source stakeholder; fix flagged citations/numbers",
                "Business analyst")
    for m in (data.compliance.mappings if data.compliance else []):
        for gap in m.compliance_gaps:
            add(m.requirement_id, "Compliance gap", gap, "Medium", m.impact,
                "Address in design; confirm with compliance officer", "Compliance officer")
    for review in (data.quality.reviews if data.quality else []):
        for issue in review.issues:
            if issue.severity == "High":
                add(review.requirement_id, "Quality defect", f"{issue.type.replace('_', ' ')}: {issue.explanation}",
                    "High", "Medium", "Resolve before baseline / ask the clarification question", "Business analyst")
    return Table("Threat and risk register",
                 ["ID", "Source", "Kind", "Threat / risk", "Likelihood", "Impact", "Rating", "Mitigation",
                  "Owner", "Status"], rows)


def assumptions_dependencies(data: ArtefactData) -> Table:
    rows = []
    for a in data.assumptions:
        rows.append([f"A-{len(rows) + 1:02d}", "Assumption", "Run", a, "Open"])
    for r in data.requirements:
        for a in r.assumptions:
            if a not in data.assumptions:
                rows.append([f"A-{len(rows) + 1:02d}", "Assumption", r.id, a, "Open"])
        for dep in r.dependencies:
            rows.append([f"D-{len(rows) + 1:02d}", "Dependency", r.id, f"{r.id} depends on {dep}", "Open"])
    return Table("Assumptions and dependencies", ["ID", "Type", "Requirement", "Description", "Status"], rows)


def open_issues(data: ArtefactData) -> Table:
    rows = []
    included = {r.id for r in data.requirements}
    for review in (data.quality.reviews if data.quality else []):
        if review.requirement_id not in included:
            continue
        for issue in review.issues:
            rows.append([f"OI-{len(rows) + 1:02d}", review.requirement_id, issue.type.replace("_", " "),
                         issue.severity, issue.explanation, "", "", "rule" if issue.origin == "rule" else "AI", "Open"])
        for q in review.clarification_questions:
            rows.append([f"OI-{len(rows) + 1:02d}", review.requirement_id, "clarification question", "Medium",
                         "", q.question, q.stakeholder_role, "AI", "Open"])
    for pair in (data.quality.conflicts if data.quality else []):
        rows.append([f"OI-{len(rows) + 1:02d}", " / ".join(pair["ids"]), "conflict", "High", pair["detail"],
                     "Which value is correct?", "Product owner", "rule", "Open"])
    return Table("Open issues", ["ID", "Requirement", "Type", "Severity", "Description", "Question",
                                 "Ask", "Found by", "Status"], rows)


ALL_REGISTERS = [("traceability_matrix", traceability_matrix),
                 ("compliance_control_matrix", compliance_control_matrix),
                 ("risk_register", risk_register),
                 ("assumptions_dependencies", assumptions_dependencies),
                 ("open_issues", open_issues)]


# ------------------------------------------------------------------- writers --
def to_csv(table: Table) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(table.headers)
    writer.writerows(table.rows)
    return buffer.getvalue().encode("utf-8-sig")       # BOM so Excel opens UTF-8 correctly


def to_xlsx(table: Table, data: ArtefactData) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = table.name[:31]
    sheet.append(table.headers)
    for row in table.rows:
        sheet.append(row)
    header_fill = PatternFill("solid", fgColor="1F6FEB")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
    for column in sheet.columns:
        longest = max(len(str(c.value or "")) for c in column)
        sheet.column_dimensions[column[0].column_letter].width = min(max(12, longest * 0.9), 60)
        for cell in column:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "A2"
    about = workbook.create_sheet("About")
    for line in [["Artefact", table.name], ["Run", data.run_id], ["Scenario", data.scenario],
                 ["Generated", data.generated_at], ["Model", data.model_name], ["Status", data.status_note]]:
        about.append(line)
    about.column_dimensions["B"].width = 90
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
