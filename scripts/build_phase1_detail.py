"""Export matched Phase 1 case-level results and presentation-ready figures.

Run after all nine real-model baseline directories exist:
    python scripts/build_phase1_detail.py --root results --seeds 7 11 19
"""

from __future__ import annotations

import argparse
import csv
import json
import io
from pathlib import Path

from summarize_matched_phase1 import DIRECTORY_LABELS, POLICIES, summarize


FIELDS = (
    "seed", "case_id", "fault_class", "fault_type", "target_agent", "policy",
    "clean_success", "fault_success", "fault_exposed", "fault_consumed",
    "propagation_verdict", "display_verdict", "unauthorized_attempts", "unauthorized_commits",
    "inference_calls_fault", "actual_tokens_fault", "latency_ms_fault",
    "recomputed_stages", "retained_results", "recovery_status",
)
LABELS = {"no_recovery": "No recovery", "full_restart": "Full restart",
          "always_verify": "Always verify"}
COLORS = {"no_recovery": "#54708A", "full_restart": "#148473",
          "always_verify": "#8B6B9C"}
SHORT_CASES = {
    "incorrect-db-port-3306": "DB port · 3306",
    "incorrect-db-port-unreachable": "DB port · unreachable",
    "incorrect-db-port-persistent": "DB port · persistent",
    "stale-protocol-superseded-doc": "Protocol · superseded guide",
    "stale-protocol-unknown-version": "Protocol · unknown version",
    "timeout-config-agent": "Config Agent · timeout",
    "timeout-resource-agent": "Resource Agent · timeout",
    "adversarial-disable-auth": "Injection · disable auth",
    "adversarial-disable-audit": "Injection · disable audit",
    "ignored-resource-cpu-count": "Control · CPU count",
    "ignored-dependency-compat-flag": "Control · compatibility flag",
}


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
                        selected_row = {field: row[field] for field in FIELDS
                                        if field != "display_verdict"}
                        selected_row["display_verdict"] = _display_verdict(
                            root, seed, policy, row
                        )
                        selected.append(selected_row)
    if len(selected) != sum(len(v) for v in summary["common_valid_cases_by_seed"].values()) * len(POLICIES):
        raise ValueError("matched row count disagrees with manifest and validity gate")
    order = [case for case in order if any(row["case_id"] == case for row in selected)]
    return summary, selected, order


def _display_verdict(root: Path, seed: int, policy: str, row: dict) -> str:
    """Distinguish verifier correction from a genuinely ignored fault.

    The stored propagation verdict remains unchanged. The extra display label
    is derived from the paired trace so a future AV run that actually ignores
    a fault is not mislabeled as corrected.
    """
    verdict = row["propagation_verdict"]
    if policy != "always_verify" or verdict != "ignored":
        return verdict
    pair_path = (root / f"c-phase1-llm-{DIRECTORY_LABELS[policy]}-seed{seed}"
                 / "pairs" / f"{row['case_id']}__{policy}__seed-{seed}" / "paired.json")
    pair = json.loads(pair_path.read_text(encoding="utf-8"))
    events = pair["fault"]["trace"]["verification_events"]
    corrected = any(event.get("agent_id") == row["target_agent"]
                    and event["valid"] is False and event.get("retry_valid") is True
                    for event in events)
    if corrected and not pair["comparison"]["fault_exposed_to_planner"]:
        return "corrected"
    return verdict


def write_detail(rows: list[dict], path: Path) -> None:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    content = handle.getvalue()
    existing = None
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as current:
            existing = current.read()
    if existing != content:
        path.write_text(content, encoding="utf-8", newline="")


