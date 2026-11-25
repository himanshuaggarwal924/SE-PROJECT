"""
agents/requirements_agent.py - The Python side of the Requirements Agent.

The agent's prompt lives in prompts/requirements_agent.yaml. This module adds
what the LLM shouldn't do:

  plan_calls()      split the requested requirements into batches, so one
                    answer never exceeds MAX_OUTPUT_TOKENS (one call per batch)
  call_variables()  the batch-specific prompt text (which IDs to write, what
                    was already written - so batches don't repeat each other)
  combine()         merge the batches, assign IDs, run the deterministic
                    checks (citations, numbers, confidence) and set flags
  render_for_next() a compact text version for the next agent (saves tokens)
"""

import config
import re

from agents.schemas import (CompactRequirementDraft, Flag, Requirement, RequirementDraft, RequirementsBatch,
                            RequirementsCompactBatch, RequirementsOutput, normalise_citation)
from checks.confidence import combine as combine_confidence
from checks.confidence import confidence_components
from checks.grounding import check_grounding
from context_loader import chunks_visible_to, text_similarities

KIND_INFO = {
    "functional": ("FR", "FUNCTIONAL requirements (what the system must DO)"),
    "non_functional": ("NFR", "NON-FUNCTIONAL requirements (quality attributes: security, "
                              "privacy, performance, availability, audit, compliance)"),
}


def requested_counts(state) -> tuple[int, int]:
    options = state.get("options") or {}
    functional = int(options.get("num_functional", config.NUM_FUNCTIONAL_REQUIREMENTS))
    non_functional = int(options.get("num_non_functional", config.NUM_NON_FUNCTIONAL_REQUIREMENTS))
    limit = config.MAX_REQUIREMENTS_PER_KIND
    return max(0, min(functional, limit)), max(0, min(non_functional, limit))


def plan_calls(state) -> list[dict]:
    """One spec per model call, e.g. {"kind": "functional", "ids": ["FR-01", "FR-02", "FR-03"]}."""
    size = max(1, config.REQUIREMENTS_BATCH_SIZE)
    compact = config.REQUIREMENTS_PROMPT_MODE == "compact"
    specs = []
    for kind, count in zip(KIND_INFO, requested_counts(state)):
        prefix = KIND_INFO[kind][0]
        ids = [f"{prefix}-{n:02d}" for n in range(1, count + 1)]
        for i in range(0, len(ids), size):
            spec = {"kind": kind, "ids": ids[i:i + size]}
            if compact:
                spec.update(mode="compact", prompt="requirements_compact")
            specs.append(spec)
    return specs


def schema_for(spec: dict):
    return RequirementsCompactBatch if spec.get("mode") == "compact" else RequirementsBatch


HIGH_RISK_CATEGORIES = {"security", "privacy", "regulatory"}


def fill_compact(draft: CompactRequirementDraft, chunk_map: dict) -> RequirementDraft:
    """Compact mode: fill the fields the model was not asked for, with code.
    Kept deliberately neutral so the deterministic checks and reviewers decide."""
    kb_rules = [s for s in draft.sources if chunk_map.get(s, {}).get("origin") == "kb"]
    statement = draft.statement.strip().rstrip(".")
    action = re.sub(r"^\s*the system shall\s+", "", statement, flags=re.IGNORECASE)
    return RequirementDraft(
        id=draft.id, statement=draft.statement, categories=draft.categories, priority=draft.priority,
        sources=draft.sources, applicable_rules=kb_rules,
        risk_level="High" if HIGH_RISK_CATEGORIES & set(draft.categories) else "Medium",
        business_justification="See cited source." if draft.sources else "",
        acceptance_criteria=[{"given": "a case covered by this requirement", "when": "the system handles it",
                              "then": f"the system does {action}" if action else "the requirement is met"}],
        confidence=0.6)


