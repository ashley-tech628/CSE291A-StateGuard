"""Render a compact, vector architecture figure for the Phase 1 appendix."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


OUT = Path(__file__).parent / "figures" / "architecture"


def main() -> None:
    with plt.rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42}):
        fig, ax = plt.subplots(figsize=(3.28, 2.32))
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.axis("off")

        def box(x, y, w, h, label, *, fill="#EDF2F5", size=7.1):
            ax.add_patch(FancyBboxPatch(
                (x, y), w, h, boxstyle="round,pad=0.10,rounding_size=0.11",
                linewidth=0.75, edgecolor="#426076", facecolor=fill,
            ))
            ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                    fontsize=size, color="#1E303B", linespacing=1.2)

        def arrow(a, b, *, color="#526B7B", rad=0):
            ax.add_patch(FancyArrowPatch(
                a, b, arrowstyle="-|>", mutation_scale=7.4, linewidth=0.85,
                color=color, connectionstyle=f"arc3,rad={rad}",
            ))

        box(2.4, 8.85, 5.2, .78, "Request + versioned guide", size=6.4)
        box(.25, 6.88, 2.84, 1.02, "Config\nAgent", fill="#E3EDF4", size=6.3)
        box(3.58, 6.88, 2.84, 1.02, "Dependency\nAgent", fill="#E3EDF4", size=6.3)
        box(6.91, 6.88, 2.84, 1.02, "Resource\nAgent", fill="#E3EDF4", size=6.3)
        box(.8, 5.20, 3.5, .80, "TritonAI adapter", fill="#F2F4F6", size=6.2)
        box(5.65, 5.20, 3.5, .80, "Planner", fill="#DCEBE7", size=6.6)
        box(5.65, 3.54, 3.5, .80, "Executor", fill="#DCEBE7", size=6.6)
        box(.38, 3.27, 4.25, 1.30,
            "SQLite state + ledger\n(field versions, events)", fill="#F7EEDB", size=6.1)
        box(.38, 1.05, 4.25, 1.04, "Provenance graph", fill="#E8ECF3", size=6.2)
        box(5.43, 1.05, 4.25, 1.04, "Checker + replay", fill="#E7EFE9", size=6.2)

        for x in (1.67, 5.0, 8.33):
            arrow((5, 8.85), (x, 8.02))
        for x in (1.67, 5.0, 8.33):
            arrow((x, 6.88), (7.4, 6.12))
        arrow((4.3, 5.6), (5.55, 5.6), color="#6F8290")
        arrow((7.4, 5.20), (7.4, 4.46))
        arrow((5.55, 3.94), (4.75, 3.94))
        arrow((2.5, 3.27), (2.5, 2.21))
        arrow((4.75, 1.57), (5.31, 1.57))
        arrow((7.55, 2.20), (7.55, 3.42), color="#168077")
        ax.text(7.83, 2.78, "version checks", fontsize=5.5,
                color="#167368", va="center")
        ax.text(5, .33, "Fault identity supplied by evaluation harness",
                ha="center", va="center", fontsize=6.4, color="#52616D")
        fig.savefig(OUT.with_suffix(".pdf"), bbox_inches="tight", pad_inches=.025)
        fig.savefig(OUT.with_suffix(".png"), dpi=320, bbox_inches="tight", pad_inches=.025)
        plt.close(fig)


if __name__ == "__main__":
    main()
