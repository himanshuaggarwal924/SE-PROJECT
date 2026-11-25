"""
artefacts/documents.py - Narrative documents built from ArtefactData:

  srs()                          Software Requirements Specification, IEEE 830 structure
  user_stories()                 "As a … I want … so that …" + acceptance criteria
  use_cases()                    one use case per functional requirement
  data_interface_requirements()  data-management/privacy and integration requirements

Deterministic (templates over the run's data); every item names its source
statement and citations.
"""

import re

import config
from artefacts.data import ArtefactData
from artefacts.document import Document

CATEGORY_SECTIONS = [
    ("3.3 Performance requirements", {"performance"}),
    ("3.4 Security and privacy requirements", {"security", "privacy"}),
    ("3.5 Software system attributes (availability, reliability, maintainability, usability)",
     {"availability/reliability", "operational/maintenance", "usability"}),
    ("3.6 Regulatory, audit and reporting requirements", {"regulatory", "audit/reporting"}),
    ("3.7 Data requirements", {"data-management"}),
]


def _header(data: ArtefactData, title: str) -> Document:
    subtitle = f"Run {data.run_id} · generated {data.generated_at[:16].replace('T', ' ')} · model {data.model_name}"
    document = Document(title, subtitle)
    document.note(data.status_note)
    return document


def _requirement_block(document: Document, data: ArtefactData, r) -> None:
    document.heading(f"{r.id}: {r.statement}", 3)
    rows = [["Categories", ", ".join(r.categories)], ["Priority / risk", f"{r.priority} / {r.risk_level}"],
            ["Rationale", r.business_justification], ["Source", data.source_statement(r)],
            ["Citations", "; ".join(data.citations(r)) or "—"],
            ["Applicable rules", "; ".join(data.citation(c) for c in r.applicable_rules) or "—"],
            ["Dependencies", ", ".join(r.dependencies) or "—"],
            ["Confidence", f"{r.confidence:.2f}" + (" (needs review)" if r.needs_human_review else "")],
            ["Approval", data.approval(r)], ["Version", str(r.version)]]
    document.table(["Attribute", "Value"], rows)
    document.bullets(data.acceptance_tests(r))


def srs(data: ArtefactData) -> Document:
    d = _header(data, "Software Requirements Specification")
    d.heading("1 Introduction")
    d.heading("1.1 Purpose", 2)
    d.para(f"This document specifies the software requirements for: {data.scenario}")
    d.heading("1.2 Scope", 2)
    d.para(data.summary or data.scenario)
    d.heading("1.3 Definitions", 2)
    d.bullets([f"**{c}** – requirement category" for c in config.REQUIREMENT_CATEGORIES
               if any(c in r.categories for r in data.requirements)]
              + ["**FR / NFR / SEC** – functional / non-functional / accepted suggested security requirement",
                 "**C-n / KB-n** – citation of a source-document excerpt / knowledge-base excerpt"])
    d.heading("1.4 References", 2)
    refs = sorted({c["document"] for c in data.chunk_map.values() if c.get("origin") != "kb"})
    kb = sorted({f"{c['title']} v{c['version']} ({c['kb_id']})" for c in data.chunk_map.values()
                 if c.get("origin") == "kb"})
    d.bullets(refs + kb or ["Functionality description only"])
    if kb:
        d.note("Knowledge-base items marked SAMPLE are illustrative, not authoritative.")

    d.heading("2 Overall description")
    d.heading("2.1 Product perspective", 2)
    d.para(data.summary or data.scenario)
    d.heading("2.2 Product functions", 2)
    d.bullets([f"{r.id}: {r.statement}" for r in data.functional])
    d.heading("2.3 User characteristics", 2)
    d.bullets(sorted({r.source_stakeholder for r in data.requirements if r.source_stakeholder})
              or ["Not stated in the sources"])
    d.heading("2.4 Constraints", 2)
    constraints = [data.citation(c) for r in data.requirements for c in r.applicable_rules]
    if data.sdlc:
        chosen = data.sdlc.selected_model or data.sdlc.recommended_model
        constraints.append(f"Delivery model: {chosen} ({data.sdlc.approval_status})")
    d.bullets(list(dict.fromkeys(constraints)) or ["None identified"])
    d.heading("2.5 Assumptions and dependencies", 2)
    d.bullets(list(dict.fromkeys(data.assumptions + [a for r in data.requirements for a in r.assumptions]))
              or ["None recorded"])

    d.heading("3 Specific requirements")
    d.heading("3.1 External interface requirements", 2)
    interfaces = [r for r in data.requirements if "integration" in r.categories]
    if interfaces:
        for r in interfaces:
            _requirement_block(d, data, r)
    else:
        d.para("No interface requirements were identified.")
    d.heading("3.2 Functional requirements", 2)
    for r in data.functional:
        _requirement_block(d, data, r)
    placed = {r.id for r in data.functional} | {r.id for r in interfaces}
    for title, categories in CATEGORY_SECTIONS:
        items = [r for r in data.non_functional if categories & set(r.categories) and r.id not in placed]
        d.heading(title, 2)
        if not items:
            d.para("None.")
        for r in items:
            _requirement_block(d, data, r)
            placed.add(r.id)
    others = [r for r in data.requirements if r.id not in placed]
    if others:
        d.heading("3.8 Other requirements", 2)
        for r in others:
            _requirement_block(d, data, r)

    d.heading("Appendix A – Traceability summary")
    d.table(["Requirement", "Source", "Citations", "Tests"],
            [[r.id, data.source_statement(r), "; ".join(r.sources) or "—", len(r.acceptance_criteria)]
             for r in data.requirements])
    if data.sdlc:
        d.heading("Appendix B – Development approach")
        chosen = data.sdlc.selected_model or data.sdlc.recommended_model
        d.para(f"Recommended: {data.sdlc.recommended_model}; chosen: {chosen} "
               f"({data.sdlc.approval_status}). {data.sdlc.scoring_basis}")
        d.para(data.sdlc.explanation)
        if data.workflow:
            d.bullets([f"{p.name}: gates – {'; '.join(p.approval_gates) or 'none'}" for p in data.workflow.phases])
    return d


