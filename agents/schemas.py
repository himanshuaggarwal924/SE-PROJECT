"""
agents/schemas.py - The expected SHAPE of each agent's output.

These Pydantic models do two jobs:
  1. Validate the JSON the LLM returns (did it include the fields we need?).
  2. Give later phases a ready-made structure to save into a database.

Some agents have TWO schemas:
  * a "draft" schema - what the model writes in one call (sent to Ollama), and
  * a final schema   - the draft plus fields computed by Python afterwards
                       (confidence, flags, approval status...). The model is
                       never asked to fill those.

Fields have defaults where reasonable, and validators quietly normalise
common small-model slips ("high" -> "High", "[C1]" -> "C1"), so a slightly
imperfect answer doesn't fail the whole run.
"""

import copy

from pydantic import BaseModel, Field, field_validator

import config

LEVELS = ["High", "Medium", "Low"]


def strict_json_schema(schema_class: type[BaseModel]) -> dict:
    """The JSON schema sent to the model (Ollama "structured outputs").

    The Pydantic classes below are deliberately lenient (defaults for
    optional fields) so that parsing rarely fails. But if the model sees a
    field as optional it may leave it empty - so in the copy we send to the
    model, EVERY field is required and defaults are removed.
    """
    schema = copy.deepcopy(schema_class.model_json_schema())

    def make_strict(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
            node.pop("default", None)
            for value in node.values():
                make_strict(value)
        elif isinstance(node, list):
            for item in node:
                make_strict(item)

    make_strict(schema)
    return schema


def _level(value, default: str = "Medium") -> str:
    """'high', ' HIGH ' -> 'High'; anything unknown -> default."""
    text = str(value or "").strip().capitalize()
    return text if text in LEVELS else default


# Common ways a model might spell a category -> the official name.
_CATEGORY_ALIASES = {
    "availability": "availability/reliability", "reliability": "availability/reliability",
    "data management": "data-management", "data": "data-management",
    "audit": "audit/reporting", "reporting": "audit/reporting", "auditability": "audit/reporting",
    "operational": "operational/maintenance", "maintenance": "operational/maintenance",
    "maintainability": "operational/maintenance", "compliance": "regulatory",
    "data privacy": "privacy",
}


def normalise_category(value: str) -> str | None:
    text = str(value or "").strip().lower()
    text = _CATEGORY_ALIASES.get(text, text)
    return text if text in config.REQUIREMENT_CATEGORIES else None


def normalise_citation(value: str) -> str:
    """'[c1]' -> 'C1', ' KB-loan-01 ' -> 'KB-LOAN-01'."""
    return str(value or "").strip().strip("[]()").strip().upper()


# ----------------------------- Requirements Agent -----------------------------
class AcceptanceCriterion(BaseModel):
    given: str = ""
    when: str = ""
    then: str = ""


class RequirementDraft(BaseModel):
    """One requirement as written by the model."""
    id: str = ""                  # e.g. "FR-01" (Python re-assigns it to the planned ID)
    statement: str                # "The system shall ..."
    categories: list[str] = Field(default_factory=list, json_schema_extra={
        "items": {"type": "string", "enum": config.REQUIREMENT_CATEGORIES},
        "minItems": 1, "maxItems": 3})
    source_stakeholder: str = ""  # who needs it, if known
    business_justification: str = ""
    priority: str = Field("Medium", json_schema_extra={"enum": LEVELS})
    dependencies: list[str] = Field(default_factory=list)   # other requirement IDs
    assumptions: list[str] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(
        default_factory=list, json_schema_extra={"minItems": 1, "maxItems": 3})
    applicable_rules: list[str] = Field(default_factory=list)
    risk_level: str = Field("Medium", json_schema_extra={"enum": LEVELS})
    sources: list[str] = Field(default_factory=list)        # citation IDs, e.g. ["C2"]
    confidence: float = 0.5       # the model's own 0-1 rating

    @field_validator("categories", mode="before")
    @classmethod
    def _categories(cls, value):
        found = [normalise_category(v) for v in (value or [])]
        return list(dict.fromkeys(c for c in found if c))  # unique, keep order

    @field_validator("priority", "risk_level", mode="before")
    @classmethod
    def _levels(cls, value):
        return _level(value)

    @field_validator("sources", "dependencies", mode="before")
    @classmethod
    def _ids(cls, value):
        return [normalise_citation(v) for v in (value or []) if str(v).strip()]

    @field_validator("acceptance_criteria", mode="after")
    @classmethod
    def _at_most_three(cls, value):
        return value[:3]

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.5
        if 1 < number <= 100:      # "80" meant 80 %
            number /= 100
        return min(max(number, 0.0), 1.0)


class RequirementsBatch(BaseModel):
    """What the model returns in ONE call (one batch of requirements)."""
    scenario_summary: str = ""
    requirements: list[RequirementDraft] = Field(default_factory=list)


class Flag(BaseModel):
    """A problem found by the deterministic checks."""
    type: str      # invalid_citation | missing_citation | possible_hallucination |
                   # uncited_number | low_confidence
    detail: str = ""


class Requirement(RequirementDraft):
    """A requirement after Python's checks (the stored, final version)."""
    kind: str = "functional"                    # functional | non_functional
    model_confidence: float = 0.5               # the model's self-rating
    confidence_breakdown: dict[str, float] = Field(default_factory=dict)
    flags: list[Flag] = Field(default_factory=list)
    needs_human_review: bool = False
    approval_status: str = "pending"            # pending | approved | rejected
    # Earlier versions replaced by a revision or a reviewer edit: {"round", "statement", ...}
    revision_history: list[dict] = Field(default_factory=list)
    version: int = 1
    # Human review (Phase 6)
    reviewer: str = ""
    reviewed_at: str = ""
    review_comment: str = ""
    auto_approved: bool = False                 # approved by --auto-approve, not a person


class RequirementsOutput(BaseModel):
    scenario_summary: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    validation_summary: dict = Field(default_factory=dict)
    # Cosine similarity between requirement statements (same order as
    # `requirements`); reused by the Quality Agent's duplicate check.
    statement_similarity: list[list[float]] = Field(default_factory=list)

    @property
    def functional_requirements(self) -> list[Requirement]:
        return [r for r in self.requirements if r.kind == "functional"]

    @property
    def non_functional_requirements(self) -> list[Requirement]:
        return [r for r in self.requirements if r.kind == "non_functional"]


# --------------------------------- SDLC Agent ---------------------------------
# The model RATES the 13 decision factors (call 1) and EXPLAINS the ranking
# (call 2). The ranking itself is computed in Python (agents/sdlc_scoring.py).
from agents.sdlc_scoring import DECISION_FACTORS  # noqa: E402  (after the helpers above)


class FactorRatingDraft(BaseModel):
    factor: str = Field(json_schema_extra={"enum": DECISION_FACTORS})
    rating: str = Field("Medium", json_schema_extra={"enum": LEVELS})
    evidence: list[str] = Field(default_factory=list)   # requirement IDs or citation IDs
    reasoning: str = ""

    @field_validator("factor", mode="before")
    @classmethod
    def _factor(cls, value):
        return str(value or "").strip().lower().replace(" ", "_").replace("/", "_")

    @field_validator("rating", mode="before")
    @classmethod
    def _rating(cls, value):
        return _level(value)

    @field_validator("evidence", mode="before")
    @classmethod
    def _evidence(cls, value):
        return [normalise_citation(v) for v in (value or []) if str(v).strip()]


class SDLCFactorsBatch(BaseModel):
    """Call 1: ratings for all 13 factors."""
    factors: list[FactorRatingDraft] = Field(default_factory=list)


class Alternative(BaseModel):
    model: str                    # e.g. "Waterfall"
    reason_not_chosen: str = ""


class SDLCExplanationDraft(BaseModel):
    """Call 2: explanation of a ranking the model did not choose."""
    top_choice_explanation: str = ""
    runner_up_explanations: list[Alternative] = Field(default_factory=list)
    key_practices: list[str] = Field(default_factory=list, json_schema_extra={"maxItems": 3})


class FactorRating(FactorRatingDraft):
    flags: list[Flag] = Field(default_factory=list)
    scored: bool = True           # False = no valid evidence, left out of the score


class RankedModel(BaseModel):
    model: str
    score: float                  # 0-100
    rank: int
    summary: str = ""             # best/worst fitting factors, rules applied
    adjustments: list[dict] = Field(default_factory=list)


class SDLCOutput(BaseModel):
    recommended_model: str        # always ranking[0] - set by Python, never by the model
    confidence: str = ""          # from the score gap between #1 and #2
    ranking: list[RankedModel] = Field(default_factory=list)
    factors: list[FactorRating] = Field(default_factory=list)
    explanation: str = ""
    runner_up_explanations: list[Alternative] = Field(default_factory=list)
    key_practices: list[str] = Field(default_factory=list)
    explanation_source: str = "llm"    # "llm" or "template" (if the explanation call failed)
    factors_scored: int = 13           # factors with evidence that were scored
    scoring_basis: str = ""            # e.g. "Based on 9 of 13 factors ..."
    approval_status: str = "pending"   # pending | approved | overridden | rejected
    selected_model: str = ""           # the model the reviewers chose ("" = recommended_model)
    reviewer: str = ""
    reviewed_at: str = ""
    review_comment: str = ""
    auto_approved: bool = False                 # approved by --auto-approve, not a person


# ---------------------------- Quality & Clarification Agent ----------------------------
ISSUE_TYPES = [
    "ambiguity", "incompleteness", "inconsistency", "duplication", "infeasibility",
    "lack_of_testability", "undefined_terminology", "conflicting_stakeholder_expectations",
    "missing_security_compliance_control",
]


class Issue(BaseModel):
    type: str = Field("ambiguity", json_schema_extra={"enum": ISSUE_TYPES})
    explanation: str = ""
    severity: str = Field("Medium", json_schema_extra={"enum": LEVELS})

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, value):
        text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
        return text if text in ISSUE_TYPES else "ambiguity"

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, value):
        return _level(value)


