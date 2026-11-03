"""Build the full-width report figure from the common valid experiment pairs."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from build_phase1_detail import matched_rows, plot_propagation_and_cost

if __name__ == "__main__":
    _, rows, _ = matched_rows(ROOT / "results", [7, 11, 19])
    plot_propagation_and_cost(
        rows, Path(__file__).parent / "figures" / "propagation-cost.png", compact=True
    )
