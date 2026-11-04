"""Draw the single-column, vector StateGuard architecture figure."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


OUT = Path(__file__).parent / "figures" / "architecture"
INK = "#202C34"
BLUE = "#526D7D"
TEAL = "#18766F"


def main() -> None:
    # The report uses 10 pt newtxtext. Times New Roman closely matches its
    # proportions, and the PDF keeps text and rules as vector objects.
    with plt.rc_context({"font.family": "Times New Roman", "pdf.fonttype": 42}):
        fig, ax = plt.subplots(figsize=(3.30, 4.86))
        ax.set(xlim=(0, 3.30), ylim=(0, 4.86))
        ax.set_aspect("equal")
        ax.axis("off")

        def node(x: float, y: float, width: float, height: float, label: str,
                 *, edge: str = BLUE, fill: str = "#FFFFFF") -> None:
            ax.add_patch(Rectangle((x, y), width, height, linewidth=.78,
                                   edgecolor=edge, facecolor=fill, zorder=3))
            ax.text(x + width / 2, y + height / 2, label,
                    ha="center", va="center", fontsize=10, color=INK,
                    linespacing=1.05, zorder=4)

        def line(x1: float, y1: float, x2: float, y2: float,
                 *, color: str = BLUE) -> None:
            ax.plot([x1, x2], [y1, y2], color=color, linewidth=.77, zorder=1)

        def arrow(x1: float, y1: float, x2: float, y2: float,
                  *, color: str = BLUE) -> None:
            ax.add_patch(FancyArrowPatch(
                (x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=7.5,
                linewidth=.82, color=color, shrinkA=0, shrinkB=0, zorder=2))

        ax.text(.07, 4.75, "FORWARD EXECUTION", fontsize=10, weight="bold",
                color=BLUE, va="center")
        line(.07, 4.66, 3.22, 4.66, color="#B9C6CE")

        node(.07, 4.22, 3.15, .37, "Task request + versioned guide",
             fill="#F4F7F8")
        for x, width, label in ((.07, .89, "Config\nAgent"),
                                (1.12, 1.06, "Dependency\nAgent"),
                                (2.34, .88, "Resource\nAgent")):
            node(x, 3.47, width, .47, label, fill="#F4F7F8")
        # Orthogonal buses distinguish fan-out and fan-in dependencies.
        line(1.645, 4.22, 1.645, 4.10)
        line(.515, 4.10, 2.78, 4.10)
        for x in (.515, 1.65, 2.78):
            arrow(x, 4.10, x, 3.94)
            line(x, 3.47, x, 3.31)
        line(.515, 3.31, 2.78, 3.31)
        arrow(1.645, 3.31, 1.645, 3.10)

        node(.68, 2.69, 1.93, .41, "Planner", fill="#EAF3F3")
        arrow(1.645, 2.69, 1.645, 2.50)
        node(.68, 2.09, 1.93, .41, "Controlled executor",
             fill="#EAF3F3")
        line(1.645, 2.09, 1.645, 2.02)
        line(.80, 2.02, 2.50, 2.02)
        arrow(.80, 2.02, .80, 1.95)
        arrow(2.50, 2.02, 2.50, 1.95)
        node(.07, 1.45, 1.46, .50, "SQLite field\nversions",
             fill="#F4F7F8")
        node(1.77, 1.45, 1.45, .50, "Action ledger",
             fill="#F4F7F8")

        ax.text(.07, 1.28, "FAULT RECOVERY", fontsize=10, weight="bold",
                color=TEAL, va="center")
        line(.07, 1.18, 3.22, 1.18, color="#A6C6C2")
        node(.07, .78, 1.46, .35, "Known fault ID", edge=TEAL,
             fill="#F1F8F6")
        node(1.77, .78, 1.45, .35, "Provenance DAG", edge=TEAL,
             fill="#F1F8F6")
        # State and committed actions both enter the dependency trace.
        line(.80, 1.45, .80, 1.40, color=TEAL)
        line(.80, 1.40, 2.50, 1.40, color=TEAL)
        line(2.50, 1.45, 2.50, 1.40, color=TEAL)
        arrow(2.50, 1.40, 2.50, 1.13, color=TEAL)

        node(.07, .13, 1.46, .42, "Impact + version\nchecks", edge=TEAL,
             fill="#F1F8F6")
        node(1.77, .13, 1.45, .42, "Replay or\nexplicit block", edge=TEAL,
             fill="#F1F8F6")
        arrow(.80, .78, .80, .55, color=TEAL)
        line(2.50, .78, 2.50, .67, color=TEAL)
        line(2.50, .67, 1.23, .67, color=TEAL)
        arrow(1.23, .67, 1.23, .55, color=TEAL)
        arrow(1.53, .34, 1.77, .34, color=TEAL)

        fig.savefig(OUT.with_suffix(".pdf"), bbox_inches="tight", pad_inches=.025)
        fig.savefig(OUT.with_suffix(".png"), dpi=320, bbox_inches="tight", pad_inches=.025)
        plt.close(fig)


if __name__ == "__main__":
    main()
