"""
agents/prompt_builder.py - Turns an agent's YAML prompt file into the actual
messages sent to the model. Every agent is prompted by the same code, which
is what makes adding new agents easy.
"""

import re

import yaml

import config
from agents.registry import AgentDefinition
from security.injection import DATA_INSTRUCTION, wrap_data

# Every prompt YAML file must contain these keys.
REQUIRED_PROMPT_KEYS = ["role", "goal", "backstory", "task_description", "expected_output"]

# Matches placeholders like {scenario} but NOT JSON like {"id": ...}.
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def load_prompt(key: str) -> dict:
    """Read prompts/<key>.yaml and check it has all the required sections."""
    prompt_file = config.PROMPTS_DIR / f"{key}.yaml"
    with open(prompt_file, encoding="utf-8") as f:
        prompt = yaml.safe_load(f)

    missing = [k for k in REQUIRED_PROMPT_KEYS if not prompt.get(k)]
    if missing:
        raise ValueError(f"{prompt_file.name} is missing: {', '.join(missing)}")
    return prompt


def fill_placeholders(template: str, variables: dict[str, str]) -> str:
    """Replace each {name} in the template with variables[name]."""
    def replace(match):
        name = match.group(1)
        if name not in variables:
            raise ValueError(f"Prompt uses {{{name}}} but no value was provided for it.")
        return str(variables[name])
    return PLACEHOLDER.sub(replace, template)


def build_messages(definition: AgentDefinition, variables: dict[str, str],
                   previous_outputs: dict[str, str], prompt_key: str | None = None) -> tuple[str, str]:
    """Build the (system prompt, user prompt) pair for one agent.

    variables:        values for the {placeholders}, e.g. {"scenario": "..."}
    previous_outputs: {agent display name: its raw output} for every agent
                      whose output this agent receives (the chain).
    prompt_key:       use prompts/<prompt_key>.yaml instead of the agent's own
                      file (for agents whose calls use different prompts).
    """
    prompt = load_prompt(prompt_key or definition.key)

    # The system prompt sets the agent's persona.
    system_prompt = (
        f"You are a {fill_placeholders(prompt['role'].strip(), variables)}.\n"
        f"{fill_placeholders(prompt['backstory'].strip(), variables)}\n"
        f"Your goal: {fill_placeholders(prompt['goal'].strip(), variables)}\n"
        f"{DATA_INSTRUCTION}"
    )

    # The user prompt holds the task, the previous agents' outputs and the
    # required output format.
    parts = [fill_placeholders(prompt["task_description"].strip(), variables)]
    for agent_name, output in previous_outputs.items():
        parts.append(f"OUTPUT FROM THE {agent_name.upper()} (your input):\n"
                     + wrap_data(output, f"output of the {agent_name}"))
    parts.append("EXPECTED OUTPUT:\n" + fill_placeholders(prompt["expected_output"].strip(), variables))
    user_prompt = "\n\n".join(parts)

    return system_prompt, user_prompt
