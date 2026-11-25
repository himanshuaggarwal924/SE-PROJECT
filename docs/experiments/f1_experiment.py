"""F1 investigation: full vs compact requirements prompt on the loan document (real model)."""
import copy, json, sys, time
from pathlib import Path
sys.path.insert(0, r"C:\Users\himan\Desktop\SE Project")
import config
here = Path(__file__).parent / "f1_experiment"; here.mkdir(exist_ok=True)
config.LOGS_DIR = here / "logs"; config.AUDIT_LOG_FILE = config.LOGS_DIR / "a.jsonl"
config.DATA_DIR = here / "data"; config.APP_DB = config.DATA_DIR / "a.sqlite"; config.CHECKPOINT_DB = config.DATA_DIR / "c.sqlite"
from agents.registry import get_agent
from agents.schemas import RequirementsOutput
from evaluation import gold as g, metrics
from orchestration.nodes import make_agent_node, prepare_context_node
loan = g.load(config.EVAL_GOLD_DIR / "loan_approval_policy.yaml")
state = {"run_id": "f1-exp", "model_name": config.MODEL_NAME, "scenario": loan.scenario,
         "source_text": loan.document_text(), "source_name": loan.document,
         "options": {"num_functional": 5, "num_non_functional": 4}, "agent_outputs": {}}
state.update(prepare_context_node(state))
node = make_agent_node(get_agent("requirements_agent"))
results = []
for mode in ["full", "compact", "compact"]:
    config.REQUIREMENTS_PROMPT_MODE = mode
    t = time.time()
    update = node(copy.deepcopy(state))
    seconds = round(time.time() - t)
    out = RequirementsOutput.model_validate(update["agent_outputs"]["requirements_agent"]["parsed"])
    reqs = [{"statement": r.statement, "categories": r.categories, "sources": r.sources,
             "flags": [f.type for f in r.flags], "acceptance_criteria": [c.model_dump() for c in r.acceptance_criteria]}
            for r in out.requirements]
    so = metrics.SystemOutput(system=mode, requirements=reqs)
    m = {**metrics.extraction(so, loan), **metrics.grounding(so, loan)}
    row = {"mode": mode, "seconds": seconds, **{k: m[k] for k in ("precision", "recall", "f1", "category_accuracy",
           "completeness", "hallucination_rate", "citation_correctness", "traceability_coverage")},
           "flags": out.validation_summary.get("flag_counts"), "statements": [r.statement for r in out.requirements]}
    results.append(row)
    print(json.dumps({k: v for k, v in row.items() if k != "statements"}), flush=True)
    for s in row["statements"]: print("   -", s, flush=True)
(here / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
