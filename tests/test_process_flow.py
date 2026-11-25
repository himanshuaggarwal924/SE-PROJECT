"""Phase 12: process-workflow flowchart linked to requirement IDs."""

from artefacts import process_flow
from artefacts.bundle import DESCRIPTIONS, generate
from pipeline import run_pipeline

REQS = [
    {"id": "FR-01", "kind": "functional", "statement": "The system shall capture the loan application.",
     "categories": ["functional"], "dependencies": []},
    {"id": "FR-02", "kind": "functional", "statement": "The system shall route loans above 50,000 to an underwriter.",
     "categories": ["functional", "regulatory"], "dependencies": ["FR-01"]},
    {"id": "FR-03", "kind": "functional", "statement": "The system shall notify the applicant of the outcome.",
     "categories": ["functional"], "dependencies": []},
    {"id": "NFR-01", "kind": "non_functional", "statement": "The system shall log decisions for 7 years.",
     "categories": ["regulatory", "audit/reporting"], "dependencies": []},
    {"id": "NFR-02", "kind": "non_functional", "statement": "The system shall respond within 2 seconds.",
     "categories": ["performance"], "dependencies": []},
]


def test_flow_structure():
    flow = process_flow.build_flow(REQS, "Loan application")
    kinds = {n.requirement: n.kind for n in flow.nodes if n.requirement}
    assert kinds == {"FR-01": "step", "FR-02": "decision", "FR-03": "step", "NFR-01": "control", "NFR-02": "control"}
    edges = {(a, b, label, style) for a, b, label, style in flow.edges}
    assert ("START", "FR_01", "", "solid") in edges
    assert ("FR_02", "FR_03", "meets rule", "solid") in edges
    assert ("FR_02", "EXCEPTION", "exception", "solid") in edges
    assert ("FR_01", "FR_02", "depends on", "dashed") in edges
    assert ("NFR_01", "FR_02", "", "dotted") in edges                 # shares "regulatory"
    assert ("NFR_02", "START", "applies to all", "dotted") in edges   # no shared category


def test_mermaid_and_dot_output():
    flow = process_flow.build_flow(REQS, "Loan application")
    mermaid = process_flow.to_mermaid(flow)
    assert mermaid.startswith("flowchart TD")
    assert 'FR_02{"FR-02: Route loans above 50,000 to an underwriter"}' in mermaid
    assert "FR_02 -->|exception| EXCEPTION" in mermaid and "subgraph Controls" in mermaid
    assert all(r["id"] in mermaid for r in REQS)
    dot = process_flow.to_dot(flow)
    assert dot.startswith("digraph process") and "shape=diamond" in dot


def test_flowchart_is_in_the_artefacts(mock_llm):
    result = run_pipeline("Loan approval", options={"num_functional": 2, "num_non_functional": 1})
    files = generate(result)
    assert {"process_flowchart.md", "process_flowchart.mmd"} <= set(files) <= set(DESCRIPTIONS)
    text = files["process_flowchart.md"].decode("utf-8")
    assert "```mermaid\nflowchart TD" in text and "| FR-01 |" in text and "Loan application starts" in text


def test_the_noun_decision_alone_is_not_a_gate():
    flow = process_flow.build_flow([
        {"id": "FR-01", "kind": "functional", "statement": "The system shall store decision records.", "categories": []},
        {"id": "FR-02", "kind": "functional", "statement": "The system shall verify the applicant identity.", "categories": []},
    ])
    assert [n.kind for n in flow.nodes if n.requirement] == ["step", "decision"]
