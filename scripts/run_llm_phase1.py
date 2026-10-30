"""Standalone LLM integration runner; leaves the team's experiment.py unchanged."""
import argparse
import csv
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from stateguard.model_adapter import ModelAdapter
from stateguard.workflow import DeploymentTask, WorkflowRunner

SMOKE_CASES = [
    ("none", "no_recovery"),
    ("incorrect", "no_recovery"),
    ("incorrect", "always_verify"),
    ("incorrect", "full_restart"),
    ("stale", "no_recovery"),
    ("stale", "always_verify"),
    ("adversarial", "no_recovery"),
    ("timeout", "no_recovery"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["clean", "smoke", "matrix"], default="clean")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seeds", type=int, nargs="+", default=[7])
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--model")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = args.output or Path("results") / f"jingwen-llm-{stamp}"
    if root.exists() and any(root.iterdir()):
        parser.error("Output directory is not empty; choose a NEW path to preserve old runs.")
    root.mkdir(parents=True, exist_ok=True)
    adapter = ModelAdapter(model=args.model, max_attempts=args.max_attempts,
                           temperature=args.temperature)
    cases = [("none", "no_recovery")] if args.suite == "clean" else SMOKE_CASES
    tasks = (DeploymentTask(),)
    if args.suite == "matrix":
        from stateguard.experiment import build_pilot_tasks, FAULTS, POLICIES
        tasks = build_pilot_tasks()
        cases = [(f, p) for f in FAULTS for p in POLICIES]
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True,
                                           stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True))
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = None, None
    (root / "manifest.json").write_text(json.dumps({
        "suite": args.suite, "model": adapter.model, "prompt_version": "stateguard-llm-v2",
        "sdk_version": adapter.sdk_version, "seeds": args.seeds,
        "seed_note": "Seeds label schedules/repetitions; provider seed is not sent. Model outputs are stochastic.",
        "temperature": args.temperature, "max_attempts": args.max_attempts,
        "git_revision": revision, "git_dirty": dirty, "python_version": sys.version,
        "scope": "LLM integration smoke/matrix; not the complete Phase 1 evaluation.",
        "limitations": ["Verification uses deterministic oracle checks, not an LLM verifier.",
                        "Planner is schema-checked but is not always-verified by this baseline.",
                        "Full restart replays the original fixed worker update, not arbitrary external events.",
                        "Injected timeout is an intermediate-result fault, not a lost-ACK tool fault."],
    }, indent=2), encoding="utf-8")
    rows = []
    for task in tasks:
        for seed in args.seeds:
            for fault, policy in cases:
                name = f"{task.task_id}__{fault}__{policy}__{seed}"
                folder = root / name
                folder.mkdir()
                attempts = []
                started = perf_counter()
                for number in range(1, 3 if policy == "full_restart" and fault != "none" else 2):
                    runner = WorkflowRunner(
                        task=task, fault=fault if number == 1 else "none", policy=policy,
                        db_path=folder / f"attempt-{number}.sqlite3",
                        attempt_id=f"{name}-attempt-{number}", seed=seed,
                        replay_external_event=number > 1, model_adapter=adapter,
                    )
                    trace = runner.run()
                    attempts.append(trace)
                    # Save immediately, so completed attempts survive interruption.
                    (folder / f"attempt-{number}.json").write_text(
                        json.dumps(asdict(trace), indent=2, ensure_ascii=False), encoding="utf-8")
                final = attempts[-1]
                row = {
                    "scenario": name, "fault": fault, "policy": policy, "seed": seed,
                    "success": final.checker["success"],
                    "fault_exposed": any(a.fault_evidence for a in attempts),
                    "fault_matching_write": any(a.fault_consumed for a in attempts),
                    "model_calls": sum(a.real_inference_calls for a in attempts),
                    "reported_tokens": sum(a.actual_tokens for a in attempts),
                    "usage_missing_calls": sum(a.usage_missing_calls for a in attempts),
                    "simulated_cost_units": sum(a.simulated_tokens for a in attempts),
                    "unauthorized_attempts": sum(a.checker["unauthorized_attempts"] for a in attempts),
                    "unauthorized_commits": sum(a.checker["unauthorized_commits"] for a in attempts),
                    "attempts": len(attempts),
                    "wall_latency_ms": round((perf_counter() - started) * 1000, 3),
                }
                rows.append(row)
                with (root / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(row))
                    writer.writeheader()
                    writer.writerows(rows)
                print(f'{name}: success={row["success"]}, calls={row["model_calls"]}, '
                      f'tokens={row["reported_tokens"]}', flush=True)
    print("Saved:", root)


if __name__ == "__main__":
    main()
