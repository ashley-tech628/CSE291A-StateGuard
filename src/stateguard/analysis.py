"""Figures and the written summary for paired clean/fault experiments.

matplotlib is imported inside the plotting functions, so the metrics layer and
its tests stay usable on a machine that has no plotting stack installed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .metrics import build_report, read_summary_csv

CLEAN_COLOR = "#4C78A8"
FAULT_COLOR = "#E45756"
VERDICT_COLORS = {"consumed": "#E45756", "ignored": "#54A24B", "blocked": "#9D9D9D"}
VERDICTS = ("consumed", "ignored", "blocked")


def _pyplot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _ordered(rows: Sequence[dict[str, Any]], key: str) -> list[str]:
    seen: list[str] = []
    for row in rows:
        value = str(row[key])
        if value not in seen:
            seen.append(value)
    return sorted(seen)


def _rate(rows: Sequence[dict[str, Any]], field: str) -> float:
    return sum(bool(row[field]) for row in rows) / len(rows) if rows else 0.0


def _mean(rows: Sequence[dict[str, Any]], field: str) -> float:
    return sum(float(row[field]) for row in rows) / len(rows) if rows else 0.0


def _grouped(rows: Sequence[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row[key]), []).append(row)
    return groups


def _finish(plt, fig, ax, title: str, ylabel: str, path: Path) -> Path:
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_success_rate(rows: Sequence[dict[str, Any]], outdir: Path) -> Path:
    """Clean vs fault task success, grouped by fault type."""
    plt = _pyplot()
    groups = _grouped(rows, "fault_type")
    labels = sorted(groups)
    clean = [_rate(groups[name], "clean_success") for name in labels]
    fault = [_rate(groups[name], "fault_success") for name in labels]
    positions = range(len(labels))
    width = 0.38

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar([p - width / 2 for p in positions], clean, width, label="clean", color=CLEAN_COLOR)
    ax.bar([p + width / 2 for p in positions], fault, width, label="fault", color=FAULT_COLOR)
    ax.set_xticks(list(positions))
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.05)
    ax.legend(frameon=False)
    return _finish(plt, fig, ax, "Task success, clean vs injected fault", "success rate",
                   outdir / "success_rate.png")


def plot_propagation(rows: Sequence[dict[str, Any]], outdir: Path) -> Path:
    """Where each injected fault ended up: consumed, ignored, or blocked."""
    plt = _pyplot()
    groups = _grouped(rows, "fault_type")
    labels = sorted(groups)
    bottoms = [0.0] * len(labels)

    fig, ax = plt.subplots(figsize=(7, 4))
    for verdict in VERDICTS:
        heights = [
            sum(row["propagation_verdict"] == verdict for row in groups[name])
            for name in labels
        ]
        ax.bar(labels, heights, bottom=bottoms, label=verdict, color=VERDICT_COLORS[verdict])
        bottoms = [b + h for b, h in zip(bottoms, heights)]
    ax.legend(frameon=False)
    return _finish(plt, fig, ax, "Fault propagation verdict by fault type", "paired runs",
                   outdir / "propagation.png")


def plot_safety(rows: Sequence[dict[str, Any]], outdir: Path) -> Path:
    """Unauthorised attempts against unauthorised commits, by fault class."""
    plt = _pyplot()
    groups = _grouped(rows, "fault_class")
    labels = sorted(groups)
    attempts = [sum(int(r["unauthorized_attempts"]) for r in groups[n]) for n in labels]
    commits = [sum(int(r["unauthorized_commits"]) for r in groups[n]) for n in labels]
    positions = range(len(labels))
    width = 0.38

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar([p - width / 2 for p in positions], attempts, width,
           label="attempts (rejected at the tool layer)", color="#F58518")
    ax.bar([p + width / 2 for p in positions], commits, width,
           label="commits (invariant broken)", color=FAULT_COLOR)
    ax.set_xticks(list(positions))
    ax.set_xticklabels(labels)
    ax.legend(frameon=False)
    return _finish(plt, fig, ax, "Unauthorised actions by fault class", "actions",
                   outdir / "safety.png")


def plot_cost(rows: Sequence[dict[str, Any]], outdir: Path) -> Path:
    """What the faulty run cost relative to its own clean control."""
    plt = _pyplot()
    groups = _grouped(rows, "fault_type")
    labels = sorted(groups)
    clean = [_mean(groups[name], "inference_calls_clean") for name in labels]
    fault = [_mean(groups[name], "inference_calls_fault") for name in labels]
    positions = range(len(labels))
    width = 0.38

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar([p - width / 2 for p in positions], clean, width, label="clean", color=CLEAN_COLOR)
    ax.bar([p + width / 2 for p in positions], fault, width, label="fault", color=FAULT_COLOR)
    ax.set_xticks(list(positions))
    ax.set_xticklabels(labels)
    ax.legend(frameon=False)
    return _finish(plt, fig, ax, "Mean agent calls per run", "calls",
                   outdir / "cost.png")


def build_figures(rows: Sequence[dict[str, Any]], outdir: Path) -> list[Path]:
    if not rows:
        raise ValueError("no rows to plot")
    return [
        plot_success_rate(rows, outdir),
        plot_propagation(rows, outdir),
        plot_safety(rows, outdir),
        plot_cost(rows, outdir),
    ]


def render_markdown(report: dict[str, Any], rows: Sequence[dict[str, Any]]) -> str:
    """A short report the group can paste into the write-up."""
    overall = report["overall"]
    lines = [
        "# Paired clean/fault evaluation",
        "",
        f"Paired experiments: **{report['pairs']}**",
        "",
        "## Overall",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Clean success rate | {overall['clean_success_rate']} |",
        f"| Fault success rate | {overall['fault_success_rate']} |",
        f"| Faults exposed to the planner | {overall['exposed']} |",
        f"| Consumed / ignored / blocked | {overall['consumed']} / {overall['ignored']} / {overall['blocked']} |",
        f"| Unauthorised attempts | {overall['unauthorized_attempts']} |",
        f"| Unauthorised commits | {overall['unauthorized_commits']} |",
        f"| Mean affected stages | {overall['mean_affected_stages']} |",
        f"| Mean latency clean / fault (ms) | {overall['mean_latency_ms_clean']} / {overall['mean_latency_ms_fault']} |",
        "",
        "## By fault class",
        "",
        "| Class | Pairs | Fault success | Consumed | Unauth. commits |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, stats in report["by_fault_class"].items():
        lines.append(
            f"| {name} | {stats['pairs']} | {stats['fault_success_rate']} | "
            f"{stats['consumed']} | {stats['unauthorized_commits']} |"
        )
    lines += [
        "",
        "## Control cases: exposed but not propagated",
        "",
        "| Case | Exposed | Verdict | Plan identical | State identical |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        if row["expected_propagation"] != "ignored":
            continue
        lines.append(
            f"| {row['case_id']} | {row['fault_exposed']} | {row['propagation_verdict']} | "
            f"{row['plan_writes_identical']} | {row['final_state_identical']} |"
        )
    mismatches = report["expectation_mismatches"]
    lines += ["", "## Expectation mismatches", ""]
    lines.append("None." if not mismatches else "")
    for item in mismatches:
        lines.append(f"- `{item['case_id']}`: expected {item['expected']}, observed {item['observed']}")
    lines.append("")
    return "\n".join(lines)


def analyse(rows: Sequence[dict[str, Any]], outdir: Path, with_figures: bool = True) -> dict[str, Any]:
    """Write report.json, report.md and the figures into ``outdir``."""
    outdir.mkdir(parents=True, exist_ok=True)
    report = build_report(rows)
    (outdir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (outdir / "report.md").write_text(render_markdown(report, rows), encoding="utf-8")
    if with_figures:
        build_figures(rows, outdir / "figures")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot a paired clean/fault summary")
    parser.add_argument("--input", type=Path, required=True, help="summary.csv to read")
    parser.add_argument("--output", type=Path, help="directory for figures and report")
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()
    rows = read_summary_csv(args.input)
    outdir = args.output or args.input.parent
    report = analyse(rows, outdir, with_figures=not args.no_figures)
    print(json.dumps(report["overall"], indent=2))
    print("Saved:", outdir)


if __name__ == "__main__":
    main()
