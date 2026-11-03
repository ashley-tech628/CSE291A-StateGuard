import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from stateguard.model_adapter import ModelAdapter
from stateguard.workflow import DeploymentTask, WorkflowRunner

with tempfile.TemporaryDirectory() as folder:
    runner = WorkflowRunner(
        task=DeploymentTask(),
        fault="incorrect",
        policy="always_verify",
        db_path=Path(folder) / "state.sqlite3",
        attempt_id="real-config-verify",
        seed=7,
        config_model=ModelAdapter(),
    )

    trace = runner.run()

    output = Path("results/jingwen-config-verify")
    output.mkdir(parents=True, exist_ok=True)
    (output / "trace.json").write_text(
        json.dumps(asdict(trace), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Checker:")
    print(json.dumps(trace.checker, indent=2))
    print("Config result:")
    print(json.dumps(trace.results[0], indent=2))
    print("Trace saved to:", output / "trace.json")

    print("Verification:", trace.verification_events)
    print("Config results:", [
        r["content"] for r in trace.results if r["agent_id"] == "config"
    ])