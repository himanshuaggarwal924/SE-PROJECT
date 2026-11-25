"""
checks/quality.py - Deterministic requirement-quality checks (no LLM).

Run before the Quality & Clarification Agent; their findings are shown to
the model and also kept as issues with origin "rule".

  rule_issues()  vague words, unmeasurable NFRs, missing actor, missing source
  duplicates()   near-duplicate pairs (embedding or word-overlap similarity)
  conflicts()    same subject + contradictory values, or "shall" vs "shall not"
"""

import re

import config
from agents.schemas import QualityIssue
from checks.grounding import extract_numbers

STOPWORDS = {
    "the", "system", "shall", "must", "will", "should", "and", "for", "with", "within",
    "all", "any", "each", "every", "that", "this", "are", "from", "into", "when", "than",
    "not", "per", "least", "most", "have", "has", "been", "its", "their", "his", "her",
    "via", "using", "use", "able", "allow", "allows", "provide", "provides", "ensure",
}
# A number, up to two describing words, then a unit: "3 seconds", "5 failed login attempts".
UNIT_PATTERN = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(?:[a-z-]+\s+){0,2}?(%|percent|ms|milliseconds?|seconds?|secs?|minutes?|"
    r"mins?|hours?|hrs?|days?|weeks?|months?|years?|attempts?|times?|transactions?|users?|requests?)\b",
    re.IGNORECASE)
UNIT_ALIASES = {"percent": "%", "secs": "second", "sec": "second", "mins": "minute", "min": "minute",
                "hrs": "hour", "hr": "hour", "milliseconds": "ms", "millisecond": "ms"}
# Money: "₹5 lakh", "Rs. 10,00,000", "INR 50,000", "2 crore". Counted as money
# only with a currency sign or a lakh/crore word; converted to rupees.
MONEY_PATTERN = re.compile(
    r"(₹|\brs\.?|\binr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr)?\b", re.IGNORECASE)
MONEY_MULTIPLIERS = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
                     "crore": 1e7, "crores": 1e7, "cr": 1e7}
ACTOR_PATTERN = re.compile(r"^\s*(the\s+)?[a-z][\w\s/-]{0,40}?\s+shall\b", re.IGNORECASE)
MEASURABLE_CATEGORIES = {"performance", "availability/reliability", "usability"}


def content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z][a-z-]{2,}", (text or "").lower())
    return {w for w in words if w not in STOPWORDS}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def find_vague_words(text: str) -> list[str]:
    lowered = f" {(text or '').lower()} "
    found = []
    for word in config.QUALITY_VAGUE_WORDS:
        if re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", lowered):
            found.append(word)
    return found


def _all_text(requirement: dict) -> str:
    parts = [requirement.get("statement", "")]
    for c in requirement.get("acceptance_criteria", []):
        parts += [c.get("given", ""), c.get("when", ""), c.get("then", "")]
    return " ".join(parts)


def rule_issues(requirement: dict) -> list[QualityIssue]:
    """Single-requirement checks. `requirement` is a Requirement as a dict."""
    issues = []
    statement = requirement.get("statement", "")
    has_number = bool(extract_numbers(_all_text(requirement)))

    vague = find_vague_words(statement)
    if vague:
        issues.append(QualityIssue(
            type="ambiguity", origin="rule", severity="Low" if has_number else "Medium",
            explanation=f"Vague term(s) {', '.join(repr(v) for v in vague)} "
                        f"{'- check they are backed by the measurable value' if has_number else 'without a measurable criterion'}."))

    if requirement.get("kind") == "non_functional" and not has_number:
        measurable = MEASURABLE_CATEGORIES & set(requirement.get("categories", []))
        issues.append(QualityIssue(
            type="lack_of_testability", origin="rule", severity="High" if measurable else "Medium",
            explanation="Non-functional requirement has no measurable target value."))

    if "shall" not in statement.lower():
        issues.append(QualityIssue(type="ambiguity", origin="rule", severity="Medium",
                                   explanation="Not written as 'The <actor> shall ...'."))
    elif not ACTOR_PATTERN.match(statement):
        issues.append(QualityIssue(type="incompleteness", origin="rule", severity="Medium",
                                   explanation="No actor before 'shall' (who performs it?)."))

    if not requirement.get("sources") and not requirement.get("source_stakeholder"):
        issues.append(QualityIssue(
            type="incompleteness", origin="rule", severity="Low",
            explanation="No source excerpt or stakeholder recorded, so it can't be traced."))
    return issues