class ClarificationQuestion(BaseModel):
    question: str
    stakeholder_role: str = ""    # who should answer, e.g. "Compliance officer"


class RequirementReviewDraft(BaseModel):
    requirement_id: str
    issues: list[Issue] = Field(default_factory=list)
    clarification_questions: list[ClarificationQuestion] = Field(
        default_factory=list, json_schema_extra={"maxItems": 2})

    @field_validator("requirement_id", mode="before")
    @classmethod
    def _rid(cls, value):
        return normalise_citation(value)


class QualityBatch(BaseModel):
    """What the model returns in ONE call (reviews of a few requirements)."""
    reviews: list[RequirementReviewDraft] = Field(default_factory=list)


class QualityIssue(Issue):
    origin: str = "llm"                          # "rule" (deterministic) or "llm"
    related_ids: list[str] = Field(default_factory=list)   # e.g. the duplicate's ID


class RequirementReview(BaseModel):
    requirement_id: str
    issues: list[QualityIssue] = Field(default_factory=list)
    clarification_questions: list[ClarificationQuestion] = Field(default_factory=list)
    max_severity: str = ""                       # "" when there are no issues


class QualityOutput(BaseModel):
    reviews: list[RequirementReview] = Field(default_factory=list)
    duplicates: list[dict] = Field(default_factory=list)   # {"ids": [a, b], "similarity": x}
    conflicts: list[dict] = Field(default_factory=list)    # {"ids": [a, b], "detail": "..."}
    summary: dict = Field(default_factory=dict)

    def review_for(self, requirement_id: str) -> RequirementReview | None:
        return next((r for r in self.reviews if r.requirement_id == requirement_id), None)


