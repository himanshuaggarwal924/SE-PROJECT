import pytest

import config
from agents import prompt_builder
from agents.registry import AGENT_PIPELINE, get_agent
from agents.schemas import RequirementsBatch, strict_json_schema


def test_fill_placeholders_leaves_json_alone():
    template = 'Scenario: {scenario}\n{"id": "FR-01"}'
    assert prompt_builder.fill_placeholders(template, {"scenario": "Loans"}) == \
        'Scenario: Loans\n{"id": "FR-01"}'


def test_missing_placeholder_value_raises():
    with pytest.raises(ValueError, match="unknown_field"):
        prompt_builder.fill_placeholders("{unknown_field}", {})


def test_prompt_with_missing_section_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "broken.yaml").write_text("role: x\ngoal: y\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROMPTS_DIR", tmp_path)
    with pytest.raises(ValueError, match="missing"):
        prompt_builder.load_prompt("broken")


@pytest.mark.parametrize("definition", AGENT_PIPELINE, ids=lambda d: d.key)
def test_every_registered_agent_has_a_valid_prompt(definition):
    from tests.mock_llm import make_requirement
    requirement = {**make_requirement("FR-01"), "kind": "functional"}
    state = {"scenario": "Loan approval", "reference_context": "CTX", "kb_context": "KB",
             "kb_context_full": "KB FULL",
             "agent_outputs": {"requirements_agent": {"parsed": {"requirements": [requirement]}},
                               "sdlc_agent": {"parsed": {"recommended_model": "Agile"}}}}
    variables = {k: v for k, v in state.items() if isinstance(v, str)}
    if definition.plan_calls:
        spec = definition.plan_calls(state)[0]
        variables.update(definition.call_variables(spec, state, []))
    system, user = prompt_builder.build_messages(definition, variables, {})
    assert system.startswith("You are a ")
    assert "Loan approval" in user
    assert "EXPECTED OUTPUT" in user


def test_previous_outputs_are_appended():
    sdlc = get_agent("sdlc_agent")
    _, user = prompt_builder.build_messages(
        sdlc, {"scenario": "Loans", "reference_context": "", "factor_definitions": "- x"},
        {"Requirements Agent": '{"functional_requirements": []}'})
    assert "OUTPUT FROM THE REQUIREMENTS AGENT (your input):" in user
    assert user.index("OUTPUT FROM THE") < user.index("EXPECTED OUTPUT")


def test_strict_schema_requires_every_field_and_drops_defaults():
    schema = strict_json_schema(RequirementsBatch)
    assert set(schema["required"]) == set(schema["properties"])
    requirement = schema["$defs"]["RequirementDraft"]
    assert set(requirement["required"]) == set(requirement["properties"])
    assert "'default'" not in str(schema)
    # Computed fields are never asked of the model.
    assert "approval_status" not in requirement["properties"]
    assert "flags" not in requirement["properties"]
    # Categories are constrained to the allowed list.
    assert requirement["properties"]["categories"]["items"]["enum"] == config.REQUIREMENT_CATEGORIES