# --------------------------------------------------------------- user stories --
def _role(r) -> str:
    who = r.source_stakeholder.split(";")[0].strip() if r.source_stakeholder else ""
    return re.sub(r"\s*\(.*?\)\s*$", "", who) or "user of the system"


def _want(statement: str) -> str:
    text = re.sub(r"^\s*the system shall\s+", "", statement.strip().rstrip("."), flags=re.IGNORECASE)
    return f"the system to {text}"


VERB_STARTS = {"ensures", "ensure", "prevents", "reduces", "protects", "supports", "meets", "provides",
               "enables", "allows", "avoids", "helps", "complies", "keeps", "maintains", "required", "needed"}


def _so_that(justification: str) -> str:
    """'Ensures compliance.' -> 'it ensures compliance'; 'Loans are checked' -> 'loans are checked'."""
    reason = justification.strip().rstrip(".") or "the business need is met"
    reason = reason[0].lower() + reason[1:]
    first = reason.split()[0] if reason.split() else ""
    return f"it is {reason}" if first in ("required", "needed") else         f"it {reason}" if first in VERB_STARTS else reason


def user_stories(data: ArtefactData) -> Document:
    d = _header(data, "User stories")
    for r in data.functional:
        d.heading(f"US-{r.id}: {r.statement}", 2)
        d.para(f"**As a** {_role(r)}, **I want** {_want(r.statement)}, **so that** {_so_that(r.business_justification)}.")
        d.para(f"Priority: {r.priority} · Source: {data.source_statement(r)} · Approval: {data.approval(r)}")
        d.bullets(["Acceptance: " + t.split(": ", 1)[1] for t in data.acceptance_tests(r)])
    if not data.functional:
        d.para("No functional requirements.")
    return d


def use_cases(data: ArtefactData) -> Document:
    d = _header(data, "Use-case descriptions")
    for number, r in enumerate(data.functional, start=1):
        d.heading(f"UC-{number:02d}: {r.statement}", 2)
        preconditions = [c.given for c in r.acceptance_criteria] or ["—"]
        flow = [f"{c.when} → {c.then}" for c in r.acceptance_criteria] or [r.statement]
        d.table(["Field", "Description"], [
            ["Requirement", r.id], ["Primary actor", _role(r)], ["Goal", r.statement],
            ["Preconditions", "; ".join(preconditions)], ["Main flow", " | ".join(flow)],
            ["Postconditions", "; ".join(c.then for c in r.acceptance_criteria) or "—"],
            ["Business rules", "; ".join(data.citation(c) for c in r.applicable_rules) or "—"],
            ["Source", data.source_statement(r)], ["Approval", data.approval(r)]])
    if not data.functional:
        d.para("No functional requirements.")
    return d


def data_interface_requirements(data: ArtefactData) -> Document:
    d = _header(data, "Data and interface requirements")
    d.heading("Data requirements")
    data_reqs = [r for r in data.requirements if {"data-management", "privacy"} & set(r.categories)]
    rows = []
    for r in data_reqs:
        mapping = data.mapping(r.id)
        rows.append([r.id, r.statement, ", ".join(r.categories),
                     "; ".join(mapping.retention_reporting_obligations) if mapping else "—",
                     "; ".join(data.citations(r)) or "—"])
    if rows:
        d.table(["ID", "Requirement", "Categories", "Retention / reporting", "Citations"], rows)
    else:
        d.para("No data-management or privacy requirements were identified.")
    d.heading("Interface requirements")
    interfaces = [r for r in data.requirements if "integration" in r.categories]
    if interfaces:
        d.table(["ID", "Requirement", "Required controls", "Citations"],
                [[r.id, r.statement, "; ".join(data.mapping(r.id).required_controls) if data.mapping(r.id) else "—",
                  "; ".join(data.citations(r)) or "—"] for r in interfaces])
    else:
        d.para("No integration requirements were identified.")
    return d
