"""
tools/replay_run.py - Rebuild a finished run from its audit log, WITHOUT the model.

The audit log records every model answer ("agent_call" events). This tool
re-runs the same pipeline, but every model call is answered with the recorded
answer, in order (and checked against the agent that asks). Everything else -
retrieval, citation and number checks, scoring, review, artefacts - is
deterministic Python, so the result is the same run, saved as JSON for the
app's "Load a saved run" option.

    python -m tools.replay_run --audit run_audit_log.jsonl --document documents/loan_approval_policy.md \
        --scenario "..." --functional 5 --non-functional 4 --review auto --out demo/final_run
"""

import argparse
import json
import tempfile
from pathlib import Path

import config
import llm_service
from llm_service import LLMResponse

SCHEMA_AGENT = {"RequirementsBatch": "Requirements Agent", "QualityBatch": "Quality & Clarification Agent",
                "ComplianceBatch": "Compliance & Security Agent", "SDLCFactorsBatch": "SDLC Agent",
                "SDLCExplanationDraft": "SDLC Agent", "WorkflowCustomisation": "Workflow Agent"}


class ReplayLLM:
    """Answers model calls with the answers recorded in an audit log."""

    def __init__(self, events: list[dict]):
        self.calls = [e for e in events if e["event"] == "agent_call" and "output" in e]
        self.position = 0

    def chat(self, system_prompt, user_prompt, model_name=None, json_schema=None, **kwargs):
        if self.position >= len(self.calls):
            raise RuntimeError("The audit log has no more recorded answers.")
        recorded = self.calls[self.position]
        expected = SCHEMA_AGENT.get((json_schema or {}).get("title"))
        if expected and recorded["agent"] != expected:
            raise RuntimeError(f"Replay out of step: call {self.position + 1} is for {recorded['agent']}, "
                               f"but {expected} is asking.")
        self.position += 1
        return LLMResponse(text=recorded["output"], prompt_tokens=recorded.get("prompt_tokens", 0),
                           output_tokens=recorded.get("output_tokens", 0), seconds=recorded.get("seconds", 0.0))


def replay(audit_file: Path, document: Path, scenario: str, options: dict, user: str = "replay"):
    from document_reader import extract_text
    from pipeline import run_pipeline
    events = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    original = next(e for e in events if e["event"] == "pipeline_started")
    finished = next((e for e in events if e["event"] == "pipeline_finished"), {})
    replayer = ReplayLLM(events)
    real_chat = llm_service.chat
    llm_service.chat = replayer.chat
    try:
        result = run_pipeline(scenario, extract_text(document.name, document.read_bytes()), document.name,
                              original.get("model", config.MODEL_NAME), user=user, options=options)
    finally:
        llm_service.chat = real_chat
    if replayer.position != len(replayer.calls):
        raise RuntimeError(f"Only {replayer.position} of {len(replayer.calls)} recorded answers were used.")
    # Keep the original run's identity and timing.
    result.run_id = original["run_id"]
    result.elapsed_seconds = finished.get("elapsed_seconds", result.elapsed_seconds)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--document", required=True, type=Path)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--functional", type=int, default=5)
    parser.add_argument("--non-functional", type=int, default=4)
    parser.add_argument("--review", default="auto", choices=["auto", "none"])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    # The replay itself writes its audit/db records to a temporary folder.
    temp = Path(tempfile.mkdtemp(prefix="finreq_replay_"))
    config.LOGS_DIR, config.AUDIT_LOG_FILE = temp / "logs", temp / "logs" / "audit_log.jsonl"
    config.DATA_DIR, config.APP_DB, config.CHECKPOINT_DB = temp / "data", temp / "data" / "a.sqlite", temp / "data" / "c.sqlite"

    from pipeline import save_result
    result = replay(args.audit, args.document, args.scenario,
                    {"num_functional": args.functional, "num_non_functional": args.non_functional,
                     "review_mode": args.review})
    save_result(result, args.out / "result.json")
    print(f"Saved {args.out / 'result.json'} (run {result.run_id}, "
          f"{len(result.get('requirements_agent').parsed.requirements)} requirements)")
    return result


if __name__ == "__main__":
    main()