# ------------------------------ Compliance & Security Agent ------------------------------
COMPLIANCE_DISCLAIMER = (
    "Decision support only - not a legal determination. Mappings are based on the "
    "knowledge-base excerpts shown and must be confirmed by a compliance officer."
)


class ComplianceMappingDraft(BaseModel):
    requirement_id: str
    applicable_rules: list[str] = Field(default_factory=list)       # KB citation IDs only
    required_controls: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)               # citation IDs (KB-n / Cn)
    compliance_gaps: list[str] = Field(default_factory=list)
    approval_checkpoints: list[str] = Field(default_factory=list)
    retention_reporting_obligations: list[str] = Field(default_factory=list)
    impact: str = Field("Medium", json_schema_extra={"enum": LEVELS})

    @field_validator("requirement_id", mode="before")
    @classmethod
    def _rid(cls, value):
        return normalise_citation(value)

    @field_validator("evidence", mode="before")
    @classmethod
    def _evidence(cls, value):
        return [normalise_citation(v) for v in (value or []) if str(v).strip()]

    @field_validator("impact", mode="before")
    @classmethod
    def _impact(cls, value):
        return _level(value)


class ComplianceBatch(BaseModel):
    """What the model returns in ONE call."""
    mappings: list[ComplianceMappingDraft] = Field(default_factory=list)


class ComplianceMapping(ComplianceMappingDraft):
    flags: list[Flag] = Field(default_factory=list)
    requires_compliance_officer_approval: bool = False
    approval_status: str = "pending"
    # Human review (Phase 6)
    reviewer: str = ""
    reviewed_at: str = ""
    review_comment: str = ""
    auto_approved: bool = False                 # approved by --auto-approve, not a person


class SuggestedRequirement(BaseModel):
    """A security/privacy requirement nobody asked for but a baseline control needs."""
    id: str                                   # e.g. "SUG-01"
    control: str                              # e.g. "multi_factor_authentication"
    statement: str
    categories: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)   # KB excerpts that mention the control
    rationale: str = ""
    status: str = "suggested"                 # suggested | accepted | rejected


