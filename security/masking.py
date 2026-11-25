"""
security/masking.py - Masks sensitive data before any text reaches the model.

Detected (deterministic regexes, most specific first):
  CARD      13-19 digits (spaces/dashes allowed) that pass the Luhn check
  AADHAAR   12 digits in groups of 4, not starting with 0 or 1
  PAN       Indian PAN: 5 letters, 4 digits, 1 letter (ABCDE1234F)
  IFSC      4 letters, "0", 6 letters/digits (HDFC0001234)
  ACCOUNT   9-18 digit number next to "account", "a/c" or "acct"
  PHONE     Indian mobile (+91 optional, 10 digits starting 6-9) or +<country> numbers
  EMAIL     name@domain.tld
  NAME      the value of an obvious name field ("Name: …", "Customer name: …")

Each value becomes a typed placeholder (<PAN_1>, <EMAIL_2>, ...). The same
value always gets the same placeholder within one Masker, so the text still
reads consistently. The reversible mapping stays in the Masker object (local
memory only) - it is never put into prompts or the audit log; only the
COUNT of each type is logged.
"""

import re

LUHN_CANDIDATE = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
PATTERNS = [
    # Not part of a longer digit group (e.g. a 16-digit number that failed the card check).
    ("AADHAAR", re.compile(r"(?<!\d)(?<!\d[ -])[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?![ -]?\d)")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("ACCOUNT", re.compile(r"(?i)(?:\ba/c|\bacct|\baccount)(?:\s*(?:no\.?|number|#))?\s*[:\-]?\s*(\d{9,18})\b")),
    ("PHONE", re.compile(r"(?<![\w+])(?:\+91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)|\+\d{1,3}[ -]?\d{6,12}(?!\d)")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    # The value of an obvious name field; words separated by spaces/tabs only (never a newline),
    # initials allowed ("Anil K Rao").
    ("NAME", re.compile(r"(?im)^[ \t]*(?:[-*][ \t]*)?(?:full[ \t]+|customer[ \t]+|applicant[ \t]+|"
                        r"account[ \t]+holder[ \t]+)?name[ \t]*[:\-][ \t]*"
                        r"([A-Z][A-Za-z.'-]*(?:[ \t]+[A-Z][A-Za-z.'-]*){0,3})")),
]


def luhn_ok(digits: str) -> bool:
    total, double = 0, False
    for ch in reversed(digits):
        n = int(ch)
        if double:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
        double = not double
    return total % 10 == 0


class Masker:
    """Masks text, remembering value -> placeholder for this run."""

    def __init__(self):
        self.mapping: dict[str, str] = {}          # placeholder -> original (never logged)
        self._by_value: dict[tuple, str] = {}
        self.counts: dict[str, int] = {}

    def _placeholder(self, kind: str, value: str) -> str:
        key = (kind, re.sub(r"[ -]", "", value))
        if key not in self._by_value:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            placeholder = f"<{kind}_{self.counts[kind]}>"
            self._by_value[key] = placeholder
            self.mapping[placeholder] = value
        return self._by_value[key]

    def mask(self, text: str) -> str:
        if not text:
            return text

        def card(match):
            digits = re.sub(r"[ -]", "", match.group())
            return self._placeholder("CARD", match.group()) if luhn_ok(digits) else match.group()
        text = LUHN_CANDIDATE.sub(card, text)
        for kind, pattern in PATTERNS:
            def replace(match, kind=kind):
                if match.lastindex and match.group(match.lastindex):
                    value = match.group(match.lastindex)          # only the captured value
                    start, end = match.span(match.lastindex)
                    whole = match.group()
                    offset = match.start()
                    return whole[:start - offset] + self._placeholder(kind, value) + whole[end - offset:]
                return self._placeholder(kind, match.group())
            text = pattern.sub(replace, text)
        return text

    def mask_name(self, name: str) -> str:
        """A person's name from a structured field (e.g. an interviewee)."""
        return self._placeholder("NAME", name.strip()) if name and name.strip() else name

    def unmask(self, text: str) -> str:
        """Restore originals (local display only - never send the result to the model)."""
        for placeholder, value in self.mapping.items():
            text = text.replace(placeholder, value)
        return text

    @property
    def summary(self) -> dict[str, int]:
        return dict(self.counts)


def mask_text(text: str) -> tuple[str, dict[str, int]]:
    """One-off masking: (masked text, counts per type)."""
    masker = Masker()
    return masker.mask(text), masker.summary
