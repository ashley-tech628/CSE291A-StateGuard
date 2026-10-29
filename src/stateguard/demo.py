"""Fixed-output clean path; replace each stage behind the shared contracts."""

import json
from dataclasses import asdict
from pathlib import Path

from .schemas import AgentResult
from .state import StateStore


def run_clean_demo(db_path: str | Path, trace_path: str | Path, run_id: str = "demo-001") -> dict:
    db_path, trace_path = Path(db_path), Path(trace_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    store = StateStore(db_path)
    try:
        store.seed("database.port", 5432)
        store.seed("api.db_port", 5431)
        source = store.read("database.port")
        config = AgentResult(
            run_id, "config-1", "config", (), {"database.port": source.version},
            {"db_port": source.value},
        )
        store.record_result(config)
        current = store.read("api.db_port")
        plan = AgentResult(
            run_id, "plan-1", "planner", (config.result_id,),
            {"api.db_port": current.version},
            {"target_key": "api.db_port", "target_value": config.content["db_port"]},
        )
        store.record_result(plan)
        store.update(
            run_id=run_id, key=plan.content["target_key"],
            value=plan.content["target_value"], expected_version=current.version,
            actor="executor", action_id=f"{run_id}-write-1",
            parent_result_ids=(plan.result_id,),
        )
        final = store.read("api.db_port")
        success = final.value == store.read("database.port").value
        trace = store.trace(run_id)
        trace_path.write_text(json.dumps(asdict(trace), ensure_ascii=False, indent=2), encoding="utf-8")
        return {"run_id": run_id, "success": success, "api.db_port": final.value,
                "results": len(trace.results), "actions": len(trace.actions),
                "events": len(trace.events), "trace_path": str(trace_path)}
    finally:
        store.close()
