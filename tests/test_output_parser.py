from agents.schemas import RequirementsBatch, SDLCOutput
from output_parser import extract_json_text, parse_agent_output


def test_extract_json_strips_fences_and_chatter():
    raw = 'Sure! Here it is:\n```json\n{"a": 1}\n```\nHope that helps.'
    assert extract_json_text(raw) == '{"a": 1}'


def test_extract_json_without_braces_returns_input():
    assert extract_json_text("no json here") == "no json here"


def test_parses_clean_json():
    parsed, error = parse_agent_output('{"recommended_model": "Agile"}', SDLCOutput)
    assert error is None
    assert parsed.recommended_model == "Agile"
    assert parsed.runner_up_explanations == []  # lenient defaults


def test_repairs_trailing_comma_and_missing_comma():
    raw = '{"recommended_model": "V-Model", "key_practices": ["a" "b",],}'
    parsed, error = parse_agent_output(raw, SDLCOutput)
    assert error is None
    assert parsed.recommended_model == "V-Model"


def test_nested_requirements_are_validated_and_normalised():
    raw = ('{"requirements": [{"id": "FR-01", "statement": "The system shall x.", '
           '"categories": ["Security", "compliance", "nonsense", "security"], '
           '"priority": "high", "sources": ["[c1]", " C2 "], "confidence": 85}]}')
    parsed, error = parse_agent_output(raw, RequirementsBatch)
    assert error is None
    requirement = parsed.requirements[0]
    assert requirement.categories == ["security", "regulatory"]
    assert requirement.priority == "High"
    assert requirement.risk_level == "Medium"
    assert requirement.sources == ["C1", "C2"]
    assert requirement.confidence == 0.85


def test_missing_required_field_reports_error_not_exception():
    parsed, error = parse_agent_output('{"confidence": "High"}', SDLCOutput)
    assert parsed is None
    assert "expected structure" in error


def test_non_object_answer_reports_error():
    parsed, error = parse_agent_output("I cannot help with that.", SDLCOutput)
    assert parsed is None
    assert error