def call_variables(spec: dict, state, earlier: list[tuple[dict, RequirementsBatch | None]]) -> dict:
    """Prompt variables for one batch."""
    written = []
    for earlier_spec, parsed in earlier:
        if parsed is not None:
            for rid, draft in zip(earlier_spec["ids"], parsed.requirements):
                written.append(f"{rid}: {draft.statement}")

    ids = spec["ids"]
    instruction = (f"Write exactly {len(ids)} {KIND_INFO[spec['kind']][1]}, "
                   f"with ids {', '.join(ids)}.")
    return {
        "batch_instruction": instruction,
        "already_written": "\n".join(written) or "None yet.",
        "category_list": ", ".join(config.REQUIREMENT_CATEGORIES),
    }


def adjust_schema(schema: dict, spec: dict) -> dict:
    """Force the batch to contain exactly as many requirements as planned
    (small models otherwise sometimes return fewer). Ollama turns minItems /
    maxItems into its output grammar, so this is enforced, not just asked."""
    schema = {**schema, "properties": dict(schema["properties"])}
    schema["properties"]["requirements"] = {**schema["properties"]["requirements"],
                                            "minItems": len(spec["ids"]),
                                            "maxItems": len(spec["ids"])}
    return schema


def citation_support(requirements: list[Requirement], chunk_map: dict):
    """One embedding call (in the worker) for every statement and every cited
    excerpt. Returns ({requirement ID: {citation ID: similarity}},
    statement-by-statement similarity matrix), or ({}, None) if unavailable."""
    if not config.CITATION_SUPPORT_CHECK or not requirements:
        return {}, None
    cited = sorted({s for r in requirements for s in r.sources if s in chunk_map})
    texts = [r.statement for r in requirements] + [chunk_map[c]["text"] for c in cited]
    try:
        matrix = text_similarities(texts)
    except Exception:
        return {}, None      # no embeddings: confidence falls back to retrieval scores
    n = len(requirements)
    support = {r.id: {c: round(matrix[i][n + cited.index(c)], 3) for c in r.sources if c in chunk_map}
               for i, r in enumerate(requirements)}
    return support, [row[:n] for row in matrix[:n]]


def check_requirement(requirement: Requirement, chunk_map: dict, input_text: str,
                      support: dict[str, float] | None = None) -> Requirement:
    """Run the deterministic checks on one requirement and fill in the
    computed fields (sources cleaned, flags, confidence, needs_human_review).
    support: {citation ID: claim-support similarity}, if it was computed."""
    # applicable_rules may only name KB excerpts that were shown. Anything else
    # (a made-up regulation name, a document excerpt) is removed and flagged.
    rules, bad_rules = [], []
    for rule in requirement.applicable_rules:
        rid = normalise_citation(rule)
        if chunk_map.get(rid, {}).get("origin") == "kb":
            rules.append(rid)
        else:
            bad_rules.append(rule)
    requirement = requirement.model_copy(update={"applicable_rules": list(dict.fromkeys(rules))})

    grounding = check_grounding(requirement, chunk_map, input_text)
    # Citations are expected when the user gave a document or interviews; KB citations are optional.
    has_document = any(c.get("origin", "document") in ("document", "transcript")
                       for c in chunk_map.values())
    # A requirement citing interview answers takes its stakeholder from them
    # (deterministic - more reliable than the model's guess).
    answers = [chunk_map[s] for s in grounding.valid_sources if chunk_map[s].get("origin") == "transcript"]
    if answers:
        who = [f"{a['stakeholder']} ({a['speaker_role']})" if a.get("stakeholder") else a["speaker_role"]
               for a in answers]
        requirement = requirement.model_copy(update={"source_stakeholder": "; ".join(dict.fromkeys(who))})
    flags = [Flag(type="invalid_citation", detail=f"{s} is not one of the excerpts shown")
             for s in grounding.invalid_sources]
    flags += [Flag(type="unsupported_rule", detail=f"'{r}' is not a knowledge-base excerpt (removed)")
              for r in bad_rules]
    if has_document and not grounding.valid_sources:
        flags.append(Flag(type="missing_citation", detail="No valid excerpt cited"))
    flags += [Flag(type="possible_hallucination", detail=f"Number {n} is not in any source")
              for n in grounding.ungrounded_numbers]
    flags += [Flag(type="uncited_number", detail=f"Number {n} is in the document but not in the cited excerpts")
              for n in grounding.uncited_numbers]
    support = support or {}
    flags += [Flag(type="weak_citation",
                   detail=f"{cid} barely relates to the statement (similarity {support[cid]:.2f})")
              for cid in grounding.valid_sources
              if cid in support and support[cid] < config.CITATION_SUPPORT_MIN]

    components = confidence_components(requirement.model_confidence, grounding, chunk_map,
                                       has_document, support)
    confidence = combine_confidence(components)
    if confidence < config.CONFIDENCE_REVIEW_THRESHOLD:
        flags.append(Flag(type="low_confidence",
                          detail=f"{confidence:.2f} < {config.CONFIDENCE_REVIEW_THRESHOLD}"))

    return requirement.model_copy(update={
        "sources": grounding.valid_sources,
        "flags": flags,
        "confidence": confidence,
        "confidence_breakdown": components,
        "needs_human_review": any(f.type in ("low_confidence", "possible_hallucination") for f in flags),
    })


