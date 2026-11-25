"""
The agents package.

  registry.py           - WHICH agents exist, in what order, their hooks and read permissions
  prompt_builder.py     - HOW a YAML prompt becomes model messages (same for all agents)
  schemas.py            - WHAT each agent's output looks like (draft + final schemas)
  requirements_agent.py - batching + deterministic checks for the Requirements Agent
  quality_agent.py      - rule pre-checks + review batches (Quality & Clarification Agent)
  compliance_agent.py   - KB-only mapping checks + suggested security requirements
  sdlc_agent.py         - rate 13 factors -> score (sdlc_scoring.py) -> explain
  sdlc_evidence.py      - candidate evidence IDs per SDLC factor (hints)
  sdlc_scoring.py       - deterministic multi-criteria scoring (config/sdlc_rules.yaml)
  workflow_agent.py     - template + bounded tailoring of the SDLC workflow

The prompts themselves live in the top-level  prompts/  folder.
"""
