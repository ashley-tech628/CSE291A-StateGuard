"""Run paired clean/fault experiments over the fault case library.

Each pair runs the same versioned workload twice - once clean, once with one
scheduled fault case - and saves two complete traces plus the comparison that
shows whether the faulty result actually reached the planner.

    python scripts/run_paired_experiment.py --output results/paired --seed 7
    python scripts/run_paired_experiment.py --cases ignored-resource-cpu-count
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stateguard.analysis import analyse
from stateguard.fault_runner import run_paired, write_paired_artifacts
from stateguard.faults import CASE_LIBRARY, get_case
from stateguard.metrics import paired_row, write_summary_csv
from stateguard.workloads import default_task, find_task

MARKER = ".stateguard-generated"


def prepare_output(path: Path) -> Path:
    path = path.resolve()
    if path.exists() and any(path.iterdir()) and not (path / MARKER).exists():
        raise SystemExit(f"refusing to write into an unowned directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    (path / MARKER).write_text("StateGuard paired experiment output\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/paired"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--policy", default="no_recovery",
                        choices=["no_recovery", "full_restart", "always_verify"])
    parser.add_argument("--task", help="task_id; defaults to the first pilot workload")
    parser.add_argument("--cases", nargs="*", help="case ids; defaults to the whole library")
    parser.add_argument("--no-figures", action="store_true")
    parser.add_argument("--llm", action="store_true",
                        help="drive the agents with a real model instead of the "
                             "deterministic backend (needs OPENAI_BASE_URL and OPENAI_API_KEY)")
    parser.add_argument("--model", help="model id; defaults to STATEGUARD_MODEL")
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("--temperature", type=float)
    args = parser.parse_args()

    task = find_task(args.task) if args.task else default_task()
    cases = [get_case(name) for name in args.cases] if args.cases else list(CASE_LIBRARY)
    root = prepare_output(args.output)

    adapter = None
    if args.llm:
        from stateguard.model_adapter import ModelAdapter

        adapter = ModelAdapter(
            model=args.model,
            max_attempts=args.max_attempts,
            temperature=args.temperature,
        )

    (root / "manifest.json").write_text(json.dumps({
        "workload": task.as_dict(),
        "policy": args.policy,
        "seed": args.seed,
        "cases": [case.case_id for case in cases],
        "backend": "real-model" if adapter else "deterministic",
        "model": getattr(adapter, "model", None),
        "max_attempts": args.max_attempts if adapter else None,
        "temperature": args.temperature if adapter else None,
        "python_version": sys.version,
        "design": "paired clean/fault; the clean run is the control for each case",
        "seed_note": (
            "The seed pins the fault schedule, not the model. Real-model runs are "
            "stochastic, so a verdict from one run is evidence, not a guarantee."
        ),
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    rows = []
    for case in cases:
        workdir = root / "pairs" / f"{case.case_id}__{args.policy}__seed-{args.seed}"
        result = run_paired(
            task=task, case=case, policy=args.policy, seed=args.seed,
            workdir=workdir, model_adapter=adapter,
        )
        write_paired_artifacts(result, workdir)
        row = paired_row(result)
        rows.append(row)
        print(
            f"{case.case_id:38s} verdict={row['propagation_verdict']:8s} "
            f"expected={row['expected_propagation']:8s} "
            f"fault_success={str(row['fault_success']):5s} "
            f"unauth={row['unauthorized_attempts']}/{row['unauthorized_commits']}",
            flush=True,
        )

    write_summary_csv(rows, root / "summary.csv")
    report = analyse(rows, root, with_figures=not args.no_figures)
    mismatches = report["expectation_mismatches"]
    print()
    print(json.dumps(report["overall"], indent=2))
    print("Control cases proven ignored:",
          f"{report['control_cases']['proven_ignored']}/{report['control_cases']['count']}")
    if mismatches:
        print("Expectation mismatches:", json.dumps(mismatches))
    print("Saved:", root)
    # expected_propagation is declared for the deterministic no-recovery
    # baseline, so a mismatch is only a failure under exactly those conditions.
    strict = args.policy == "no_recovery" and adapter is None
    raise SystemExit(1 if mismatches and strict else 0)


if __name__ == "__main__":
    main()
