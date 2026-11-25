"""
artefacts/data.py - Collects what the artefacts are generated from.

Approved data first: if any requirement of the run is approved, only
approved requirements are included. If nothing is approved (e.g. a run
without review), all non-rejected requirements are included and every
artefact is marked DRAFT.
"""

from dataclasses import dataclass, field
from datetime import datetime

from agents.sdlc_scoring import FACTOR_LABELS

ROLE_BY_CATEGORY = [("regulatory", "Compliance officer"), ("security", "Information security"),
                    ("privacy", "Information security"), ("audit/reporting", "Compliance officer"),
                    ("integration", "Architect"), ("performance", "Architect"),
                    ("availability/reliability", "Operations")]


@dataclass
class ArtefactData:
    run_id: str
    scenario: str
    model_name: str
    generated_at: str
    draft: bool                        # True if nothing was approved
    requirements: list = field(default_factory=list)       # Requirement objects
    summary: str = ""
    assumptions: list = field(default_factory=list)
    quality: object = None             # QualityOutput or None
    compliance: object = None          # ComplianceOutput or None
    sdlc: object = None                # SDLCOutput or None
    workflow: object = None            # WorkflowOutput or None
    chunk_map: dict = field(default_factory=dict)
    source_name: str = ""

    @property
    def status_note(self) -> str:
        if self.draft:
            return "DRAFT – generated from unapproved requirements; not a baseline."
        return "Generated from human-approved requirements."

    @property
    def functional(self):
        return [r for r in self.requirements if r.kind == "functional"]

    @property
    def non_functional(self):
        return [r for r in self.requirements if r.kind != "functional"]

    # ---------------------------------------------------------- lookups --
    def mapping(self, requirement_id: str):
        return self.compliance.mapping_for(requirement_id) if self.compliance else None

    def review(self, requirement_id: str):
        return self.quality.review_for(requirement_id) if self.quality else None

    def citation(self, cid: str) -> str:
        """'C2 (policy.md, part 3)' / 'KB-1 (Credit policy v2.0 – Limits)' / 'C3 (Interview …)'."""
        chunk = self.chunk_map.get(cid)
        if not chunk:
            return cid
        if chunk.get("origin") == "kb":
            return f"{cid} ({chunk['title']} v{chunk['version']} – {chunk['section']})"
        if chunk.get("origin") == "transcript":
            return f"{cid} ({chunk['document']})"
        return f"{cid} ({chunk.get('document')}, part {(chunk.get('position') or 0) + 1})"

    def citations(self, requirement) -> list[str]:
        return [self.citation(c) for c in requirement.sources]

    def source_statement(self, requirement) -> str:
        """Who asked for it and the exact text it came from (first cited excerpt)."""
        parts = []
        if requirement.source_stakeholder:
            parts.append(requirement.source_stakeholder)
        for cid in requirement.sources:
            chunk = self.chunk_map.get(cid)
            if chunk and chunk.get("origin") != "kb":
                text = " ".join(chunk["text"].split())
                parts.append(f"“{text[:180]}{'…' if len(text) > 180 else ''}” [{cid}]")
                break
        if not parts:
            parts.append(f"Functionality description: “{self.scenario[:180]}”")
        return " – ".join(parts)

    def factor_evidence(self, requirement_id: str) -> list[str]:
        """SDLC factors whose evidence cites this requirement, e.g. 'Security risk=High'."""
        if not self.sdlc:
            return []
        return [f"{FACTOR_LABELS.get(f.factor, f.factor)}={f.rating}" for f in self.sdlc.factors
                if requirement_id in f.evidence]

    def owner(self, requirement) -> str:
        for category, role in ROLE_BY_CATEGORY:
            if category in requirement.categories:
                return role
        return "Product owner"

    def acceptance_tests(self, requirement) -> list[str]:
        return [f"TC-{requirement.id}-{n}: Given {c.given}, when {c.when}, then {c.then}"
                for n, c in enumerate(requirement.acceptance_criteria, start=1)]

    def approval(self, item) -> str:
        status = item.approval_status
        if getattr(item, "reviewer", ""):
            status += f" by {item.reviewer}" + (" (auto)" if getattr(item, "auto_approved", False) else "")
        return status


def collect(result) -> ArtefactData:
    """Build ArtefactData from a PipelineResult."""
    def parsed(key):
        agent = result.get(key)
        return agent.parsed if agent and agent.parsed else None

    requirements_output = parsed("requirements_agent")
    all_requirements = requirements_output.requirements if requirements_output else []
    approved = [r for r in all_requirements if r.approval_status == "approved"]
    draft = not approved
    chosen = approved or [r for r in all_requirements if r.approval_status != "rejected"]
    return ArtefactData(
        run_id=result.run_id, scenario=result.scenario, model_name=result.model_name,
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"), draft=draft,
        requirements=chosen,
        summary=requirements_output.scenario_summary if requirements_output else "",
        assumptions=requirements_output.assumptions if requirements_output else [],
        quality=parsed("quality_agent"), compliance=parsed("compliance_agent"),
        sdlc=parsed("sdlc_agent"), workflow=parsed("workflow_agent"),
        chunk_map=result.chunk_map, source_name=(result.context_info or {}).get("source", ""))
