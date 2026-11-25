"""
checks/grounding.py - Is a requirement backed by its sources?

Two deterministic checks, no LLM involved:

1. Citation validation - every ID in `sources` must be an excerpt that was
   actually shown to the model (the chunk map). Invalid IDs are removed and
   flagged as "invalid_citation".

2. Number grounding - every number in the requirement (amounts, %, days,
   limits...) must appear in a cited excerpt or in the typed description.
     found in cited excerpt / description -> grounded
     found only in an excerpt NOT cited   -> "uncited_number" (weak flag)
     found nowhere                        -> "possible_hallucination"
"""

import re
from dataclasses import dataclass, field

import config

# Requirement / citation IDs contain digits that are not "facts": FR-01, NFR-2, C3, KB-LOAN-01.
ID_PATTERN = re.compile(r"\b(?:N?FR|C|KB(?:-[A-Z]+)*)-?\d+\b", re.IGNORECASE)
# A number: 50,000 | 50000 | 99.9 | 30 (in "30-day") | 5 (in "5%"),
# but not digits glued to letters like "2FA" or "v2a".
NUMBER_PATTERN = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?!\w)")


def normalise_number(text: str) -> str:
    """'50,000' -> '50000', '99.90' -> '99.9', '007' -> '7', '5.0' -> '5'."""
    text = text.replace(",", "")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.lstrip("0") or "0"


def extract_numbers(text: str) -> set[str]:
    """All numbers in a text, normalised, ignoring IDs and trivial numbers."""
    text = ID_PATTERN.sub(" ", text or "")
    numbers = {normalise_number(m.group().rstrip(",")) for m in NUMBER_PATTERN.finditer(text)}
    return numbers - config.GROUNDING_IGNORED_NUMBERS


def requirement_text(requirement) -> str:
    """Every piece of text in a requirement that could contain a number."""
    parts = [requirement.statement, requirement.business_justification,
             *requirement.applicable_rules, *requirement.assumptions]
    for criterion in requirement.acceptance_criteria:
        parts += [criterion.given, criterion.when, criterion.then]
    return "\n".join(p for p in parts if p)


@dataclass
class GroundingResult:
    valid_sources: list[str]
    invalid_sources: list[str]
    grounded_numbers: list[str] = field(default_factory=list)
    uncited_numbers: list[str] = field(default_factory=list)       # in an uncited excerpt
    ungrounded_numbers: list[str] = field(default_factory=list)    # nowhere

    @property
    def number_count(self) -> int:
        return len(self.grounded_numbers) + len(self.uncited_numbers) + len(self.ungrounded_numbers)


def check_grounding(requirement, chunk_map: dict, input_text: str) -> GroundingResult:
    """Run both checks for one requirement.

    chunk_map:  {"C1": {"text": ..., ...}, ...} - the excerpts shown to the model
    input_text: the user's typed description (always a valid source of numbers)
    """
    valid = [s for s in requirement.sources if s in chunk_map]
    invalid = [s for s in requirement.sources if s not in chunk_map]

    cited_numbers = extract_numbers(input_text)
    for source in valid:
        cited_numbers |= extract_numbers(chunk_map[source]["text"])
    all_context_numbers = set(cited_numbers)
    for chunk in chunk_map.values():
        all_context_numbers |= extract_numbers(chunk["text"])

    result = GroundingResult(valid_sources=valid, invalid_sources=invalid)
    for number in sorted(extract_numbers(requirement_text(requirement))):
        if number in cited_numbers:
            result.grounded_numbers.append(number)
        elif number in all_context_numbers:
            result.uncited_numbers.append(number)
        else:
            result.ungrounded_numbers.append(number)
    return result
