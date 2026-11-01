"""Export a typed dependency graph and fault impact from one paired run.

Example:
    python scripts/inspect_provenance.py \
      results/paired/pairs/incorrect-db-port-3306__no_recovery__seed-7/paired.json \
      --output results/paired/incorrect-port-impact.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stateguard.provenance import build_provenance
from stateguard.recovery_assessment import assess_recovery
from stateguard.state import StateStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paired_json", type=Path)
    parser.add_argument("--faulty-result-id")
    parser.add_argument("--db", type=Path,
                        help="SQLite attempt database; defaults to fault.sqlite3 beside paired.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    pair = json.loads(args.paired_json.read_text(encoding="utf-8"))
    fault = pair["fault"]
    graph = build_provenance(fault["trace"])
    applied_ids = [case["result_id"] for case in fault["applied_cases"]]
    faulty_id = args.faulty_result_id
    if faulty_id is None:
        if len(applied_ids) != 1:
            parser.error("choose --faulty-result-id when the pair has zero or multiple faults")
        faulty_id = applied_ids[0]
    result = {
        "pair_id": pair["pair_id"],
        "faulty_result_id": faulty_id,
        "impact": graph.impacted_by(faulty_id).as_dict(),
        "graph": graph.as_dict(),
    }
    db_path = args.db or args.paired_json.parent / "fault.sqlite3"
    if db_path.exists():
        store = StateStore(db_path)
        try:
            durable = store.trace(fault["trace"]["attempt_id"])
            result["recovery_preflight"] = assess_recovery(
                store=store, trace=durable, faulty_result_id=faulty_id,
            ).as_dict()
        finally:
            store.close()
    else:
        result["recovery_preflight"] = None
    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(output)


if __name__ == "__main__":
    main()