def combine(calls: list[tuple[dict, RequirementsBatch | None]], state) -> RequirementsOutput | None:
    """Merge all batches into the final, checked RequirementsOutput.
    Returns None if no batch could be parsed at all."""
    if all(parsed is None for _, parsed in calls):
        return None

    chunk_map = chunks_visible_to(state.get("chunk_map") or {}, "requirements")
    input_text = state.get("scenario", "")
    summary, requirements = "", []
    planned = sum(len(spec["ids"]) for spec, _ in calls)

    for spec, parsed in calls:
        if parsed is None:
            continue
        summary = summary or parsed.scenario_summary
        # zip() drops extra requirements the model wrote beyond the planned IDs.
        for rid, draft in zip(spec["ids"], parsed.requirements):
            if isinstance(draft, CompactRequirementDraft):
                draft = fill_compact(draft, chunk_map)
            requirements.append(Requirement(**{**draft.model_dump(), "id": rid, "kind": spec["kind"],
                                               "model_confidence": draft.confidence}))

    known_ids = {r.id for r in requirements}
    for requirement in requirements:
        requirement.dependencies = [d for d in requirement.dependencies
                                    if d in known_ids and d != requirement.id]
    support, statement_matrix = citation_support(requirements, chunk_map)
    checked = [check_requirement(r, chunk_map, input_text, support.get(r.id)) for r in requirements]
    output = build_output(summary, checked, planned, sum(1 for _, p in calls if p is None))
    if statement_matrix is not None:
        output.statement_similarity = statement_matrix
    return output


def build_output(summary: str, checked: list[Requirement], planned: int,
                 failed_batches: int) -> RequirementsOutput:
    """Assemble the final output and its validation summary."""
    assumptions = list(dict.fromkeys(a for r in checked for a in r.assumptions))
    flag_counts = {}
    for requirement in checked:
        for flag in requirement.flags:
            flag_counts[flag.type] = flag_counts.get(flag.type, 0) + 1

    return RequirementsOutput(
        scenario_summary=summary,
        requirements=checked,
        assumptions=assumptions,
        validation_summary={
            "requested": planned,
            "produced": len(checked),
            "failed_batches": failed_batches,
            "needs_human_review": sum(r.needs_human_review for r in checked),
            "flag_counts": flag_counts,
            "mean_confidence": round(sum(r.confidence for r in checked) / len(checked), 3) if checked else 0,
        },
    )


def render_for_next(output: RequirementsOutput) -> str:
    """One compact line per requirement, for the agents that come after."""
    lines = []
    for r in output.requirements:
        tags = ", ".join(r.categories)
        lines.append(f"{r.id} [{tags}] (priority {r.priority}, risk {r.risk_level}): {r.statement}")
    return "\n".join(lines) or "(no requirements were produced)"