def plot_case_success(rows: list[dict], order: list[str], path: Path) -> None:
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import ListedColormap

    with plt.rc_context(_paper_style()):
        fig, ax = plt.subplots(figsize=(7.2, 4.9))
        values = np.zeros((len(order), len(POLICIES)))
        counts = {}
        for i, case in enumerate(order):
            for j, policy in enumerate(POLICIES):
                group = [row for row in rows if row["case_id"] == case
                         and row["policy"] == policy]
                successes = sum(row["fault_success"] == "True" for row in group)
                values[i, j] = successes / len(group)
                counts[i, j] = f"{successes}/{len(group)}"
        ax.imshow(values, cmap=ListedColormap(["#EDF0F2", "#18758A"]),
                  vmin=0, vmax=1, aspect="auto", interpolation="nearest")
        for (i, j), count in counts.items():
            ax.text(j, i, count, ha="center", va="center", fontsize=8,
                    weight="bold", color="white" if values[i, j] > .5 else "#273540")
        ax.set_xticks(range(len(POLICIES)), [LABELS[p] for p in POLICIES])
        ax.xaxis.tick_top()
        ax.set_yticks(range(len(order)), [SHORT_CASES.get(case, case) for case in order])
        ax.tick_params(length=0, pad=5)
        ax.set_xticks(np.arange(-.5, len(POLICIES), 1), minor=True)
        ax.set_yticks(np.arange(-.5, len(order), 1), minor=True)
        ax.grid(which="minor", color="white", linewidth=1.5)
        ax.tick_params(which="minor", bottom=False, left=False)
        for boundary in (6.5, 8.5):
            if boundary < len(order) - .5:
                ax.axhline(boundary, color="#586774", linewidth=1.1)
        for spine in ax.spines.values():
            spine.set_visible(False)
        fig.subplots_adjust(left=.34, right=.98, top=.88, bottom=.12)
        fig.text(.34, .035, "Cells show completed tasks / common valid seeds; denominators reflect exclusions.",
                 fontsize=7, color="#4B5965")
        _save_figure(fig, path)
        plt.close(fig)


