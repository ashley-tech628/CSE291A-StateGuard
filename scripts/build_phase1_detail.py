"""Export matched Phase 1 case-level results and presentation-ready figures.

Run after all nine real-model baseline directories exist:
    python scripts/build_phase1_detail.py --root results --seeds 7 11 19
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from summarize_matched_phase1 import DIRECTORY_LABELS, POLICIES, summarize


FIELDS = (
    "seed", "case_id", "fault_class", "fault_type", "target_agent", "policy",
    "clean_success", "fault_success", "fault_exposed", "fault_consumed",
    "propagation_verdict", "unauthorized_attempts", "unauthorized_commits",
    "inference_calls_fault", "actual_tokens_fault", "latency_ms_fault",
    "recomputed_stages", "retained_results", "recovery_status",
)
LABELS = {"no_recovery": "No recovery", "full_restart": "Full restart",
          "always_verify": "Always verify"}
COLORS = {"no_recovery": "#d95f02", "full_restart": "#1b9e77",
          "always_verify": "#7570b3"}


def matched_rows(root: Path, seeds: list[int]) -> tuple[dict, list[dict], list[str]]:
    """Reuse the manifest validity gate; retain only common valid pairs."""
    summary = summarize(root, seeds)
    order = json.loads((root / f"c-phase1-llm-no_recovery-seed{seeds[0]}"
                        / "manifest.json").read_text(encoding="utf-8"))["cases"]
    selected = []
    for seed in seeds:
        common = set(summary["common_valid_cases_by_seed"][seed])
        for policy in POLICIES:
            path = root / f"c-phase1-llm-{DIRECTORY_LABELS[policy]}-seed{seed}" / "summary.csv"
            with path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    if row["case_id"] in common:
                        selected.append({field: row[field] for field in FIELDS})
    if len(selected) != sum(len(v) for v in summary["common_valid_cases_by_seed"].values()) * len(POLICIES):
        raise ValueError("matched row count disagrees with manifest and validity gate")
    order = [case for case in order if any(row["case_id"] == case for row in selected)]
    return summary, selected, order


def write_detail(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def plot_case_success(rows: list[dict], order: list[str], path: Path) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    fig, ax = plt.subplots(figsize=(11.6, 7.1), constrained_layout=True)
    values = np.zeros((len(order), len(POLICIES)))
    labels = []
    for i, case in enumerate(order):
        case_rows = [row for row in rows if row["case_id"] == case]
        kind = "ADV" if case_rows[0]["fault_class"] == "adversarial" else "ACC"
        labels.append(f"{kind}  {case}")
        for j, policy in enumerate(POLICIES):
            group = [row for row in case_rows if row["policy"] == policy]
            successes = sum(row["fault_success"] == "True" for row in group)
            values[i, j] = successes / len(group)
            ax.text(j, i, f"{successes}/{len(group)}", ha="center", va="center",
                    fontsize=10, fontweight="bold")
    image = ax.imshow(values, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(POLICIES)), [LABELS[p] for p in POLICIES])
    ax.set_yticks(range(len(order)), labels)
    ax.set_title("Task success by fault case on the common valid seed set")
    ax.tick_params(length=0)
    fig.colorbar(image, ax=ax, label="Task success rate", fraction=0.035, pad=0.025)
    fig.savefig(path, dpi=190, bbox_inches="tight")
    plt.close(fig)


def plot_propagation_and_cost(rows: list[dict], path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(13.8, 4.4), constrained_layout=True)
    labels = [LABELS[p] for p in POLICIES]
    bottom = [0] * len(POLICIES)
    verdict_colors = {"consumed": "#d73027", "ignored": "#91bfdb",
                      "refused": "#fdae61", "blocked": "#777777"}
    for verdict in ("consumed", "ignored", "refused", "blocked"):
        counts = [sum(row["policy"] == policy and row["propagation_verdict"] == verdict
                      for row in rows) for policy in POLICIES]
        axes[0].bar(labels, counts, bottom=bottom, label=verdict,
                    color=verdict_colors[verdict])
        bottom = [a + b for a, b in zip(bottom, counts)]
    axes[0].set_title("Propagation verdicts")
    axes[0].set_ylabel("Matched fault runs")
    axes[0].legend(frameon=False, fontsize=8)

    for axis, field, title, scale in (
        (axes[1], "actual_tokens_fault", "Actual tokens per fault run", 1),
        (axes[2], "latency_ms_fault", "Fault latency (seconds)", 1000),
    ):
        groups = [[float(row[field]) / scale for row in rows if row["policy"] == p]
                  for p in POLICIES]
        boxes = axis.boxplot(groups, tick_labels=labels, patch_artist=True,
                             showfliers=True, medianprops={"color": "black"})
        for box, policy in zip(boxes["boxes"], POLICIES):
            box.set_facecolor(COLORS[policy])
            box.set_alpha(0.8)
        axis.set_title(title)
    for axis in axes:
        axis.tick_params(axis="x", rotation=18)
        axis.spines[["top", "right"]].set_visible(False)
    fig.suptitle(f"Phase 1: propagation and cost ({len(rows) // len(POLICIES)} "
                 "common valid cases per policy)")
    fig.savefig(path, dpi=190, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results"))
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 11, 19])
    args = parser.parse_args()
    summary, rows, order = matched_rows(args.root, args.seeds)
    suffix = "" if args.seeds == [7, 11, 19] else "-seeds-" + "-".join(map(str, args.seeds))
    detail = args.root / f"c-phase1-llm{suffix}-detailed-cases.csv"
    success = args.root / f"c-phase1-llm{suffix}-case-success.png"
    cost = args.root / f"c-phase1-llm{suffix}-propagation-cost.png"
    write_detail(rows, detail)
    plot_case_success(rows, order, success)
    plot_propagation_and_cost(rows, cost)
    print(f"Matched case/seed combinations: {sum(map(len, summary['common_valid_cases_by_seed'].values()))}")
    print(f"Detailed rows: {len(rows)}")
    print(f"Saved: {detail}, {success}, {cost}")


if __name__ == "__main__":
    main()
