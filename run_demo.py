"""
run_demo.py - Run the pipeline from the terminal (no web UI, no login).

    python run_demo.py                                    # loan-approval demo (sample documents)
    python run_demo.py my_spec.pdf                        # requirements for your own file
    python run_demo.py my_spec.pdf "KYC onboarding"       # ...focused on a topic
    python run_demo.py --auto-approve                     # non-interactive: approve every review step
    python run_demo.py --fast --functional 3 --non-functional 2
    python run_demo.py --artefacts out/                   # also write the SRS, RTM, registers...

Without --auto-approve the review steps are skipped and every item stays
"pending" (the human review happens in the web app). With --auto-approve the
review steps run and approve everything, clearly marked as auto-approved.
"""

import argparse
import json
import sys
from pathlib import Path

import config
from context_loader import list_sample_documents, load_sample_documents
from document_reader import extract_text
from pipeline import run_pipeline

SAMPLE_SCENARIO = (
    "Loan approval module for a retail bank: customers apply online for a "
    "personal loan, the system checks eligibility and credit score, and either "
    "auto-decides or routes the application to a human underwriter."
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("document", nargs="?", help="PDF, DOCX, TXT or MD file (default: the sample documents)")
    parser.add_argument("focus", nargs="?", help="which functionality of the document to cover")
    parser.add_argument("--auto-approve", action="store_true",
                        help="run the review steps and approve everything (non-interactive)")
    parser.add_argument("--fast", action="store_true", help="turn off the Quality, Compliance and Workflow agents")
    parser.add_argument("--functional", type=int, default=config.NUM_FUNCTIONAL_REQUIREMENTS)
    parser.add_argument("--non-functional", type=int, default=config.NUM_NON_FUNCTIONAL_REQUIREMENTS)
    parser.add_argument("--artefacts", metavar="FOLDER", help="write the generated artefacts to this folder")
    parser.add_argument("--model", default=config.MODEL_NAME)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.document:
        path = Path(args.document)
        source_text = extract_text(path.name, path.read_bytes())
        source_name = path.name
        scenario = args.focus or f"The finance functionality described in the document '{path.name}'"
    else:
        samples = list_sample_documents()
        source_text = load_sample_documents(samples)
        source_name = " + ".join(samples)
        scenario = SAMPLE_SCENARIO

    options = {"num_functional": args.functional, "num_non_functional": args.non_functional,
               "review_mode": "auto" if args.auto_approve else "none"}
    if args.fast:
        options["disabled_agents"] = ["quality_agent", "compliance_agent", "workflow_agent"]
    print(f"Scenario: {scenario}\nSource: {source_name} ({len(source_text):,} characters)\n"
          f"Review: {'auto-approve' if args.auto_approve else 'none (items stay pending)'}\n")

    def show_progress(node_name, elapsed_seconds, update):
        print(f"--- step finished: {node_name} after {elapsed_seconds}s")
        if "context_info" in update:
            print(f"    context: {update['context_info'].get('method')}, "
                  f"{update['context_info'].get('chunks_used', 0)} excerpts")

    result = run_pipeline(scenario, source_text, source_name, args.model, on_step_finished=show_progress,
                          user="cli", options=options)

    for agent_result in result.agent_results:
        print("\n" + "=" * 70)
        print(f"{agent_result.display_name} [{agent_result.status}]")
        print("=" * 70)
        if agent_result.parsed is not None:
            print(json.dumps(agent_result.parsed.model_dump(), indent=2, ensure_ascii=False)[:6000])
        else:
            print(agent_result.parse_error or "(no output)")

    if args.artefacts:
        from artefacts.bundle import generate
        folder = Path(args.artefacts)
        folder.mkdir(parents=True, exist_ok=True)
        for name, content in generate(result, "cli").items():
            (folder / name).write_bytes(content)
        print(f"\nArtefacts written to {folder.resolve()}")

    print(f"\nRun id: {result.run_id}, took {result.elapsed_seconds}s (see logs/audit_log.jsonl)")
    if result.pii_masked:
        print(f"Masked before any model call: {result.pii_masked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
