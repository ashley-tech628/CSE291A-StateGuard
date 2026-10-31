"""The deliverable: paired clean/fault runs and what they prove."""

import json

import pytest

from stateguard.fault_runner import run_paired, write_paired_artifacts
from stateguard.faults import CASE_LIBRARY, FaultSchedule, get_case
from stateguard.workloads import default_task

TASK = default_task()


def pair(tmp_path, case_id, policy="no_recovery", seed=7):
    return run_paired(
        task=TASK, case=get_case(case_id), policy=policy, seed=seed,
        workdir=tmp_path / case_id,
    )


def test_clean_run_succeeds_and_injects_nothing(tmp_path):
    result = pair(tmp_path, "incorrect-db-port-3306")
    assert result.clean.check.success
    assert result.clean.applied_cases == ()
    assert result.clean.schedule.is_clean
    assert result.clean.trace.fault_consumed is False


def test_clean_run_reaches_the_target_state(tmp_path):
    state = pair(tmp_path, "incorrect-db-port-3306").clean.trace.final_state
    assert state["api.db_port"] == state["database.port"]
    assert state["worker.queue_protocol"] == state["database.queue_protocol"]
    assert state["worker.replicas"] == 3


# --- Faults that really do propagate ---------------------------------------


def test_incorrect_fact_reaches_the_plan_and_the_final_state(tmp_path):
    result = pair(tmp_path, "incorrect-db-port-3306")
    comparison = result.comparison
    assert comparison["fault_exposed_to_planner"]
    assert comparison["fault_consumed"]
    assert comparison["propagation_verdict"] == "consumed"
    assert comparison["matching_writes"] == [{"key": "api.db_port", "value": 3306}]
    assert not comparison["plan_writes_identical"]
    assert comparison["state_differences"]["api.db_port"] == [5432, 3306]
    assert result.clean.check.success and not result.fault.check.success


def test_stale_information_is_traced_back_to_a_stale_read_version(tmp_path):
    result = pair(tmp_path, "stale-protocol-superseded-doc")
    dependency = next(
        r for r in result.fault.trace.results if r["agent_id"] == "dependency"
    )
    assert dependency["read_set"]["database.queue_protocol"] == -1
    assert result.comparison["propagation_verdict"] == "consumed"
    assert result.fault.trace.final_state["worker.queue_protocol"] == "v1"


def test_timeout_blocks_the_pipeline_before_the_planner(tmp_path):
    result = pair(tmp_path, "timeout-config-agent")
    assert result.comparison["propagation_verdict"] == "blocked"
    assert not result.comparison["fault_consumed"]
    assert result.fault.plan_writes == ()
    assert result.fault.trace.actions == []
    assert "config" in result.fault.trace.affected_stages


def test_timeout_later_in_the_pipeline_still_blocks(tmp_path):
    result = pair(tmp_path, "timeout-resource-agent")
    assert result.comparison["propagation_verdict"] == "blocked"
    assert "resource" in result.fault.trace.affected_stages


def test_adversarial_instruction_reaches_the_plan_but_is_rejected_at_the_tool_layer(tmp_path):
    result = pair(tmp_path, "adversarial-disable-auth")
    assert result.comparison["fault_consumed"]
    assert not result.comparison["plan_writes_identical"]
    # It got into the plan, yet nothing unauthorised was committed and the
    # final state is identical to the clean control.
    assert result.fault.check.unauthorized_attempts == 1
    assert result.fault.check.unauthorized_commits == 0
    assert result.comparison["final_state_identical"]
    assert result.fault.check.success


# --- The control case: exposed, but ignored --------------------------------


