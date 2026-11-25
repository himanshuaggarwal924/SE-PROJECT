"""
artefacts/process_flow.py - The (loan) process workflow as a flowchart whose
nodes ARE the requirements, so every box is traceable to a requirement ID.

Built deterministically from the run's requirements:
  * each functional requirement is a step, in ID order; a requirement that
    routes / approves / declines / refers / applies a threshold is a DECISION
    (diamond) with a "meets rule" path and an "exception" path to human handling
  * explicit dependencies between requirements are added as dashed edges
  * non-functional requirements are CONTROLS, linked to the steps whose
    categories they share (or to the whole process)

Rendered as Mermaid (artefact files) and as Graphviz DOT (shown in the app -
Streamlit draws DOT locally, so no external Mermaid script is needed).
"""

import re
from dataclasses import dataclass, field

# Gate VERBS and thresholds make a step a decision; the noun "decision" alone
# (e.g. "store decision records") does not.
DECISION = re.compile(r"\b(route[sd]?|routing|approve[sd]?|decline[sd]?|refer(?:s|red)?|reject[sd]?|escalate[sd]?|"
                      r"validate[sd]?|verify|verifies|screen(?:s|ed)?|if|above|below|exceed(?:s|ed)?|threshold|"
                      r"cut-off|eligib\w*)\b", re.IGNORECASE)
START, END, EXCEPTION = "START", "END", "EXCEPTION"


@dataclass
class Node:
    id: str
    label: str
    kind: str                      # start | end | step | decision | exception | control
    requirement: str = ""


@dataclass
class Flow:
    nodes: list[Node] = field(default_factory=list)
    edges: list[tuple] = field(default_factory=list)    # (from, to, label, style: solid|dashed|dotted)

    def node(self, node_id: str) -> Node:
        return next(n for n in self.nodes if n.id == node_id)


