"""
run_eval.py - Evaluate the full system against the single-prompt baseline.

    python run_eval.py                         # all gold documents, both systems
    python run_eval.py --docs loan_approval_policy --fast
    python run_eval.py --mock                  # wiring check in seconds (meaningless numbers)

Writes evaluation/results/eval_<timestamp>.json and .csv; the Evaluation page
in the app shows them. The gold files are DRAFTS until the project owner
reviews them (status: reviewed).

On a CPU-only laptop (~2 tokens/s) a full run takes roughly 15-30 minutes per
document; --fast turns off the Quality, Compliance and Workflow agents.
"""

import argparse

import config
from evaluation import gold as gold_files
from evaluation.runner import SCALAR_METRICS, run_evaluation


def main(argv=None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--docs", nargs="*", help="gold file names (default: all)")
    parser.add_argument("--functional", type=int, default=config.NUM_FUNCTIONAL_REQUIREMENTS)
    parser.add_argument("--non-functional", type=int, default=config.NUM_NON_FUNCTIONAL_REQUIREMENTS)
    parser.add_argument("--fast", action="store_true", help="turn off the Quality, Compliance and Workflow agents")
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--mock", action="store_true", help="offline wiring check (canned model answers)")
    parser.add_argument("--model", default=config.MODEL_NAME)
    args = parser.parse_args(argv)

    if args.mock:
        from evaluation import offline
        offline.install()
    golds = gold_files.load_all(args.docs)
    if not golds:
        parser.error("no gold files found")
    options = {"num_functional": args.functional, "num_non_functional": args.non_functional}
    if args.fast:
        options["disabled_agents"] = ["quality_agent", "compliance_agent", "workflow_agent"]

    results = run_evaluation(golds, options, with_baseline=not args.no_baseline, model_name=args.model,
                             mock=args.mock,
                             on_document=lambda g: print(f"Evaluating {g.name} ({'DRAFT gold' if g.is_draft else 'reviewed gold'})..."))
    systems = list(results["summary"])
    print(f"\n{'metric':<24}" + "".join(f"{s:>12}" for s in systems))
    for metric in SCALAR_METRICS:
        row = [results["summary"][s].get(metric) for s in systems]
        print(f"{metric:<24}" + "".join(f"{('n/a' if v is None else v):>12}" for v in row))
    print(f"\nhuman correction rate (audit log): {results['meta']['human_correction_rate']}")
    return results


if __name__ == "__main__":
    main()