class ComplianceOutput(BaseModel):
    mappings: list[ComplianceMapping] = Field(default_factory=list)
    suggested_requirements: list[SuggestedRequirement] = Field(default_factory=list)
    disclaimer: str = COMPLIANCE_DISCLAIMER
    summary: dict = Field(default_factory=dict)

    def mapping_for(self, requirement_id: str) -> ComplianceMapping | None:
        return next((m for m in self.mappings if m.requirement_id == requirement_id), None)


# ---------------------------- Workflow Generation Agent ----------------------------
WORKFLOW_LIST_FIELDS = ["activities", "roles", "deliverables", "security_activities", "testing",
                        "compliance_checkpoints", "approval_gates", "entry_criteria",
                        "exit_criteria", "traceability"]


class PhaseCustomisationDraft(BaseModel):
    """Project-specific additions the model proposes for one template phase."""
    phase: str
    extra_activities: list[str] = Field(default_factory=list, json_schema_extra={"maxItems": 2})
    extra_security_activities: list[str] = Field(default_factory=list, json_schema_extra={"maxItems": 2})
    extra_testing: list[str] = Field(default_factory=list, json_schema_extra={"maxItems": 2})
    extra_compliance_checkpoints: list[str] = Field(default_factory=list, json_schema_extra={"maxItems": 2})
    project_notes: str = ""


class WorkflowCustomisation(BaseModel):
    phases: list[PhaseCustomisationDraft] = Field(default_factory=list)


class WorkflowPhase(BaseModel):
    name: str
    activities: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    security_activities: list[str] = Field(default_factory=list)
    testing: list[str] = Field(default_factory=list)
    compliance_checkpoints: list[str] = Field(default_factory=list)
    approval_gates: list[str] = Field(default_factory=list)
    entry_criteria: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)
    traceability: list[str] = Field(default_factory=list)
    project_notes: str = ""
    added: list[str] = Field(default_factory=list)   # "field: item" added for THIS project


class WorkflowOutput(BaseModel):
    model: str
    summary: str = ""
    phases: list[WorkflowPhase] = Field(default_factory=list)
    customised_by_ai: bool = False


# ---------------------------- Stakeholder Interview Agent ----------------------------
ASSESSMENTS = ["complete", "vague", "inconsistent"]


class InterviewTurnDraft(BaseModel):
    """The interview agent's view of a borderline answer (one call)."""
    assessment: str = Field("complete", json_schema_extra={"enum": ASSESSMENTS})
    reason: str = ""
    follow_up_question: str = ""

    @field_validator("assessment", mode="before")
    @classmethod
    def _assessment(cls, value):
        text = str(value or "").strip().lower()
        return text if text in ASSESSMENTS else "vague"


# ---------------------------------------------- Evaluation baseline (single prompt) ----------------------------------------------
class BaselineRequirement(BaseModel):
    statement: str
    categories: list[str] = Field(default_factory=list, json_schema_extra={
        "items": {"type": "string", "enum": config.REQUIREMENT_CATEGORIES}, "maxItems": 3})

    @field_validator("categories", mode="before")
    @classmethod
    def _categories(cls, value):
        found = [normalise_category(v) for v in (value or [])]
        return list(dict.fromkeys(c for c in found if c))


class BaselineOutput(BaseModel):
    """The single-prompt, no-RAG baseline: requirements + one SDLC model, one call."""
    requirements: list[BaselineRequirement] = Field(default_factory=list)
    sdlc_model: str = ""


# ------------------------------------------ Requirements Agent, compact mode ------------------------------------------
class CompactRequirementDraft(BaseModel):
    """REQUIREMENTS_PROMPT_MODE = "compact": only what the model must decide."""
    id: str = ""
    statement: str
    categories: list[str] = Field(default_factory=list, json_schema_extra={
        "items": {"type": "string", "enum": config.REQUIREMENT_CATEGORIES}, "minItems": 1, "maxItems": 3})
    priority: str = Field("Medium", json_schema_extra={"enum": LEVELS})
    sources: list[str] = Field(default_factory=list)

    @field_validator("categories", mode="before")
    @classmethod
    def _categories(cls, value):
        found = [normalise_category(v) for v in (value or [])]
        return list(dict.fromkeys(c for c in found if c))

    @field_validator("priority", mode="before")
    @classmethod
    def _priority(cls, value):
        return _level(value)

    @field_validator("sources", mode="before")
    @classmethod
    def _sources(cls, value):
        return [normalise_citation(v) for v in (value or []) if str(v).strip()]


class RequirementsCompactBatch(BaseModel):
    scenario_summary: str = ""
    requirements: list[CompactRequirementDraft] = Field(default_factory=list)
