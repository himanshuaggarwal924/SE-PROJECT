"""Phase 8: requirement artefacts generated from (approved) run data."""

import csv
import io
import zipfile

import docx
import openpyxl
import pytest

from artefacts import documents, registers
from artefacts.bundle import DESCRIPTIONS, generate, zip_all
from artefacts.data import collect
from pipeline import resume_pipeline, run_pipeline, run_state
from tests.mock_llm import make_requirement

DOC = "Loans above 50,000 need an underwriter. Customer data must be encrypted."


def reviewed_result(mock_llm):
    """A finished interactive run: FR-02 rejected, the rest approved, SDLC approved."""
    def answer(system, user):
        import re
        ids = re.findall(r"\bN?FR-\d+\b", user.split("YOUR TASK NOW:")[-1].split("EXPECTED")[0])
        return {"scenario_summary": "Loan approval with underwriting.", "requirements": [
            make_requirement(rid, sources=["C1"],
                             statement=f"The system shall route loans above 50,000 to an underwriter ({rid}).",
                             categories=["security", "privacy"] if rid.startswith("NFR") else ["functional", "integration"],
                             risk_level="High", dependencies=["FR-01"] if rid == "FR-02" else [],
                             assumptions=[f"Assumption for {rid}"]) for rid in ids]}
    mock_llm.responses["RequirementsBatch"] = answer
    result = run_pipeline("Loan approval", source_text=DOC, source_name="policy.md", user="alice",
                          options={"num_functional": 2, "num_non_functional": 1, "review_mode": "interactive"})
    state = run_state(result.run_id)
    maps = state["agent_outputs"]["compliance_agent"]["parsed"]["mappings"]
    result = resume_pipeline(result.run_id, {"reviewer": "alice", "requirements": {
        "FR-01": {"action": "accept"}, "FR-02": {"action": "reject"}, "NFR-01": {"action": "accept"}},
        "mappings": {m["requirement_id"]: {"action": "accept"} for m in maps}})
    return resume_pipeline(result.run_id, {"reviewer": "bob", "action": "approve"})


def test_only_approved_requirements_are_used(mock_llm):
    data = collect(reviewed_result(mock_llm))
    assert not data.draft
    assert [r.id for r in data.requirements] == ["FR-01", "NFR-01"]       # FR-02 was rejected


def test_unreviewed_run_is_marked_draft(mock_llm):
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1})
    data = collect(result)
    assert data.draft and "DRAFT" in data.status_note
    assert "DRAFT" in documents.srs(data).to_markdown()


def test_all_files_are_generated_and_valid(mock_llm):
    result = reviewed_result(mock_llm)
    files = generate(result, "alice")
    assert list(files) == list(DESCRIPTIONS)

    srs = docx.Document(io.BytesIO(files["srs.docx"]))
    headings = [p.text for p in srs.paragraphs if p.style.name.startswith("Heading")]
    for expected in ("1 Introduction", "2 Overall description", "3 Specific requirements",
                     "3.1 External interface requirements", "3.2 Functional requirements"):
        assert expected in headings
    assert "**" not in "\n".join(p.text for p in srs.paragraphs)

    sheet = openpyxl.load_workbook(io.BytesIO(files["traceability_matrix.xlsx"])).active
    rows = list(sheet.values)
    assert rows[0][0] == "Requirement" and [r[0] for r in rows[1:]] == ["FR-01", "NFR-01"]

    table = list(csv.reader(io.StringIO(files["traceability_matrix.csv"].decode("utf-8-sig"))))
    assert table[0][:6] == ["Requirement", "Type", "Statement", "Source stakeholder", "Source statement", "Citations"]

    archive = zipfile.ZipFile(io.BytesIO(zip_all(files, result.run_id)))
    assert len(archive.namelist()) == len(files)


def test_traceability_links_every_column(mock_llm):
    data = collect(reviewed_result(mock_llm))
    table = registers.traceability_matrix(data)
    row = dict(zip(table.headers, table.rows[0]))
    assert row["Source stakeholder"] == "Credit risk team"
    assert "Loans above 50,000 need an underwriter" in row["Source statement"]
    assert row["Citations"].startswith("C1 (policy.md, part 1)")
    assert row["Compliance controls"] == "Encryption"                       # from the mapping
    assert "Regulatory criticality=High" in row["SDLC factor evidence"]     # mock cites FR-01
    assert row["Tests / acceptance criteria"].startswith("TC-FR-01-1: Given")
    assert row["Approval"] == "approved by alice"


def test_registers_content(mock_llm):
    data = collect(reviewed_result(mock_llm))
    risks = registers.risk_register(data)
    kinds = [(r[1], r[2]) for r in risks.rows]
    assert ("NFR-01", "Threat") in kinds and ("FR-01", "Threat") in kinds          # privacy / integration
    assert all(r[0].startswith("R-") for r in risks.rows)
    issues = registers.open_issues(data)
    assert any(r[2] == "clarification question" and r[6] == "Product owner" for r in issues.rows)
    deps = registers.assumptions_dependencies(data)
    assert any(r[1] == "Assumption" and "FR-01" in r[3] for r in deps.rows)
    compliance = registers.compliance_control_matrix(data)
    assert {r[0] for r in compliance.rows} >= {"FR-01", "NFR-01"}
    assert "FR-02" not in {r[0] for r in compliance.rows}


def test_user_stories_and_use_cases(mock_llm):
    data = collect(reviewed_result(mock_llm))
    stories = documents.user_stories(data).to_markdown()
    assert "**As a** Credit risk team, **I want** the system to route loans above 50,000" in stories
    assert "Acceptance: Given an application" in stories
    cases = documents.use_cases(data).to_markdown()
    assert "UC-01" in cases and "| Primary actor | Credit risk team |" in cases
    interface = documents.data_interface_requirements(data).to_markdown()
    assert "FR-01" in interface.split("# Interface requirements")[-1]


def test_artefacts_are_audited(mock_llm):
    import audit_log
    result = reviewed_result(mock_llm)
    generate(result, "alice")
    event = [e for e in audit_log.read_events(result.run_id) if e["event"] == "artefacts_generated"][0]
    assert event["user"] == "alice" and event["draft"] is False and "srs.docx" in event["files"]


@pytest.mark.parametrize("name", ["srs.md", "user_stories.md", "use_cases.md"])
def test_markdown_tables_escape_pipes(mock_llm, name):
    result = reviewed_result(mock_llm)
    text = generate(result)[name].decode("utf-8")
    for line in text.splitlines():
        if line.startswith("|") and not line.startswith("|---"):
            assert line.endswith("|")


@pytest.mark.parametrize("justification, expected", [
    ("Ensures compliance with the policy.", "it ensures compliance with the policy"),
    ("Required by the loan policy.", "it is required by the loan policy"),
    ("Underwriters can review risky loans", "underwriters can review risky loans"),
    ("", "the business need is met"),
])
def test_user_story_so_that_clause_reads_naturally(justification, expected):
    assert documents._so_that(justification) == expected
