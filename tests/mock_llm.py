"""
tests/mock_llm.py - A fake LLM so the pipeline can be tested without Ollama.

It replaces llm_service.chat(). Each agent sends the JSON schema of one
call's answer (see orchestration/nodes.py), and the schema's "title" is the
name of the Pydantic class (e.g. "RequirementsBatch"). The mock looks that
title up in `responses` and returns the canned answer, so the mock keeps
working when prompts are edited.

A response can be a string, a dict (sent as JSON), or a function
(system_prompt, user_prompt) -> str|dict for answers that depend on the prompt.
Every call is recorded in `calls` so tests can check what each agent received.
"""

import inspect
import json
import re
from dataclasses import dataclass, field

from llm_service import LLMResponse


def make_requirement(rid: str, **overrides) -> dict:
    functional = rid.startswith("FR")
    requirement = {
        "id": rid,
        "statement": f"The system shall do thing {rid}.",
        "categories": ["functional"] if functional else ["security", "privacy"],
        "source_stakeholder": "Credit risk team",
        "business_justification": "Required by the loan policy.",
        "priority": "High",
        "dependencies": [],
        "assumptions": ["A credit bureau integration is available."],
        "acceptance_criteria": [{"given": "an application", "when": "it is submitted",
                                 "then": "it is stored"}],
        "applicable_rules": [],
        "risk_level": "Medium",
        "sources": [],
        "confidence": 0.9,
    }
    requirement.update(overrides)
    return requirement


def requirements_batch(system_prompt: str, user_prompt: str) -> dict:
    """Answer a Requirements Agent batch with exactly the IDs it asked for."""
    task = user_prompt.split("YOUR TASK NOW:")[-1]
    ids = re.findall(r"\bN?FR-\d+\b", task.split("EXPECTED OUTPUT")[0])
    return {"scenario_summary": "Online personal loan applications with automated decisions.",
            "requirements": [make_requirement(rid) for rid in ids]}


def _schema_ids(schema: dict, draft_name: str) -> list[str]:
    """The requirement IDs a batch must answer for (the schema's enum)."""
    return schema["$defs"][draft_name]["properties"]["requirement_id"]["enum"]


def quality_batch(system_prompt: str, user_prompt: str, schema: dict) -> dict:
    return {"reviews": [
        {"requirement_id": rid,
         "issues": [{"type": "lack_of_testability", "explanation": f"{rid} has no measurable target.",
                     "severity": "Medium"}] if rid.startswith("NFR") else [],
         "clarification_questions": [{"question": f"What is the target for {rid}?",
                                      "stakeholder_role": "Product owner"}] if rid.startswith("NFR") else []}
        for rid in _schema_ids(schema, "RequirementReviewDraft")]}


def compliance_batch(system_prompt: str, user_prompt: str, schema: dict) -> dict:
    return {"mappings": [
        {"requirement_id": rid, "applicable_rules": ["KB-1"], "required_controls": ["Encryption"],
         "evidence": ["KB-1"], "compliance_gaps": [], "approval_checkpoints": ["Compliance sign-off"],
         "retention_reporting_obligations": [], "impact": "Medium"}
        for rid in _schema_ids(schema, "ComplianceMappingDraft")]}


# A typical regulated, security-heavy, changing finance project.
CANNED_FACTOR_RATINGS = {
    "requirement_stability": "Medium", "regulatory_criticality": "High", "security_risk": "High",
    "complexity": "Medium", "system_size": "Medium", "legacy_dependence": "Low",
    "change_frequency": "High", "continuous_delivery_need": "High",
    "stakeholder_availability": "High", "testing_documentation_needs": "High",
    "budget_schedule_constraints": "Medium", "formal_verification_need": "Medium",
    "failure_consequences": "High",
}


def sdlc_factors(system_prompt: str, user_prompt: str) -> dict:
    return {"factors": [{"factor": f, "rating": r, "evidence": ["FR-01"], "reasoning": f"{f} is {r}."}
                        for f, r in CANNED_FACTOR_RATINGS.items()]}


def sdlc_explanation(system_prompt: str, user_prompt: str, schema: dict) -> dict:
    names = schema["$defs"]["Alternative"]["properties"]["model"]["enum"]
    return {"top_choice_explanation": "It fits the high security and change needs.",
            "runner_up_explanations": [{"model": n, "reason_not_chosen": f"{n} fits less well."}
                                       for n in names],
            "key_practices": ["Threat modelling", "Automated security tests", "Sprint reviews"]}


def workflow_customisation(system_prompt: str, user_prompt: str, schema: dict) -> dict:
    names = schema["$defs"]["PhaseCustomisationDraft"]["properties"]["phase"]["enum"]
    return {"phases": [{"phase": n, "extra_activities": [f"Project activity for {n}"],
                        "extra_security_activities": [], "extra_testing": ["Credit bureau integration test (FR-01)"],
                        "extra_compliance_checkpoints": [], "project_notes": ""} for n in names]}


def interview_turn(system_prompt: str, user_prompt: str) -> dict:
    """'vague' for answers containing 'not sure', otherwise 'complete'."""
    answer = user_prompt.split("ANSWER:", 1)[1].split("\n", 1)[0]
    return {"assessment": "vague" if "not sure" in answer.lower() else "complete",
            "reason": "mock", "follow_up_question": "MOCK FOLLOW-UP?",
            "next_question": "MOCK NEXT QUESTION?"}


def baseline_output(system_prompt: str, user_prompt: str, schema: dict) -> dict:
    count = schema["properties"]["requirements"]["minItems"]
    return {"requirements": [{"statement": f"The system shall do baseline thing {n}.", "categories": ["functional"]}
                             for n in range(1, count + 1)],
            "sdlc_model": schema["properties"]["sdlc_model"]["enum"][0]}


DEFAULT_RESPONSES = {
    "BaselineOutput": baseline_output,
    "RequirementsCompactBatch": requirements_batch,        # extra fields are ignored
    "InterviewTurnDraft": interview_turn,
    "RequirementsBatch": requirements_batch,
    "QualityBatch": quality_batch,
    "ComplianceBatch": compliance_batch,
    "SDLCFactorsBatch": sdlc_factors,
    "SDLCExplanationDraft": sdlc_explanation,
    "WorkflowCustomisation": workflow_customisation,
}


@dataclass
class MockCall:
    schema_title: str | None
    system_prompt: str
    user_prompt: str
    model_name: str
    json_schema: dict | None = None


@dataclass
class MockLLM:
    responses: dict = field(default_factory=lambda: dict(DEFAULT_RESPONSES))
    calls: list[MockCall] = field(default_factory=list)

    def chat(self, system_prompt, user_prompt, model_name="mock", json_schema=None, **kwargs):
        title = (json_schema or {}).get("title")
        self.calls.append(MockCall(title, system_prompt, user_prompt, model_name, json_schema))
        if title not in self.responses:
            raise AssertionError(f"MockLLM has no canned response for schema {title!r}")

        answer = self.responses[title]
        if callable(answer):
            # Functions may take (system, user) or (system, user, json_schema).
            takes_schema = len(inspect.signature(answer).parameters) >= 3
            answer = (answer(system_prompt, user_prompt, json_schema) if takes_schema
                      else answer(system_prompt, user_prompt))
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return LLMResponse(text=text, prompt_tokens=len(user_prompt) // 4,
                           output_tokens=len(text) // 4, seconds=0.0)

    def calls_for(self, schema_title: str) -> list[MockCall]:
        return [c for c in self.calls if c.schema_title == schema_title]
