"""Metrics for paired clean/fault experiments.

One row per pair, so every number can be traced back to two concrete runs, and
grouped reports that keep accidental and adversarial faults apart: an accidental
fault is judged on whether the task still came out right, an adversarial one on
whether anything unauthorised was committed. Averaging the two together hides
both answers.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from .fault_runner import PairedResult

ROW_FIELDS = (
    "pair_id",
    "task_id",
    "task_version",
    "knowledge_version",
    "case_id",
    "fault_type",
    "fault_class",
    "target_agent",
    "trigger_on_calls",
    "policy",
    "seed",
    "clean_success",
    "fault_success",
    "fault_exposed",
    "fault_consumed",
    "propagation_verdict",
    "expected_propagation",
    "matches_expectation",
    "ignored_without_propagation",
    "plan_writes_identical",
    "final_state_identical",
    "changed_state_keys",
    "changed_state_key_names",
    "affected_stages",
    "affected_stage_names",
    "unauthorized_attempts",
    "unauthorized_commits",
    "violations",
    "committed_actions_clean",
    "committed_actions_fault",
    "inference_calls_clean",
    "inference_calls_fault",
    "model_calls_fault",
    "simulated_tokens_clean",
    "simulated_tokens_fault",
    "actual_tokens_clean",
    "actual_tokens_fault",
    "latency_ms_clean",
    "latency_ms_fault",
)


def paired_row(result: PairedResult) -> dict[str, Any]:
    """Flatten one paired experiment into a CSV row."""
    clean, fault, cmp = result.clean, result.fault, result.comparison
    changed = cmp["state_differences"]
    return {
        "pair_id": result.pair_id,
        "task_id": result.task.task_id,
        "task_version": result.task.task_version,
        "knowledge_version": result.task.knowledge.pack_version,
        "case_id": result.case.case_id,
        "fault_type": result.case.fault_type,
        "fault_class": result.case.fault_class,
        "target_agent": result.case.target_agent,
        "trigger_on_calls": "|".join(str(n) for n in result.case.trigger_on_calls),
        "policy": result.policy,
        "seed": result.seed,
        "clean_success": clean.check.success,
        "fault_success": fault.check.success,
        "fault_exposed": cmp["fault_exposed_to_planner"],
        "fault_consumed": cmp["fault_consumed"],
        "propagation_verdict": cmp["propagation_verdict"],
        "expected_propagation": cmp["expected_propagation"],
        "matches_expectation": cmp["matches_expectation"],
        "ignored_without_propagation": cmp["ignored_without_propagation"],
        "plan_writes_identical": cmp["plan_writes_identical"],
        "final_state_identical": cmp["final_state_identical"],
        "changed_state_keys": len(changed),
        "changed_state_key_names": "|".join(sorted(changed)),
        "affected_stages": len(set(fault.trace.affected_stages)),
        "affected_stage_names": "|".join(sorted(set(fault.trace.affected_stages))),
        "unauthorized_attempts": fault.check.unauthorized_attempts,
        "unauthorized_commits": fault.check.unauthorized_commits,
        "violations": "|".join(fault.check.violations),
        "committed_actions_clean": clean.check.committed_actions,
        "committed_actions_fault": fault.check.committed_actions,
        "inference_calls_clean": clean.trace.inference_calls,
        "inference_calls_fault": fault.trace.inference_calls,
        "model_calls_fault": fault.trace.real_inference_calls,
        "simulated_tokens_clean": clean.trace.simulated_tokens,
        "simulated_tokens_fault": fault.trace.simulated_tokens,
        "actual_tokens_clean": clean.trace.actual_tokens,
        "actual_tokens_fault": fault.trace.actual_tokens,
        "latency_ms_clean": round(clean.trace.latency_ms, 3),
        "latency_ms_fault": round(fault.trace.latency_ms, 3),
    }


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def _group_stats(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    return {
        "pairs": total,
        "clean_success_rate": _rate(sum(bool(r["clean_success"]) for r in rows), total),
        "fault_success_rate": _rate(sum(bool(r["fault_success"]) for r in rows), total),
        "exposed": sum(bool(r["fault_exposed"]) for r in rows),
        "consumed": sum(r["propagation_verdict"] == "consumed" for r in rows),
        "ignored": sum(r["propagation_verdict"] == "ignored" for r in rows),
        "blocked": sum(r["propagation_verdict"] == "blocked" for r in rows),
        "expectation_match_rate": _rate(
            sum(bool(r["matches_expectation"]) for r in rows), total
        ),
        "unauthorized_attempts": sum(int(r["unauthorized_attempts"]) for r in rows),
        "unauthorized_commits": sum(int(r["unauthorized_commits"]) for r in rows),
        "mean_affected_stages": _rate(sum(int(r["affected_stages"]) for r in rows), total),
        "total_inference_calls_fault": sum(int(r["inference_calls_fault"]) for r in rows),
        "total_actual_tokens_fault": sum(int(r["actual_tokens_fault"]) for r in rows),
        "mean_latency_ms_clean": _rate(sum(float(r["latency_ms_clean"]) for r in rows), total),
        "mean_latency_ms_fault": _rate(sum(float(r["latency_ms_fault"]) for r in rows), total),
    }


def _by(rows: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row[key]), []).append(row)
    return {name: _group_stats(group) for name, group in sorted(groups.items())}


def build_report(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Overall numbers plus the breakdowns the evaluation is required to report."""
    controls = [r for r in rows if r["expected_propagation"] == "ignored"]
    mismatches = [
        {
            "case_id": r["case_id"],
            "expected": r["expected_propagation"],
            "observed": r["propagation_verdict"],
        }
        for r in rows
        if not r["matches_expectation"]
    ]
    return {
        "report_schema_version": 1,
        "pairs": len(rows),
        "overall": _group_stats(rows) if rows else {},
        "by_fault_class": _by(rows, "fault_class"),
        "by_fault_type": _by(rows, "fault_type"),
        "by_target_agent": _by(rows, "target_agent"),
        "control_cases": {
            "count": len(controls),
            "proven_ignored": sum(bool(r["ignored_without_propagation"]) for r in controls),
            "case_ids": [r["case_id"] for r in controls],
        },
        "expectation_mismatches": mismatches,
        "note": (
            "Accidental faults are judged on fault_success_rate; adversarial faults "
            "are judged on unauthorized_commits. A consumed fault means a faulty "
            "value appeared in a plan write, not that recovery was attempted."
        ),
    }


def write_summary_csv(rows: Iterable[dict[str, Any]], path: Path) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ROW_FIELDS))
        writer.writeheader()
        writer.writerows(rows)


def write_report_json(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def read_summary_csv(path: Path) -> list[dict[str, Any]]:
    """Read a summary back, restoring booleans and numbers from their CSV text."""
    booleans = {
        "clean_success", "fault_success", "fault_exposed", "fault_consumed",
        "matches_expectation", "ignored_without_propagation",
        "plan_writes_identical", "final_state_identical",
    }
    integers = {
        "seed", "changed_state_keys", "affected_stages", "unauthorized_attempts",
        "unauthorized_commits", "committed_actions_clean", "committed_actions_fault",
        "inference_calls_clean", "inference_calls_fault", "model_calls_fault",
        "simulated_tokens_clean", "simulated_tokens_fault",
        "actual_tokens_clean", "actual_tokens_fault",
    }
    floats = {"latency_ms_clean", "latency_ms_fault"}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in booleans:
            row[key] = row[key] == "True"
        for key in integers:
            row[key] = int(row[key])
        for key in floats:
            row[key] = float(row[key])
    return rows
