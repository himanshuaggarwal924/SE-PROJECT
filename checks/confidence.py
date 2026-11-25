"""
checks/confidence.py - Combines several signals into one 0-1 confidence score.

The formula and its weights are documented in config.py (CONFIDENCE_WEIGHTS).
"""

import config
from checks.grounding import GroundingResult


def rescale_similarity(similarity: float) -> float:
    """Map a raw cosine similarity onto 0-1 using the configured floor/ceiling
    (MiniLM similarities for relevant text are typically ~0.3-0.6)."""
    low, high = config.RETRIEVAL_SIMILARITY_FLOOR, config.RETRIEVAL_SIMILARITY_CEIL
    return min(max((similarity - low) / (high - low), 0.0), 1.0)


def confidence_components(self_rating: float, grounding: GroundingResult,
                          chunk_map: dict, has_document: bool,
                          support: dict[str, float] | None = None) -> dict[str, float]:
    """The individual 0-1 signals. A signal that doesn't apply is left out.

    support: {citation ID: similarity between the statement and that excerpt}
             (claim support). Preferred over the excerpts' retrieval scores.
    """
    components = {"self_rating": self_rating}

    support = support or {}
    similarities = [support[s] for s in grounding.valid_sources if s in support]
    if not similarities:
        similarities = [chunk_map[s]["similarity"] for s in grounding.valid_sources
                        if chunk_map[s].get("similarity") is not None]
    if similarities:
        components["retrieval_similarity"] = rescale_similarity(sum(similarities) / len(similarities))

    cited = len(grounding.valid_sources) + len(grounding.invalid_sources)
    if cited:
        components["citation_validity"] = len(grounding.valid_sources) / cited
    elif has_document:
        components["citation_validity"] = 0.0   # a document existed but nothing was cited

    if grounding.number_count:
        score = len(grounding.grounded_numbers) + 0.5 * len(grounding.uncited_numbers)
        components["number_grounding"] = score / grounding.number_count
    else:
        components["number_grounding"] = 1.0

    return {name: round(value, 3) for name, value in components.items()}


def combine(components: dict[str, float]) -> float:
    """Weighted mean over the available components (weights re-normalised)."""
    weights = {name: config.CONFIDENCE_WEIGHTS.get(name, 0.0) for name in components}
    total = sum(weights.values())
    if total == 0:
        return 0.0
    return round(sum(components[n] * w for n, w in weights.items()) / total, 3)