@pytest.mark.parametrize(
    "case_id", ["ignored-resource-cpu-count", "ignored-dependency-compat-flag"]
)
def test_ignored_message_is_exposed_to_the_planner_yet_does_not_propagate(tmp_path, case_id):
    result = pair(tmp_path, case_id)
    comparison = result.comparison

    # The faulty result was produced and handed to the planner...
    assert result.fault.applied_cases, "the case never fired"
    assert comparison["fault_exposed_to_planner"]

    # ...but the planner read a different field, so nothing carried it.
    assert not comparison["fault_consumed"]
    assert comparison["propagation_verdict"] == "ignored"
    assert comparison["plan_writes_identical"]
    assert comparison["final_state_identical"]
    assert comparison["ignored_without_propagation"]
    assert result.fault.check.success


def test_control_case_keeps_the_faulty_value_visible_in_the_trace(tmp_path):
    """Ignored is not the same as absent: the bad value is still on record."""
    result = pair(tmp_path, "ignored-resource-cpu-count")
    resource = next(
        r for r in result.fault.trace.results if r["agent_id"] == "resource"
    )
    assert resource["content"]["requested_cpu"] == 999
    assert resource["content"]["within_budget"] is True
    assert result.fault.trace.fault_evidence[0]["matching_writes"] == []


# --- The whole library ------------------------------------------------------


@pytest.mark.parametrize("case", CASE_LIBRARY, ids=lambda c: c.case_id)
def test_every_case_behaves_as_its_schedule_declares(tmp_path, case):
    result = run_paired(
        task=TASK, case=case, policy="no_recovery", seed=7, workdir=tmp_path / case.case_id
    )
    assert result.comparison["matches_expectation"], (
        f"{case.case_id}: expected {case.expected_propagation}, "
        f"observed {result.comparison['propagation_verdict']}"
    )
    assert result.clean.check.success, "the control run must always succeed"


def test_no_case_ever_commits_an_unauthorised_write(tmp_path):
    for case in CASE_LIBRARY:
        result = run_paired(
            task=TASK, case=case, policy="no_recovery", seed=7,
            workdir=tmp_path / case.case_id,
        )
        assert result.fault.check.unauthorized_commits == 0, case.case_id


# --- Timing and policy interaction -----------------------------------------


def test_verification_retry_clears_a_single_shot_fault(tmp_path):
    result = pair(tmp_path, "incorrect-db-port-3306", policy="always_verify")
    assert result.fault.check.success
    assert result.comparison["propagation_verdict"] == "ignored"


def test_a_fault_that_also_fires_on_the_retry_survives_verification(tmp_path):
    result = pair(tmp_path, "incorrect-db-port-persistent", policy="always_verify")
    assert not result.fault.check.success
    assert result.fault.trace.verification_events


# --- Artifacts --------------------------------------------------------------


def test_paired_run_writes_two_complete_traces_and_a_comparison(tmp_path):
    result = pair(tmp_path, "incorrect-db-port-3306")
    workdir = tmp_path / "artifacts"
    write_paired_artifacts(result, workdir)

    clean = json.loads((workdir / "clean-trace.json").read_text(encoding="utf-8"))
    fault = json.loads((workdir / "fault-trace.json").read_text(encoding="utf-8"))
    paired = json.loads((workdir / "paired.json").read_text(encoding="utf-8"))

    for payload in (clean, fault):
        assert payload["trace"]["results"]
        assert payload["trace"]["final_state"]
        assert "checker" in payload
    assert fault["applied_cases"][0]["case_id"] == "incorrect-db-port-3306"
    assert paired["workload"]["task_version"]
    assert paired["comparison"]["propagation_verdict"] == "consumed"


def test_schedule_with_two_cases_applies_both(tmp_path):
    from stateguard.fault_runner import run_attempt

    schedule = FaultSchedule(
        schedule_id="two",
        seed=7,
        cases=(get_case("incorrect-db-port-3306"), get_case("ignored-resource-cpu-count")),
    )
    outcome = run_attempt(
        task=TASK, schedule=schedule, policy="no_recovery", seed=7,
        db_path=tmp_path / "two.sqlite3", attempt_id="two", label="fault",
    )
    assert len(outcome.applied_cases) == 2
    assert outcome.verdict == "consumed"
