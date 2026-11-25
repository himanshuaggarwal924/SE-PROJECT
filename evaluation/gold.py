"""
evaluation/gold.py - Loads gold-standard files (evaluation/gold/*.yaml).

Format (see the shipped DRAFT files):
  status: draft | reviewed            reviewed_by: name
  document: file name in documents/   scenario: text
  expected_requirements: [{id, kind, categories, statement}]
  expected_controls: [keys of config.COMPLIANCE_BASELINE_CONTROLS]
  expected_sdlc: {top1: model, acceptable: [models]}
  seeded_requirements: [{statement, kind, categories, ambiguous: bool}]
  seeded_conflicts: [{a, b, conflict: bool}]
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

import config


@dataclass
class Gold:
    name: str
    status: str
    document: str
    scenario: str
    expected_requirements: list[dict]
    expected_controls: list[str] = field(default_factory=list)
    expected_sdlc: dict = field(default_factory=dict)
    seeded_requirements: list[dict] = field(default_factory=list)
    seeded_conflicts: list[dict] = field(default_factory=list)
    reviewed_by: str = ""

    @property
    def is_draft(self) -> bool:
        return self.status != "reviewed"

    def document_text(self) -> str:
        return (config.DOCUMENTS_DIR / self.document).read_text(encoding="utf-8")


def load(path: Path) -> Gold:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    missing = [k for k in ("document", "scenario", "expected_requirements") if not raw.get(k)]
    if missing:
        raise ValueError(f"{path.name} is missing: {', '.join(missing)}")
    unknown = set(raw.get("expected_controls", [])) - set(config.COMPLIANCE_BASELINE_CONTROLS)
    if unknown:
        raise ValueError(f"{path.name}: unknown controls {sorted(unknown)}")
    return Gold(name=path.stem, status=raw.get("status", "draft"), document=raw["document"],
                scenario=raw["scenario"], expected_requirements=raw["expected_requirements"],
                expected_controls=raw.get("expected_controls", []), expected_sdlc=raw.get("expected_sdlc", {}),
                seeded_requirements=raw.get("seeded_requirements", []),
                seeded_conflicts=raw.get("seeded_conflicts", []), reviewed_by=raw.get("reviewed_by", ""))


def load_all(names: list[str] | None = None) -> list[Gold]:
    paths = sorted(config.EVAL_GOLD_DIR.glob("*.yaml"))
    golds = [load(p) for p in paths]
    return [g for g in golds if not names or g.name in names]
