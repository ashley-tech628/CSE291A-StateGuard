"""Recompute reports from saved paired traces, without calling the model again.

A paired run saves everything the evaluation needs inside each
``pairs/<case>/paired.json``: both full traces, the plan writes, the model
calls. So when the judging rules change - a new verdict, a new validity rule -
the old runs do not have to be repeated. They are re-graded.

Grading always uses the CURRENT case library and checker, so a rebuilt report
reflects today's definitions applied to the data that was actually collected.

Re-grading in place also refreshes the derived fields inside each
``paired.json`` - the verdict, the checker result, the comparison - so the raw
files and the report can never disagree. The recorded traces are never touched:
what the run observed stays exactly as it was written. With ``--output`` the
source files are left alone entirely.

    python -m stateguard.rebuild --input results/paired-llm-seed7
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .analysis import analyse
from .checker import check_final_state, check_trace, plan_completed_from_results
from .fault_runner import (
    PairedResult,
    RunOutcome,
    compare,
    infrastructure_errors,
    planner_writes,
    propagation_verdict,
)
from .faults import FaultSchedule, get_case
from .metrics import paired_row, write_summary_csv
from .workloads import VersionedTask, find_task


def _outcome(payload: dict[str, Any], task: VersionedTask, schedule: FaultSchedule) -> RunOutcome:
    """Re-grade one saved run. Only the trace is reused; every verdict is recomputed."""
    trace = SimpleNamespace(**payload["trace"])
    recovery_attempts = tuple(
        SimpleNamespace(**record) for record in payload.get("recovery_attempts", ())
    )
    final = recovery_attempts[-1] if recovery_attempts else trace
    if recovery_attempts and payload.get("recovery_decision") is not None:
        check = check_final_state(
            task=task.task, state=final.final_state,
            actions=(*trace.actions, *final.actions),
            events=(*trace.events, *final.events),
            plan_completed=(
                final.execution_blocked is None
                and plan_completed_from_results(final.results)
            ),
            execution_blocked=final.execution_blocked,
        )
    else:
        check = check_trace(task.task, final)
    return RunOutcome(
        label=payload["label"],
        schedule=schedule,
        trace=trace,
        applied_cases=tuple(payload.get("applied_cases", ())),
        check=check,
        plan_writes=planner_writes(trace),
        verdict=propagation_verdict(trace),
        recovery_attempts=recovery_attempts,
        recovery_decision=payload.get("recovery_decision"),
        api_errors=infrastructure_errors(trace),
    )


def load_pair(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def rebuild_pair(payload: dict[str, Any]) -> PairedResult:
    task = find_task(payload["workload"]["task_id"])
    case = get_case(payload["case"]["case_id"])
    seed = payload["seed"]
    clean = _outcome(payload["clean"], task, FaultSchedule.clean(seed))
    fault = _outcome(payload["fault"], task, FaultSchedule.single(case, seed))
    return PairedResult(
        task=task,
        case=case,
        policy=payload["policy"],
        seed=seed,
        clean=clean,
        fault=fault,
        comparison=compare(clean, fault, case),
    )


def paired_files(run_dir: Path) -> list[Path]:
    return sorted(run_dir.glob("pairs/*/paired.json"))


def _refresh_run(stored: dict[str, Any], outcome: RunOutcome) -> None:
    stored["checker"] = outcome.check.as_dict()
    stored["plan_writes"] = [dict(write) for write in outcome.plan_writes]
    stored["propagation_verdict"] = outcome.verdict
    stored["valid"] = outcome.valid
    stored["api_errors"] = list(outcome.all_api_errors)


def refresh_payload(payload: dict[str, Any], result: PairedResult) -> dict[str, Any]:
    """Bring a saved pair's derived fields up to date, in place.

    Only conclusions are rewritten. ``trace`` - the record of what the run
    actually observed - is left exactly as it was written.
    """
    payload["comparison"] = result.comparison
    payload["case"] = result.case.as_dict()
    _refresh_run(payload["clean"], result.clean)
    _refresh_run(payload["fault"], result.fault)
    return payload


def rebuild_run(
    run_dir: Path, outdir: Path | None = None, with_figures: bool = True
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, str]]]:
    """Re-grade every pair in ``run_dir`` and rewrite its summary and report.

    Returns the rows, the report, and the list of verdicts that changed since
    the run was first graded.
    """
    files = paired_files(run_dir)
    if not files:
        raise FileNotFoundError(f"no pairs/*/paired.json under {run_dir}")

    rows: list[dict[str, Any]] = []
    changes: list[dict[str, str]] = []
    for path in files:
        payload = load_pair(path)
        previous = payload["fault"].get("propagation_verdict")
        result = rebuild_pair(payload)
        if previous and previous != result.comparison["propagation_verdict"]:
            changes.append({
                "case_id": result.case.case_id,
                "was": previous,
                "now": result.comparison["propagation_verdict"],
            })
        rows.append(paired_row(result))
        if outdir is None:
            path.write_text(
                json.dumps(refresh_payload(payload, result), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    target = outdir or run_dir
    target.mkdir(parents=True, exist_ok=True)
    write_summary_csv(rows, target / "summary.csv")
    report = analyse(rows, target, with_figures=with_figures)
    return rows, report, changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", required=True,
                        help="one or more run directories to re-grade")
    parser.add_argument("--output", type=Path,
                        help="write elsewhere instead of in place; one input only")
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()

    if args.output and len(args.input) > 1:
        parser.error("--output takes a single --input")

    for run_dir in args.input:
        rows, report, changes = rebuild_run(
            run_dir, outdir=args.output, with_figures=not args.no_figures
        )
        invalid = report["invalid_pairs"]
        print(f"{run_dir}: {report['pairs']}/{report['pairs_run']} valid pairs")
        if invalid["count"]:
            print("  excluded:", json.dumps(invalid["reasons"]))
        if changes:
            for change in changes:
                print(f"  verdict changed: {change['case_id']}: "
                      f"{change['was']} -> {change['now']}")
        else:
            print("  no verdict changed")
        if args.output:
            print("  source pair files left untouched")
        else:
            print(f"  refreshed {len(rows)} paired.json file(s); traces unchanged")
        print("  written to:", args.output or run_dir)


if __name__ == "__main__":
    main()
