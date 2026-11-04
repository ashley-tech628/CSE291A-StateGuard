"""Render the two-lane StateGuard architecture as a full-width vector figure."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


OUT = Path(__file__).parent / "figures" / "architecture"
INK = "#20323D"
MUTED = "#536877"
RULE = "#AAB8C0"
ACCENT = "#11766D"


def main() -> None:
    with plt.rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42}):
        fig, ax = plt.subplots(figsize=(7.0, 1.88))
        ax.set_xlim(-1, 101)
        ax.set_ylim(-1, 27)
        ax.axis("off")

        def box(x: float, y: float, w: float, h: float, label: str,
                *, recovery: bool = False, size: float = 8.0) -> None:
            ax.add_patch(Rectangle(
                (x, y), w, h, linewidth=.85,
                edgecolor=ACCENT if recovery else MUTED,
                facecolor="#F1F7F5" if recovery else "#F5F7F8",
            ))
            ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                    color=INK, fontsize=size, linespacing=1.18)

        def arrow(a: tuple[float, float], b: tuple[float, float],
                  *, recovery: bool = False, dashed: bool = False) -> None:
            ax.add_patch(FancyArrowPatch(
                a, b, arrowstyle="-|>", mutation_scale=8, linewidth=.95,
                color=ACCENT if recovery else MUTED,
                linestyle="--" if dashed else "-",
                shrinkA=2, shrinkB=2,
            ))

        ax.text(0, 25.2, "FORWARD EXECUTION", color=INK, fontsize=7.7,
                fontweight="bold", va="center")
        ax.text(100, 25.2, "TritonAI model adapter: agents + Planner",
                color=MUTED, fontsize=7.0, ha="right", va="center")
        ax.plot([0, 100], [23.7, 23.7], color=RULE, linewidth=.6)

        box(0, 15.2, 16, 6.7, "Task request\n+ guide version", size=7.2)
        box(20, 15.2, 25, 6.7, "Config  |  Dependency\nResource agents", size=7.8)
        box(49, 15.2, 12, 6.7, "Planner")
        box(65, 15.2, 14, 6.7, "Controlled\nexecutor", size=7.5)
        box(83, 15.2, 17, 6.7, "Versioned state\n+ action ledger", size=7.5)
        for x1, x2 in ((16, 20), (45, 49), (61, 65), (79, 83)):
            arrow((x1, 18.55), (x2, 18.55))

        ax.text(0, 11.8, "FAULT RECOVERY", color=ACCENT, fontsize=7.7,
                fontweight="bold", va="center")
        ax.plot([0, 100], [10.4, 10.4], color=RULE, linewidth=.6)

        box(18, 1.1, 26, 6.8, "Trace + typed\nprovenance", recovery=True)
        box(48, 1.1, 21, 6.8, "Impact +\nversion checks", recovery=True)
        box(74, 1.1, 26, 6.8, "Conditional replay\nor explicit block", recovery=True)
        arrow((44, 4.5), (48, 4.5), recovery=True)
        arrow((69, 4.5), (74, 4.5), recovery=True)
        arrow((32.5, 15.2), (32.5, 8.0))
        arrow((91.5, 15.2), (91.5, 8.0))
        arrow((77, 8.0), (72, 15.0), recovery=True, dashed=True)

        fig.savefig(OUT.with_suffix(".pdf"), bbox_inches="tight", pad_inches=.025)
        fig.savefig(OUT.with_suffix(".png"), dpi=320, bbox_inches="tight", pad_inches=.025)
        plt.close(fig)


if __name__ == "__main__":
    main()
