"""Build a single-column vector architecture figure for the Phase 1 report."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


OUT = Path(__file__).parent / "figures" / "architecture"
INK = "#243744"
FORWARD = "#496371"
RECOVERY = "#15736B"


def main() -> None:
    with plt.rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42}):
        fig, ax = plt.subplots(figsize=(3.26, 2.48))
        ax.set(xlim=(0, 3.26), ylim=(0, 2.5))
        ax.axis("off")

        def box(x: float, y: float, width: float, label: str,
                *, color: str = FORWARD, fill: str = "#FFFFFF") -> None:
            ax.add_patch(Rectangle((x, y), width, .34, linewidth=.7,
                                   edgecolor=color, facecolor=fill))
            ax.text(x + width / 2, y + .17, label, ha="center", va="center",
                    fontsize=7.8, color=INK)

        def arrow(x1: float, y1: float, x2: float, y2: float,
                  *, color: str = FORWARD) -> None:
            ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2),
                                         arrowstyle="-|>", mutation_scale=7,
                                         linewidth=.75, color=color,
                                         shrinkA=0, shrinkB=1))

        box(.08, 2.08, 3.10, "Task request + versioned guide")
        box(.08, 1.58, 3.10, "Config / Dependency / Resource agents")
        box(.08, 1.08, 1.40, "Planner")
        box(1.80, 1.08, 1.38, "Tool executor")
        box(.08, .58, 3.10, "SQLite field versions + action ledger",
            fill="#F0F4F6")
        box(.08, .08, 1.57, "Trace + provenance", color=RECOVERY,
            fill="#F0F7F5")
        box(1.93, .08, 1.25, "Replay / block", color=RECOVERY,
            fill="#F0F7F5")

        arrow(1.63, 2.08, 1.63, 1.92)
        arrow(.78, 1.58, .78, 1.42)
        arrow(1.48, 1.25, 1.80, 1.25)
        arrow(2.49, 1.08, 2.49, .92)
        arrow(.86, .58, .86, .42)
        arrow(1.65, .25, 1.93, .25, color=RECOVERY)

        fig.savefig(OUT.with_suffix(".pdf"), bbox_inches="tight", pad_inches=.025)
        fig.savefig(OUT.with_suffix(".png"), dpi=320, bbox_inches="tight", pad_inches=.025)
        plt.close(fig)


if __name__ == "__main__":
    main()
