"""End-to-end recovery semantics across faults, external events, and retries."""

from pathlib import Path

from stateguard.experiment import run_scenario
from stateguard.fault_runner import run_paired
from stateguard.faults import get_case
from stateguard.metrics import paired_row
from stateguard.schemas import AgentResult
from stateguard.state import StateStore
from stateguard.workflow import DeploymentTask, ExternalUpdate, WorkflowRunner
from stateguard.workloads import default_task


def test_selective_recovery_recomputes_only_contaminated_results(tmp_path: Path):
    pair = run_paired(
        task=default_task(), case=get_case("incorrect-db-port-3306"),
        policy="selective_recovery", workdir=tmp_path,
    )
    decision = pair.fault.recovery_decision
    assert decision["status"] == "complete"
    assert decision["recomputed_agents"] == ["config", "planner"]
    assert decision["reused_agents"] == ["dependency", "resource"]
    assert pair.fault.check.success
    assert pair.fault.trace.final_state["api.db_port"] == 3306
    assert pair.fault.final_trace.final_state["api.db_port"] == 5432
    assert pair.fault.final_trace.final_state["worker.replicas"] == 3
    assert len(pair.fault.recovery_attempts[0].actions) == 1
    assert pair.fault.recovery_attempts[0].actions[0]["write_set"] == ("api.db_port",)
    assert pair.fault.trace.inference_calls == 4
    assert pair.fault.recovery_attempts[0].inference_calls == 2
    row = paired_row(pair)
    assert row["recovery_status"] == "complete"
    assert row["recomputed_stages"] == 2
    assert row["retained_results"] == 2
    assert row["inference_calls_fault"] == 6


def test_same_field_admin_write_blocks_selective_replay(tmp_path: Path):
    pair = run_paired(
        task=default_task(), case=get_case("incorrect-db-port-3306"),
        policy="selective_recovery", workdir=tmp_path,
        external_updates=(ExternalUpdate("api.db_port", 5432),),
    )
    decision = pair.fault.recovery_decision
    assert decision["status"] == "blocked"
    assert decision["assessment"]["conflicting_keys"] == ("api.db_port",)
    assert pair.fault.recovery_attempts[0].actions == []
    assert pair.fault.final_trace.final_state["api.db_port"] == 5432


def test_conditional_replay_rejects_a_write_after_its_snapshot_changed(tmp_path: Path):
    store = StateStore(tmp_path / "race.sqlite3")
    runner = WorkflowRunner(
        task=DeploymentTask(), fault="none", policy="selective_recovery",
        db_path=tmp_path / "race.sqlite3", attempt_id="recovery", seed=7,
    )
    try:
        runner._seed(store)
        expected = {"api.db_port": store.read("api.db_port").version}
        store.update(run_id="external", key="api.db_port", value=6432,
                     expected_version=0, actor="admin", action_id="admin-port")
        plan = AgentResult(
            run_id="recovery", result_id="plan", agent_id="planner",
            parent_result_ids=(), read_set={},
            content={"resource_ok": True,
                     "writes": [{"key": "api.db_port", "value": 5432}]},
        )
        runner._execute(store, plan, expected_versions=expected)
        assert runner.trace.execution_blocked == "version conflict on api.db_port"
        assert runner.trace.actions == []
        assert store.read("api.db_port").value == 6432
    finally:
        store.close()


def test_paired_full_restart_runs_second_attempt_and_counts_its_work(tmp_path: Path):
    pair = run_paired(
        task=default_task(), case=get_case("incorrect-db-port-3306"),
        policy="full_restart", workdir=tmp_path,
    )
    assert len(pair.fault.recovery_attempts) == 1
    assert pair.fault.trace.inference_calls == 4
    assert pair.fault.recovery_attempts[0].inference_calls == 4
    assert pair.fault.check.success
    assert pair.fault.final_trace.final_state["worker.replicas"] == 3
    assert (tmp_path / "fault-restart.sqlite3").exists()
    row = paired_row(pair)
    assert row["recovery_attempts"] == 1
    assert row["recomputed_stages"] == 4
    assert row["inference_calls_fault"] == 8


def test_full_restart_replays_multiple_recorded_external_events(tmp_path: Path):
    updates = (ExternalUpdate("worker.replicas", 3),
               ExternalUpdate("api.replicas", 4))
    row, trace = run_scenario(
        tmp_path, task=DeploymentTask(), fault="incorrect",
        policy="full_restart", seed=7, external_updates=updates,
    )
    assert row["success"]
    first, restarted = trace["attempts"]
    first_external = [(e["key"], e["new_value"]) for e in first["events"]
                      if e["actor"] == "admin"]
    replayed = [(e["key"], e["new_value"]) for e in restarted["events"]
                if e["actor"] == "admin"]
    assert first_external == replayed == [
        ("worker.replicas", 3), ("api.replicas", 4),
    ]
    assert restarted["final_state"]["worker.replicas"] == 3
    assert restarted["final_state"]["api.replicas"] == 4


def test_full_restart_reports_conflict_instead_of_overwriting_admin(tmp_path: Path):
    row, trace = run_scenario(
        tmp_path, task=DeploymentTask(), fault="incorrect",
        policy="full_restart", seed=7,
        external_updates=(ExternalUpdate("api.db_port", 5432),),
    )
    assert not row["success"]
    assert trace["attempts"][-1]["execution_blocked"] == (
        "external replay conflict on api.db_port"
    )
    assert trace["attempts"][-1]["final_state"]["api.db_port"] == 5432


def test_restart_replays_admin_event_even_when_fault_stopped_planner(tmp_path: Path):
    row, trace = run_scenario(
        tmp_path, task=DeploymentTask(), fault="timeout",
        policy="full_restart", seed=7,
        external_updates=(ExternalUpdate("api.replicas", 4),),
    )
    assert row["success"]
    first, restarted = trace["attempts"]
    assert not any(r["agent_id"] == "planner" for r in first["results"])
    assert first["events"][0]["key"] == "api.replicas"
    assert restarted["events"][-1]["key"] == "api.replicas"
    assert restarted["final_state"]["api.replicas"] == 4
