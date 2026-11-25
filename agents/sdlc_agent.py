"""
agents/sdlc_agent.py - The hybrid SDLC selection engine.

  call 1 (prompts/sdlc_agent.yaml)      the model rates the 13 decision factors
                                        with evidence (requirement / citation IDs)
  Python (agents/sdlc_scoring.py)       multi-criteria scoring -> ranked models
  call 2 (prompts/sdlc_explainer.yaml)  the model explains the ranking, seeing
                                        ONLY the ratings and scores, so it cannot
                                        contradict them
The recommended model is always ranking[0], set by Python.
If call 2 fails, a template explanation is written from the scores instead.
"""

from agents.quality_agent import requirements_from
from agents.sdlc_evidence import candidate_evidence
from agents.schemas import (Alternative, FactorRating, Flag, RankedModel, SDLCExplanationDraft,
                            SDLCFactorsBatch, SDLCOutput)
import config
from agents.sdlc_scoring import (DECISION_FACTORS, FACTOR_LABELS, confidence_with_coverage,
                                 describe_score, score_models)

FACTOR_DEFINITIONS = {
    "requirement_stability": "High = requirements are clear and unlikely to change",
    "regulatory_criticality": "High = heavily regulated; audits and approvals required",
    "security_risk": "High = sensitive data or money movement; attractive to attackers",
    "complexity": "High = many business rules, integrations or technical unknowns",
    "system_size": "High = large scope, many components or users",
    "legacy_dependence": "High = must integrate with or replace legacy core systems",
    "change_frequency": "High = business rules expected to change often",
    "continuous_delivery_need": "High = frequent releases are needed",
    "stakeholder_availability": "High = stakeholders available for frequent feedback",
    "testing_documentation_needs": "High = extensive test evidence and documentation required",
    "budget_schedule_constraints": "High = fixed budget or deadline, little flexibility",
    "formal_verification_need": "High = formal verification/validation evidence required",
    "failure_consequences": "High = failure causes financial loss, harm or regulatory breach",
}
RUNNER_UPS = 2


def plan_calls(state) -> list[dict]:
    return [{"step": "factors"},
            {"step": "explain", "prompt": "sdlc_explainer", "include_previous": False}]


def schema_for(spec: dict):
    return SDLCFactorsBatch if spec["step"] == "factors" else SDLCExplanationDraft


def validate_factors(parsed: SDLCFactorsBatch, state) -> list[FactorRating]:
    """All 13 factors with invalid evidence removed and flags set. A factor
    is `scored` only if it has at least one valid evidence ID."""
    valid_ids = {r["id"] for r in requirements_from(state)} | set(state.get("chunk_map") or {})
    by_factor = {f.factor: f for f in parsed.factors if f.factor in DECISION_FACTORS}
    factors = []
    for name in DECISION_FACTORS:
        draft = by_factor.get(name)
        if draft is None:
            factors.append(FactorRating(factor=name, rating="Medium", reasoning="Not rated by the model.",
                                        scored=False,
                                        flags=[Flag(type="not_rated", detail="Not scored")]))
            continue
        evidence = [e for e in draft.evidence if e in valid_ids]
        flags = [Flag(type="invalid_evidence", detail=f"{e} is not a requirement or excerpt ID (removed)")
                 for e in draft.evidence if e not in valid_ids]
        if not evidence:
            flags.append(Flag(type="no_evidence", detail="No valid requirement or excerpt cited - not scored"))
        factors.append(FactorRating(**{**draft.model_dump(), "evidence": evidence, "flags": flags,
                                       "scored": bool(evidence)}))
    return factors


def score_with_evidence(factors: list[FactorRating]):
    """Score only the factors with evidence. Returns (scores, number scored,
    basis note, too_little_evidence). With fewer than SDLC_MIN_EVIDENCED_FACTORS
    evidenced factors, all ratings are used and the result is marked as weak."""
    evidenced = {f.factor: f.rating for f in factors if f.scored}
    total = len(DECISION_FACTORS)
    if len(evidenced) >= config.SDLC_MIN_EVIDENCED_FACTORS:
        note = (f"Based on {len(evidenced)} of {total} factors - factors without evidence are "
                "left out of the score.")
        return score_models(evidenced), len(evidenced), note, False
    note = (f"Only {len(evidenced)} of {total} factors had evidence (minimum "
            f"{config.SDLC_MIN_EVIDENCED_FACTORS}), so all {total} ratings were used and the "
            "confidence is Low. Add more detail to the requirements to strengthen this.")
    return score_models({f.factor: f.rating for f in factors}), len(evidenced), note, True


