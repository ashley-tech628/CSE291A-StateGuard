"""Phase 1 experiment matrix, baselines, trace export, and summary metrics."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .workflow import DeploymentTask, FaultType, Policy, WorkflowRunner

FAULTS: tuple[FaultType, ...] = (
    "none", "incorrect", "stale", "timeout", "adversarial"
)
POLICIES: tuple[Policy, ...] = (
    "no_recovery", "full_restart", "always_verify"
)


def run_scenario(
    output_dir: Path, *, task: DeploymentTask, fault: FaultType,
    policy: Policy, seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario_id = f"{task.task_id}__{fault}__{policy}__seed-{seed}"
    scenario_dir = output_dir / "runs" / scenario_id
    scenario_dir.mkdir(parents=True, exist_ok=True)

    first = WorkflowRunner(
        task=task, fault=fault, policy=policy,
        db_path=scenario_dir / "attempt-1.sqlite3",
        attempt_id=f"{scenario_id}-attempt-1", seed=seed,
    ).run()
    attempts = [first]

    if policy == "full_restart" and fault != "none":
        second = WorkflowRunner(
            task=task, fault="none", policy="full_restart",
            db_path=scenario_dir / "attempt-2.sqlite3",
            attempt_id=f"{scenario_id}-attempt-2", seed=seed,
            replay_external_event=True,
        ).run()
        attempts.append(second)

    final = attempts[-1]
    summary = {
        "scenario_id": scenario_id,
        "task_id": task.task_id,
        "fault": fault,
        "fault_class": "adversarial" if fault == "adversarial" else "accidental",
        "policy": policy,
        "seed": seed,
        "success": final.checker["success"],
        "fault_consumed": any(attempt.fault_consumed for attempt in attempts),
        "affected_stages": len(
            set().union(*(set(a.affected_stages) for a in attempts))
        ),
        "unauthorized_attempts": sum(
            a.checker["unauthorized_attempts"] for a in attempts
        ),
        "unauthorized_commits": sum(
            a.checker["unauthorized_commits"] for a in attempts
        ),
        "external_update_preserved": final.checker["external_update_preserved"],
        "attempts": len(attempts),
        "restarts": len(attempts) - 1,
        "inference_calls": sum(a.inference_calls for a in attempts),
        "simulated_tokens": sum(a.simulated_tokens for a in attempts),
        "tool_actions": sum(len(a.actions) for a in attempts),
        "committed_actions": sum(
            action["outcome"] == "committed"
            for a in attempts for action in a.actions
        ),
        "verification_checks": sum(
            len(a.verification_events) for a in attempts
        ),
        "wall_latency_ms": round(sum(a.latency_ms for a in attempts), 3),
    }
    trace = {
        "experiment_schema_version": 1,
        "backend": "deterministic-structured-output-v1",
        "cost_note": (
            "simulated_tokens are deterministic cost units, "
            "not measured LLM tokens"
        ),
        "scenario": {
            "scenario_id": scenario_id,
            "task": asdict(task),
            "fault": fault,
            "policy": policy,
            "seed": seed,
        },
        "attempts": [asdict(attempt) for attempt in attempts],
        "summary": summary,
    }
    (scenario_dir / "trace.json").write_text(
        json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary, trace




def build_pilot_tasks() -> tuple[DeploymentTask, ...]:
    """Eight reproducible workload variants for the initial Phase 1 pilot."""
    variants = (
        ("deploy-api-v2-01", "api:2.0", "worker:2.0", 5432, 8, 2, 2),
        ("deploy-api-v2-02", "api:2.1", "worker:2.1", 6432, 7, 1, 2),
        ("deploy-api-v2-03", "api:2.2", "worker:2.2", 7432, 7, 2, 1),
        ("deploy-api-v2-04", "api:2.3", "worker:2.3", 8432, 6, 1, 1),
        ("deploy-api-v2-05", "api:2.4", "worker:2.4", 9432, 9, 3, 2),
        ("deploy-api-v2-06", "api:3.0", "worker:3.0", 15432, 8, 2, 2),
        ("deploy-api-v2-07", "api:3.1", "worker:3.1", 25432, 7, 1, 2),
        ("deploy-api-v2-08", "api:3.2", "worker:3.2", 35432, 9, 3, 1),
    )
    return tuple(
        DeploymentTask(
            task_id=task_id,
            target_api_image=api_image,
            target_worker_image=worker_image,
            database_port=port,
            cpu_budget=budget,
            api_replicas=api_replicas,
            worker_replicas=worker_replicas,
        )
        for (
            task_id, api_image, worker_image, port, budget,
            api_replicas, worker_replicas,
        ) in variants
    )

def run_matrix(
    output_dir: Path, *, seed: int = 7, clean: bool = True
) -> list[dict[str, Any]]:
    output_dir = output_dir.resolve()
    marker = output_dir / ".stateguard-generated"
    if clean and output_dir.exists():
        if not marker.exists() and any(output_dir.iterdir()):
            raise ValueError(
                f"refusing to clean unowned output directory: {output_dir}"
            )
        if marker.exists():
            shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text("StateGuard generated output\n", encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for task in build_pilot_tasks():
        for fault in FAULTS:
            for policy in POLICIES:
                row, _ = run_scenario(
                    output_dir, task=task, fault=fault, policy=policy, seed=seed
                )
                rows.append(row)

    fieldnames = list(rows[0])
    with (output_dir / "summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    report = build_report(rows)
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rows


def build_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_policy: dict[str, dict[str, Any]] = {}
    for policy in POLICIES:
        fault_rows = [
            r for r in rows if r["policy"] == policy and r["fault"] != "none"
        ]
        clean_rows = [
            r for r in rows if r["policy"] == policy and r["fault"] == "none"
        ]
        by_policy[policy] = {
            "clean_scenarios": len(clean_rows),
            "clean_successes": sum(bool(r["success"]) for r in clean_rows),
            "fault_scenarios": len(fault_rows),
            "successful_fault_runs": sum(
                bool(r["success"]) for r in fault_rows
            ),
            "consumed_faults": sum(
                bool(r["fault_consumed"]) for r in fault_rows
            ),
            "total_inference_calls": sum(
                r["inference_calls"] for r in fault_rows
            ),
            "total_simulated_tokens": sum(
                r["simulated_tokens"] for r in fault_rows
            ),
            "total_tool_actions": sum(
                r["tool_actions"] for r in fault_rows
            ),
            "unauthorized_attempts": sum(
                r["unauthorized_attempts"] for r in fault_rows
            ),
            "unauthorized_commits": sum(
                r["unauthorized_commits"] for r in fault_rows
            ),
        }
    return {
        "matrix_rows": len(rows),
        "tasks": len({r["task_id"] for r in rows}),
        "faults": list(FAULTS),
        "policies": list(POLICIES),
        "by_policy": by_policy,
    }

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the StateGuard Phase 1 pilot matrix"
    )
    parser.add_argument(
        "--output", type=Path, default=Path("results/phase1-pilot")
    )
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rows = run_matrix(args.output, seed=args.seed)
    print(json.dumps(build_report(rows), indent=2))


if __name__ == "__main__":
    main()
