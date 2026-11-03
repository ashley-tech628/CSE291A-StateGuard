"""Summarize real-model Phase 1 baselines on the same valid case set.

Example:
    python scripts/summarize_matched_phase1.py --root results --seeds 7 11 19

The script refuses to compare runs with different workloads, fault schedules,
models, retry settings, request intervals, or source revisions. API failures
remain visible in ``invalid_by_run`` and are excluded from the common set.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean


POLICIES = ("no_recovery", "full_restart", "always_verify")
DIRECTORY_LABELS = {
    "no_recovery": "no_recovery",
    "full_restart": "full-restart",
    "always_verify": "always-verify",
}
MATCH_FIELDS = (
    "workload", "cases", "backend", "model", "max_attempts",
    "request_interval_seconds", "temperature", "source_commit",
    "external_updates",
)


def _read_run(root: Path, policy: str, seed: int) -> tuple[dict, dict[str, dict]]:
    path = root / f"c-phase1-llm-{DIRECTORY_LABELS[policy]}-seed{seed}"
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    status = json.loads((path / "run_status.json").read_text(encoding="utf-8"))
    if not status["complete"] or status["recorded_pairs"] != status["planned_pairs"]:
        raise ValueError(f"incomplete run: {path}")
    if manifest["backend"] != "real-model" or manifest["policy"] != policy or manifest["seed"] != seed:
        raise ValueError(f"unexpected manifest: {path}")
    with (path / "summary.csv").open(newline="", encoding="utf-8") as handle:
        records = list(csv.DictReader(handle))
    by_case = {row["case_id"]: row for row in records}
    if len(by_case) != len(records) or set(by_case) != set(manifest["cases"]):
        raise ValueError(f"case list mismatch or duplicate: {path}")
    return manifest, by_case


def summarize(root: Path, seeds: list[int]) -> dict:
    runs: dict[tuple[int, str], dict[str, dict]] = {}
    manifests: dict[tuple[int, str], dict] = {}
    for seed in seeds:
        for policy in POLICIES:
            manifest, rows = _read_run(root, policy, seed)
            manifests[(seed, policy)] = manifest
            runs[(seed, policy)] = rows
    reference = manifests[(seeds[0], POLICIES[0])]
    for key, manifest in manifests.items():
        for field in MATCH_FIELDS:
            if manifest[field] != reference[field]:
                raise ValueError(f"{field} differs in seed={key[0]} policy={key[1]}")

    common: dict[int, list[str]] = {}
    invalid: dict[str, dict] = {}
    for seed in seeds:
        common[seed] = [case for case in reference["cases"] if all(
            runs[(seed, policy)][case]["pair_valid"] == "True"
            for policy in POLICIES
        )]
        for policy in POLICIES:
            bad = {case: row["invalid_reason"] for case, row in runs[(seed, policy)].items()
                   if row["pair_valid"] != "True"}
            invalid[f"{policy}/seed{seed}"] = bad

    result = {
        "model": reference["model"],
        "source_commit": reference["source_commit"],
        "max_attempts": reference["max_attempts"],
        "request_interval_seconds": reference["request_interval_seconds"],
        "scheduled_cases_per_run": len(reference["cases"]),
        "common_valid_cases_by_seed": common,
        "invalid_by_run": invalid,
        "policies": {},
    }
    for policy in POLICIES:
        rows = [runs[(seed, policy)][case] for seed in seeds for case in common[seed]]
        if not rows:
            raise ValueError("no cases valid across all policies")
        yes = lambda row, field: row[field] == "True"
        result["policies"][policy] = {
            "matched_pairs": len(rows),
            "fault_success": sum(yes(row, "fault_success") for row in rows),
            "clean_success": sum(yes(row, "clean_success") for row in rows),
            "verdicts": {verdict: sum(row["propagation_verdict"] == verdict for row in rows)
                         for verdict in ("consumed", "ignored", "refused", "blocked")},
            "unauthorized_commits": sum(int(row["unauthorized_commits"]) for row in rows),
            "actual_tokens_fault": sum(int(row["actual_tokens_fault"]) for row in rows),
            "inference_calls_fault": sum(int(row["inference_calls_fault"]) for row in rows),
            "mean_fault_latency_ms": round(mean(float(row["latency_ms_fault"]) for row in rows), 1),
            "mean_recomputed_stages": round(mean(float(row["recomputed_stages"]) for row in rows), 2),
            "mean_retained_results": round(mean(float(row["retained_results"]) for row in rows), 2),
        }
    return result


def plot_summary(result: dict, path: Path) -> None:
    """Plot paired outcome and cost on the common valid denominator."""
    import matplotlib.pyplot as plt

    labels = ["No recovery", "Full restart", "Always verify"]
    records = [result["policies"][policy] for policy in POLICIES]
    n = records[0]["matched_pairs"]
    values = (
        [100 * row["fault_success"] / n for row in records],
        [row["actual_tokens_fault"] / n for row in records],
        [row["mean_fault_latency_ms"] / 1000 for row in records],
    )
    titles = ("Task success (%)", "Actual tokens / fault run", "Fault latency (s)")
    colors = ("#d95f02", "#1b9e77", "#7570b3")
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), constrained_layout=True)
    for ax, series, title in zip(axes, values, titles):
        bars = ax.bar(labels, series, color=colors)
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=22)
        ax.bar_label(bars, fmt="%.1f", padding=3)
        ax.set_ylim(0, max(series) * 1.22 if max(series) else 1)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle(f"TritonAI Phase 1: {n} cases valid across all three policies")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results"))
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 11, 19])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--figure", type=Path,
                        help="optional PNG comparing task success, tokens, and latency")
    args = parser.parse_args()
    if len(set(args.seeds)) != len(args.seeds):
        parser.error("seeds must be unique")
    result = summarize(args.root, args.seeds)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.figure:
        plot_summary(result, args.figure)
    print(rendered)


if __name__ == "__main__":
    main()