def call_variables(spec: dict, state, earlier) -> dict | None:
    if spec["step"] == "factors":
        candidates = candidate_evidence(state)
        lines = []
        for factor, definition in FACTOR_DEFINITIONS.items():
            hint = ", ".join(candidates.get(factor, [])) or "none found"
            lines.append(f"- {factor}: {definition}. Likely evidence: {hint}")
        # The requirement list itself ("FR-01 [...]: The system shall ...") is
        # appended automatically from the Requirements Agent's output.
        return {"factor_definitions": "\n".join(lines)}

    parsed = earlier[0][1]
    if parsed is None:
        return None                      # no ratings -> nothing to explain (template used)
    factors = validate_factors(parsed, state)
    scores, _, _, all_used = score_with_evidence(factors)
    top, runner_ups = scores[0], scores[1:1 + RUNNER_UPS]
    spec["runner_ups"] = [s.model for s in runner_ups]       # used by adjust_schema
    return {
        "factor_ratings": "\n".join(
            f"- {FACTOR_LABELS[f.factor]}: {f.rating}"
            + ("" if f.scored or all_used else " (no evidence - not scored)") for f in factors),
        "ranking": "\n".join(f"{s.rank}. {describe_score(s)}" for s in scores[:1 + RUNNER_UPS]),
        "top_model": top.model,
        "runner_up_list": ", ".join(spec["runner_ups"]),
    }


def adjust_schema(schema: dict, spec: dict) -> dict:
    schema = {**schema, "properties": dict(schema["properties"]), "$defs": dict(schema.get("$defs", {}))}
    if spec["step"] == "factors":
        schema["properties"]["factors"] = {**schema["properties"]["factors"],
                                           "minItems": len(DECISION_FACTORS),
                                           "maxItems": len(DECISION_FACTORS)}
    else:
        names = spec.get("runner_ups", [])
        schema["properties"]["runner_up_explanations"] = {
            **schema["properties"]["runner_up_explanations"],
            "minItems": len(names), "maxItems": len(names)}
        alternative = dict(schema["$defs"]["Alternative"])
        alternative["properties"] = {**alternative["properties"],
                                     "model": {"type": "string", "enum": names or ["-"]}}
        schema["$defs"]["Alternative"] = alternative
    return schema


def _template_explanation(scores) -> tuple[str, list[Alternative]]:
    top = scores[0]
    text = (f"{top.model} has the highest score ({top.score:.0f}%). "
            f"{describe_score(top)}.")
    alternatives = [Alternative(model=s.model,
                                reason_not_chosen=f"Scored {s.score:.0f}%: {describe_score(s)}.")
                    for s in scores[1:1 + RUNNER_UPS]]
    return text, alternatives


def combine(calls, state) -> SDLCOutput | None:
    factors_parsed = calls[0][1] if calls else None
    if factors_parsed is None:
        return None
    factors = validate_factors(factors_parsed, state)
    scores, factors_scored, basis, too_little_evidence = score_with_evidence(factors)
    ranking = [RankedModel(model=s.model, score=s.score, rank=s.rank, summary=describe_score(s),
                           adjustments=s.adjustments) for s in scores]

    explanation_parsed = calls[1][1] if len(calls) > 1 else None
    runner_up_names = [s.model for s in scores[1:1 + RUNNER_UPS]]
    if explanation_parsed is not None and explanation_parsed.top_choice_explanation.strip():
        explanation = explanation_parsed.top_choice_explanation
        given = {a.model: a for a in explanation_parsed.runner_up_explanations}
        template_text, template_alts = _template_explanation(scores)
        # Keep only explanations for the real runner-ups (fill gaps from the template).
        runner_ups = [given.get(name) or alt for name, alt in zip(runner_up_names, template_alts)]
        practices, source = explanation_parsed.key_practices[:3], "llm"
    else:
        explanation, runner_ups = _template_explanation(scores)
        practices, source = [], "template"

    confidence = "Low" if too_little_evidence else confidence_with_coverage(scores, factors_scored)
    return SDLCOutput(recommended_model=scores[0].model, confidence=confidence,
                      ranking=ranking, factors=factors, explanation=explanation,
                      runner_up_explanations=runner_ups, key_practices=practices,
                      explanation_source=source, factors_scored=factors_scored, scoring_basis=basis)


def render_for_next(output: SDLCOutput) -> str:
    ranking = ", ".join(f"{r.model} {r.score:.0f}%" for r in output.ranking[:3])
    factors = ", ".join(f"{FACTOR_LABELS[f.factor]}={f.rating}" for f in output.factors)
    return f"Recommended SDLC model: {output.recommended_model} (ranking: {ranking}).\nFactors: {factors}"
