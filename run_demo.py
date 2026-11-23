"""
run_demo.py - Run the pipeline from the terminal (no web UI, no login).

    python run_demo.py                       -> loan-approval example using the
                                                sample documents in /documents
    python run_demo.py my_spec.pdf           -> requirements from your own file
    python run_demo.py my_spec.pdf "KYC onboarding"   -> ...focused on a topic
"""

import json
import sys
from pathlib import Path

from context_loader import list_sample_documents, load_sample_documents
from document_reader import extract_text
from pipeline import run_pipeline

SAMPLE_SCENARIO = (
    "Loan approval module for a retail bank: customers apply online for a "
    "personal loan, the system checks eligibility and credit score, and either "
    "auto-decides or routes the application to a human underwriter."
)


def main() -> None:
    if len(sys.argv) > 1:
        # Use the file given on the command line, like an upload in the UI.
        path = Path(sys.argv[1])
        source_text = extract_text(path.name, path.read_bytes())
        source_name = path.name
        scenario = sys.argv[2] if len(sys.argv) > 2 else \
            f"The finance functionality described in the document '{path.name}'"
    else:
        # Default demo: the sample documents act as the uploaded document.
        samples = list_sample_documents()
        source_text = load_sample_documents(samples)
        source_name = " + ".join(samples)
        scenario = SAMPLE_SCENARIO

    print(f"Scenario: {scenario}\nSource: {source_name} ({len(source_text):,} characters)\n")

    def show_progress(node_name, elapsed_seconds, update):
        print(f"--- step finished: {node_name} after {elapsed_seconds}s")
        if "context_info" in update:
            print(f"    context: {update['context_info']}")

    result = run_pipeline(scenario, source_text, source_name, on_step_finished=show_progress)

    for agent_result in result.agent_results:
        print("\n" + "=" * 70)
        print(agent_result.display_name)
        print("=" * 70)
        if agent_result.parsed is not None:
            print(json.dumps(agent_result.parsed.model_dump(), indent=2))
        else:
            print("Could not parse structured output:", agent_result.parse_error)
            print(agent_result.raw_output)

    print(f"\nRun id: {result.run_id}, took {result.elapsed_seconds}s (see logs/audit_log.jsonl)")


if __name__ == "__main__":
    main()
