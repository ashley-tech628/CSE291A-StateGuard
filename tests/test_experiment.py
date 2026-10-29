import csv
import json
from pathlib import Path

import pytest

from stateguard.experiment import run_matrix, run_scenario
from stateguard.workflow import DeploymentTask


@pytest.mark.parametrize("fault", ["incorrect", "stale", "timeout"])
def test_no_recovery_exposes_accidental_failures(tmp_path: Path, fault: str):
    row, trace = run_scenario(
        tmp_path,
        task=DeploymentTask(),
        fault=fault,
        policy="no_recovery",
        seed=7,
    )
    assert row["success"] is False
    if fault == "timeout":
        assert row["fault_consumed"] is False
        assert trace["attempts"][0]["affected_stages"] == ["config"]
    else:
        assert row["fault_consumed"] is True
        assert row["affected_stages"] == 2


def test_adversarial_instruction_is_consumed_but_tool_layer_blocks_it(tmp_path: Path):
    row, trace = run_scenario(
        tmp_path,
        task=DeploymentTask(),
        fault="adversarial",
        policy="no_recovery",
        seed=7,
    )
    assert row["fault_consumed"] is True
    assert row["unauthorized_attempts"] == 1
    assert row["unauthorized_commits"] == 0
    assert trace["attempts"][0]["final_state"]["protected.auth_mode"] == "oauth"


@pytest.mark.parametrize("fault", ["incorrect", "stale", "timeout", "adversarial"])
def test_always_verify_prevents_fault_propagation(tmp_path: Path, fault: str):
    row, trace = run_scenario(
        tmp_path,
        task=DeploymentTask(),
        fault=fault,
        policy="always_verify",
        seed=7,
    )
    assert row["success"] is True
    assert row["fault_consumed"] is False
    assert row["restarts"] == 0
    assert row["verification_checks"] == 3
    assert any(
        event["valid"] is False
        for event in trace["attempts"][0]["verification_events"]
    )


@pytest.mark.parametrize("fault", ["incorrect", "stale", "timeout", "adversarial"])
def test_full_restart_recovers_and_replays_external_update(tmp_path: Path, fault: str):
    row, trace = run_scenario(
        tmp_path,
        task=DeploymentTask(),
        fault=fault,
        policy="full_restart",
        seed=7,
    )
    assert row["success"] is True
    assert row["restarts"] == 1
    assert row["external_update_preserved"] is True
    assert trace["attempts"][-1]["final_state"]["worker.replicas"] == 3


def test_complete_matrix_exports_machine_readable_artifacts(tmp_path: Path):
    rows = run_matrix(tmp_path / "pilot", seed=11)
    assert len(rows) == 120
    with (tmp_path / "pilot" / "summary.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        exported = list(csv.DictReader(handle))
    report = json.loads(
        (tmp_path / "pilot" / "report.json").read_text(encoding="utf-8")
    )
    assert len(exported) == 120
    assert report["matrix_rows"] == 120
    assert report["by_policy"]["always_verify"]["successful_fault_runs"] == 32
    assert report["by_policy"]["full_restart"]["successful_fault_runs"] == 32

def test_matrix_refuses_to_clean_unowned_directory(tmp_path: Path):
    unowned = tmp_path / "important"
    unowned.mkdir()
    (unowned / "keep.txt").write_text("user data", encoding="utf-8")
    with pytest.raises(ValueError, match="unowned output directory"):
        run_matrix(unowned, seed=7)
    assert (unowned / "keep.txt").read_text(encoding="utf-8") == "user data"