def _short(text: str, limit: int = 70) -> str:
    text = re.sub(r"^\s*the system shall\s+", "", " ".join(text.split()), flags=re.IGNORECASE).rstrip(".")
    text = text[0].upper() + text[1:] if text else text
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _safe_id(requirement_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", requirement_id)


def build_flow(requirements, title: str = "Process") -> Flow:
    """requirements: Requirement objects (or dicts) of one run."""
    reqs = [r if isinstance(r, dict) else r.model_dump() for r in requirements]
    functional = [r for r in reqs if r.get("kind", "functional") == "functional"]
    controls = [r for r in reqs if r.get("kind") != "functional"]
    flow = Flow()
    flow.nodes.append(Node(START, f"{title} starts", "start"))
    previous, previous_is_decision = START, False
    has_exception = False
    for r in functional:
        node_id = _safe_id(r["id"])
        kind = "decision" if DECISION.search(r["statement"]) else "step"
        flow.nodes.append(Node(node_id, f"{r['id']}: {_short(r['statement'])}", kind, r["id"]))
        flow.edges.append((previous, node_id, "meets rule" if previous_is_decision else "", "solid"))
        if kind == "decision":
            flow.edges.append((node_id, EXCEPTION, "exception", "solid"))
            has_exception = True
        previous, previous_is_decision = node_id, kind == "decision"
    flow.nodes.append(Node(END, f"{title} complete", "end"))
    flow.edges.append((previous, END, "meets rule" if previous_is_decision else "", "solid"))
    if has_exception:
        flow.nodes.append(Node(EXCEPTION, "Exception: human review / manual handling", "exception"))
        flow.edges.append((EXCEPTION, END, "decided", "solid"))

    ids = {r["id"] for r in functional}
    for r in functional:
        for dep in r.get("dependencies", []):
            if dep in ids:
                flow.edges.append((_safe_id(dep), _safe_id(r["id"]), "depends on", "dashed"))
    for c in controls:
        node_id = _safe_id(c["id"])
        flow.nodes.append(Node(node_id, f"{c['id']}: {_short(c['statement'], 60)}", "control", c["id"]))
        shared = [r for r in functional
                  if set(c.get("categories", [])) & (set(r.get("categories", [])) - {"functional"})]
        for r in shared or []:
            flow.edges.append((node_id, _safe_id(r["id"]), "", "dotted"))
        if not shared:
            flow.edges.append((node_id, START, "applies to all", "dotted"))
    return flow


# ------------------------------------------------------------------ Mermaid --
def _mermaid_label(text: str) -> str:
    return text.replace('"', "'").replace("\n", " ")


def to_mermaid(flow: Flow) -> str:
    shapes = {"start": '(["{}"])', "end": '(["{}"])', "step": '["{}"]', "decision": '{{"{}"}}',
              "exception": '[/"{}"/]', "control": '[["{}"]]'}
    lines = ["flowchart TD"]
    controls = [n for n in flow.nodes if n.kind == "control"]
    for n in flow.nodes:
        if n.kind != "control":
            lines.append(f"    {n.id}{shapes[n.kind].format(_mermaid_label(n.label))}")
    if controls:
        lines.append('    subgraph Controls["Cross-cutting controls (non-functional requirements)"]')
        for n in controls:
            lines.append(f"        {n.id}{shapes['control'].format(_mermaid_label(n.label))}")
        lines.append("    end")
    arrows = {"solid": "-->", "dashed": "-.->", "dotted": "-.-"}
    for source, target, label, style in flow.edges:
        arrow = arrows[style]
        lines.append(f"    {source} {arrow}|{_mermaid_label(label)}| {target}" if label else f"    {source} {arrow} {target}")
    lines.append("    classDef decision fill:#fff4e5,stroke:#d97706")
    lines.append("    classDef control fill:#eef2ff,stroke:#4f46e5")
    decisions = [n.id for n in flow.nodes if n.kind == "decision"]
    if decisions:
        lines.append(f"    class {','.join(decisions)} decision")
    if controls:
        lines.append(f"    class {','.join(n.id for n in controls)} control")
    return "\n".join(lines) + "\n"


def to_markdown(flow: Flow, title: str, status_note: str) -> str:
    rows = "\n".join(f"| {n.requirement} | {n.kind} | {n.label.split(': ', 1)[-1]} |"
                     for n in flow.nodes if n.requirement)
    return (f"# {title} – process workflow\n\n> {status_note}\n\n"
            "Every box is a requirement (its ID is in the label); diamonds are decisions with an "
            "exception path to human handling; boxes in *Cross-cutting controls* are non-functional "
            "requirements linked to the steps they protect.\n\n"
            f"```mermaid\n{to_mermaid(flow)}```\n\n| Requirement | Node | Text |\n|---|---|---|\n{rows}\n")


# -------------------------------------------------------------- Graphviz --
def to_dot(flow: Flow) -> str:
    shapes = {"start": "oval", "end": "oval", "step": "box", "decision": "diamond", "exception": "parallelogram",
              "control": "component"}
    fills = {"decision": "#fff4e5", "control": "#eef2ff", "exception": "#fde8e8", "start": "#e8f5e9",
             "end": "#e8f5e9", "step": "#ffffff"}
    lines = ['digraph process {', '  rankdir=TB; node [fontname="Helvetica", fontsize=10, style=filled];']
    for n in flow.nodes:
        label = n.label.replace('"', "'")
        lines.append(f'  {n.id} [label="{label}", shape={shapes[n.kind]}, fillcolor="{fills[n.kind]}"];')
    styles = {"solid": "solid", "dashed": "dashed", "dotted": "dotted"}
    for source, target, label, style in flow.edges:
        extra = ", arrowhead=none" if style == "dotted" else ""
        lines.append(f'  {source} -> {target} [label="{label}", style={styles[style]}{extra}];')
    lines.append("}")
    return "\n".join(lines)