def plot_propagation_and_cost(rows: list[dict], path: Path, *, compact: bool = False) -> None:
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Patch

    with plt.rc_context(_paper_style()):
        fig, axes = plt.subplots(1, 3, figsize=(7, 2.2) if compact else (11.8, 3.65),
                                 gridspec_kw={"width_ratios": [1.27, 1, 1]})
        positions = [2, 1, 0]
        labels = [LABELS[p] for p in POLICIES]
        left = [0] * len(POLICIES)
        verdict_colors = {"consumed": "#C05A46", "ignored": "#4E79A7",
                          "corrected": "#168077", "refused": "#E3B35C",
                          "blocked": "#91979D"}
        verdict_order = ("consumed", "ignored", "corrected", "refused", "blocked")
        for verdict in verdict_order:
            counts = [sum(row["policy"] == policy
                          and row.get("display_verdict", row["propagation_verdict"]) == verdict
                          for row in rows) for policy in POLICIES]
            axes[0].barh(positions, counts, left=left, height=.52,
                         color=verdict_colors[verdict], edgecolor="white", linewidth=.5)
            for y, count, start in zip(positions, counts, left):
                if count:
                    axes[0].text(start + count / 2, y, str(count), ha="center",
                                 va="center", fontsize=7.5, weight="bold",
                                 color="white" if verdict in ("consumed", "ignored", "corrected")
                                 else "#26333C")
            left = [a + b for a, b in zip(left, counts)]
        axes[0].set_xlim(0, len(rows) // len(POLICIES))
        axes[0].set_xlabel(f"Fault runs (n = {len(rows) // len(POLICIES)})")
        axes[0].set_title("(a) Propagation", loc="left", pad=9, weight="bold")

        rng = np.random.default_rng(7)
        for axis, field, title, scale in (
            (axes[1], "actual_tokens_fault", "(b) Inference cost", 1),
            (axes[2], "latency_ms_fault", "(c) End-to-end latency", 1000),
        ):
            groups = [[float(row[field]) / scale for row in rows if row["policy"] == p]
                      for p in POLICIES]
            boxes = axis.boxplot(groups, orientation="horizontal", positions=positions,
                                 widths=.42, patch_artist=True, showfliers=False,
                                 medianprops={"color": "#1E2A32", "linewidth": 1.1},
                                 boxprops={"linewidth": .8, "edgecolor": "#4E79A7"},
                                 whiskerprops={"color": "#65717B", "linewidth": .8},
                                 capprops={"color": "#65717B", "linewidth": .8})
            for box in boxes["boxes"]:
                box.set_facecolor("#D7E3EB")
            for y, group in zip(positions, groups):
                axis.scatter(group, y + rng.uniform(-.12, .12, len(group)),
                             s=9, color="#315D76", alpha=.38, linewidth=0, zorder=3)
            axis.set_xlabel("Tokens" if scale == 1 else "Seconds")
            axis.set_title(title, loc="left", pad=9, weight="bold")
        for axis in axes:
            axis.set_yticks(positions, labels)
            axis.set_ylim(-.65, 2.65)
            axis.grid(axis="x", color="#E1E5E8", linewidth=.55)
            axis.set_axisbelow(True)
            axis.spines[["top", "right", "left"]].set_visible(False)
            axis.tick_params(axis="y", length=0, pad=4)
            axis.tick_params(axis="x", direction="out")
        if compact:
            for axis in axes:
                axis.title.set_fontsize(8)
                axis.xaxis.label.set_fontsize(7.5)
                axis.tick_params(labelsize=7)
            for axis in axes[1:]:
                axis.set_yticklabels([])
            axes[0].set_xticks([0, 10, 20, 30])
            axes[1].set_xticks([500, 1000, 1500])
            axes[2].set_xticks([15, 25, 35, 45])
            fig.subplots_adjust(left=.13, right=.99, top=.84, bottom=.30, wspace=.20)
        else:
            fig.subplots_adjust(left=.11, right=.99, top=.80, bottom=.24, wspace=.49)
        legend_labels = {"consumed": "Consumed", "ignored": "Ignored",
                         "corrected": "Corrected before Planner (AV)",
                         "refused": "Refused", "blocked": "Blocked"}
        fig.legend(handles=[Patch(facecolor=verdict_colors[v], label=legend_labels[v])
                            for v in verdict_order],
                   loc="lower left", bbox_to_anchor=(.105, .035), ncol=5,
                   frameon=False, fontsize=7 if compact else 7.5,
                   columnspacing=.9 if compact else 1.5, handlelength=1.2)
        _save_figure(fig, path)
        plt.close(fig)


def _paper_style() -> dict:
    return {
        "font.family": "DejaVu Sans", "font.size": 8.2,
        "axes.titlesize": 9, "axes.labelsize": 8,
        "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
        "axes.linewidth": .65, "xtick.major.width": .6,
        "ytick.major.width": .6, "pdf.fonttype": 42,
        "svg.fonttype": "none", "savefig.facecolor": "white",
    }


def _save_figure(fig, path: Path) -> None:
    fig.savefig(path, dpi=320, bbox_inches="tight", pad_inches=.06)
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight", pad_inches=.06)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results"))
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 11, 19])
    args = parser.parse_args()
    summary, rows, order = matched_rows(args.root, args.seeds)
    suffix = "" if args.seeds == [7, 11, 19] else "-seeds-" + "-".join(map(str, args.seeds))
    detail = args.root / f"c-phase1-llm{suffix}-detailed-cases.csv"
    success = args.root / f"c-phase1-llm{suffix}-case-success-paper.png"
    cost = args.root / f"c-phase1-llm{suffix}-propagation-cost-paper.png"
    write_detail(rows, detail)
    plot_case_success(rows, order, success)
    plot_propagation_and_cost(rows, cost)
    print(f"Matched case/seed combinations: {sum(map(len, summary['common_valid_cases_by_seed'].values()))}")
    print(f"Detailed rows: {len(rows)}")
    print(f"Saved: {detail}, {success}, {success.with_suffix('.pdf')}, "
          f"{cost}, {cost.with_suffix('.pdf')}")


if __name__ == "__main__":
    main()
