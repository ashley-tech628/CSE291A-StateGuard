"""Matched comparisons must share a workload and a valid case denominator."""

import csv
import json

import pytest

from scripts.summarize_matched_phase1 import DIRECTORY_LABELS, POLICIES, summarize


def _write_run(root, seed, policy, *, invalid=False, model="test-model"):
    path = root / f"c-phase1-llm-{DIRECTORY_LABELS[policy]}-seed{seed}"
    path.mkdir()
    manifest = {
        "workload": {"task_id": "task-1"}, "cases": ["a", "b"],
        "backend": "real-model", "model": model, "max_attempts": 3,
        "request_interval_seconds": 5, "temperature": None,
        "source_commit": "abc123", "external_updates": None,
        "seed": seed, "policy": policy,
    }
    (path / "manifest.json").write_text(json.dumps(manifest))
    (path / "run_status.json").write_text(json.dumps({
        "complete": True, "recorded_pairs": 2, "planned_pairs": 2,
    }))
    rows = []
    for case in ("a", "b"):
        rows.append({
            "case_id": case, "pair_valid": str(not (invalid and case == "b")),
            "invalid_reason": "api_error" if invalid and case == "b" else "",
            "fault_success": str(policy != "no_recovery"),
            "clean_success": "True", "propagation_verdict": "consumed",
            "unauthorized_commits": "0", "actual_tokens_fault": "10",
            "inference_calls_fault": "2", "latency_ms_fault": "100",
            "recomputed_stages": "1", "retained_results": "0",
        })
    with (path / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def test_common_valid_cases_and_invalid_reason(tmp_path):
    for seed in (7, 11):
        for policy in POLICIES:
            _write_run(tmp_path, seed, policy,
                       invalid=(seed == 7 and policy == "full_restart"))
    result = summarize(tmp_path, [7, 11])
    assert result["common_valid_cases_by_seed"] == {7: ["a"], 11: ["a", "b"]}
    assert result["invalid_by_run"]["full_restart/seed7"] == {"b": "api_error"}
    assert result["policies"]["no_recovery"]["matched_pairs"] == 3
    assert result["policies"]["no_recovery"]["fault_success"] == 0
    assert result["policies"]["full_restart"]["fault_success"] == 3


def test_mismatched_model_is_rejected(tmp_path):
    for policy in POLICIES:
        _write_run(tmp_path, 7, policy,
                   model="other-model" if policy == "always_verify" else "test-model")
    with pytest.raises(ValueError, match="model differs"):
        summarize(tmp_path, [7])