def duplicates(requirements: list[dict], similarity: list[list[float]] | None = None) -> list[dict]:
    """Near-duplicate pairs. With an embedding similarity matrix, pairs above
    QUALITY_DUPLICATE_THRESHOLD; otherwise word-overlap above the lexical threshold."""
    pairs = []
    words = [content_words(r.get("statement", "")) for r in requirements]
    for i in range(len(requirements)):
        for j in range(i + 1, len(requirements)):
            if similarity is not None:
                score, threshold, method = similarity[i][j], config.QUALITY_DUPLICATE_THRESHOLD, "embedding"
            else:
                score, threshold, method = (jaccard(words[i], words[j]),
                                            config.QUALITY_LEXICAL_DUPLICATE_THRESHOLD, "lexical")
            if score >= threshold:
                pairs.append({"ids": [requirements[i]["id"], requirements[j]["id"]],
                              "similarity": round(float(score), 3), "method": method})
    return pairs


def _format_rupees(value: float) -> str:
    """Indian style: ₹2 crore, ₹5 lakh, ₹12.5 lakh, ₹50,000."""
    for size, word in ((1e7, "crore"), (1e5, "lakh")):
        if value >= size:
            return f"₹{value / size:g} {word}"
    return f"₹{value:,.0f}"


def quantities(text: str) -> dict[str, set[str]]:
    """{unit: {values}} for numbers with a unit, e.g. {"second": {"3"}, "INR": {"₹500,000"}}."""
    found: dict[str, set[str]] = {}
    for number, unit in UNIT_PATTERN.findall(text or ""):
        unit = unit.lower()
        unit = UNIT_ALIASES.get(unit, unit.rstrip("s") if len(unit) > 2 else unit)
        found.setdefault(unit, set()).add(number.replace(",", ""))
    for currency, number, multiplier in MONEY_PATTERN.findall(text or ""):
        if not currency and not multiplier:
            continue
        value = float(number.replace(",", "")) * MONEY_MULTIPLIERS.get(multiplier.lower(), 1)
        found.setdefault("INR", set()).add(_format_rupees(value))
    return found


_quantities = quantities     # older name, used below


def conflicts(requirements: list[dict]) -> list[dict]:
    """Possible conflicts between two requirements about the same subject:
    different values for the same unit, or one says "shall not"."""
    found = []
    for i, a in enumerate(requirements):
        for b in requirements[i + 1:]:
            text_a, text_b = a.get("statement", ""), b.get("statement", "")
            overlap = jaccard(content_words(text_a), content_words(text_b))
            if overlap < config.QUALITY_CONFLICT_SUBJECT_OVERLAP:
                continue
            qa, qb = _quantities(_all_text(a)), _quantities(_all_text(b))
            for unit in qa.keys() & qb.keys():
                if qa[unit] != qb[unit] and not (qa[unit] & qb[unit]):
                    found.append({"ids": [a["id"], b["id"]],
                                  "detail": f"Different values for the same subject: "
                                            f"{'/'.join(sorted(qa[unit]))} vs {'/'.join(sorted(qb[unit]))} {unit}"})
            negated_a = "shall not" in text_a.lower()
            negated_b = "shall not" in text_b.lower()
            if negated_a != negated_b and overlap >= 0.5:
                found.append({"ids": [a["id"], b["id"]],
                              "detail": "One requirement says 'shall not' about the same subject."})
    return found
