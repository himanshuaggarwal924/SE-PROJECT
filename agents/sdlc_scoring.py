"""
agents/sdlc_scoring.py - Deterministic multi-criteria SDLC scoring.

The LLM rates the 13 decision factors (High/Medium/Low); this module turns
those ratings into a ranked list of SDLC models using the weight/rule table
in config/sdlc_rules.yaml (the formula is documented there). No LLM here.
"""

from dataclasses import dataclass, field
from functools import lru_cache

import yaml

import config

DECISION_FACTORS = [
    "requirement_stability", "regulatory_criticality", "security_risk", "complexity",
    "system_size", "legacy_dependence", "change_frequency", "continuous_delivery_need",
    "stakeholder_availability", "testing_documentation_needs", "budget_schedule_constraints",
    "formal_verification_need", "failure_consequences",
]
FACTOR_LABELS = {f: f.replace("_", " ").capitalize() for f in DECISION_FACTORS}
FACTOR_LABELS.update({"budget_schedule_constraints": "Budget/schedule constraints",
                      "testing_documentation_needs": "Testing/documentation needs"})


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_rules() -> dict:
    return _load(str(config.SDLC_RULES_FILE))


@dataclass
class ModelScore:
    model: str
    score: float                                   # 0-100
    rank: int = 0
    contributions: list[dict] = field(default_factory=list)   # per factor: fit and weight
    adjustments: list[dict] = field(default_factory=list)     # rules that fired


def _preference(spec) -> tuple[str, float]:
    if isinstance(spec, dict):
        return spec["prefer"], float(spec.get("importance", 1))
    return spec, 1.0


def score_models(ratings: dict[str, str], rules: dict | None = None) -> list[ModelScore]:
    """Rank every model in the rule table. `ratings`: factor -> High/Medium/Low.
    A factor that is NOT in `ratings` (e.g. no evidence) is left out of the
    score entirely, and rules that depend on it don't fire."""
    rules = rules or load_rules()
    levels, weights = rules["levels"], rules["factor_weights"]
    value = {f: levels.get(ratings[f], 0.5) for f in DECISION_FACTORS if f in ratings}

    neutral = float(rules.get("neutral_importance", 0.0))
    scores, raw = [], {}
    for model, preferences in rules["models"].items():
        total = weighted = 0.0
        contributions = []
        for factor in DECISION_FACTORS:
            if factor not in value:
                continue                # not scored (no evidence)
            if factor in preferences:
                prefer, importance = _preference(preferences[factor])
                fit = 1 - abs(value[factor] - levels[prefer])
                contributions.append({"factor": factor, "rating": ratings[factor],
                                      "prefers": prefer, "fit": round(fit, 2),
                                      "weight": round(weights.get(factor, 1.0) * importance, 2)})
            else:                       # a factor this model is indifferent to
                importance, fit = neutral, 0.5
            weight = weights.get(factor, 1.0) * importance
            total += weight
            weighted += weight * fit
        score = 100 * weighted / total if total else 0.0

        adjustments = []
        for rule in rules.get("rules", []):
            if all(ratings.get(f) == level for f, level in rule["when"].items()) \
                    and model in rule["adjust"]:
                points = rule["adjust"][model]
                score += points
                adjustments.append({"points": points, "reason": rule["reason"]})
        raw[model] = score
        scores.append(ModelScore(model, round(min(max(score, 0.0), 100.0), 1),
                                 contributions=contributions, adjustments=adjustments))

    # Highest raw score first (ties broken by the order in the YAML: stable sort).
    scores.sort(key=lambda s: -raw[s.model])
    for rank, s in enumerate(scores, start=1):
        s.rank = rank
    return scores


def confidence_from_gap(scores: list[ModelScore]) -> str:
    """How clear the winner is: High if it leads by 10+ points, Medium 4+, else Low."""
    if len(scores) < 2:
        return "High"
    gap = scores[0].score - scores[1].score
    return "High" if gap >= 10 else "Medium" if gap >= 4 else "Low"


def confidence_with_coverage(scores: list[ModelScore], factors_scored: int) -> str:
    """The gap-based confidence, capped by how many factors had evidence:
    High needs >= SDLC_HIGH_CONFIDENCE_FACTORS, Medium >= SDLC_MEDIUM_CONFIDENCE_FACTORS."""
    order = ["Low", "Medium", "High"]
    if factors_scored >= config.SDLC_HIGH_CONFIDENCE_FACTORS:
        cap = "High"
    elif factors_scored >= config.SDLC_MEDIUM_CONFIDENCE_FACTORS:
        cap = "Medium"
    else:
        cap = "Low"
    return min(confidence_from_gap(scores), cap, key=order.index)


def describe_score(s: ModelScore, top: int = 3) -> str:
    """Short text of a model's best and worst fitting factors, for the explainer prompt."""
    ranked = sorted(s.contributions, key=lambda c: -c["weight"] * c["fit"])
    good = [f"{FACTOR_LABELS[c['factor']]}={c['rating']}" for c in ranked if c["fit"] >= 0.75][:top]
    bad = [f"{FACTOR_LABELS[c['factor']]}={c['rating']} (prefers {c['prefers']})"
           for c in ranked if c["fit"] <= 0.25][:top]
    parts = [f"{s.model}: {s.score:.0f}%"]
    if good:
        parts.append("fits " + ", ".join(good))
    if bad:
        parts.append("mismatches " + ", ".join(bad))
    parts += [f"rule {a['points']:+g}: {a['reason']}" for a in s.adjustments]
    return "; ".join(parts)


def load_workflow_template(model: str) -> dict | None:
    """The YAML workflow template whose `model:` equals the given model name."""
    for path in sorted(config.SDLC_WORKFLOWS_DIR.glob("*.yaml")):
        template = _load(str(path))
        if template.get("model") == model:
            return template
    return None
