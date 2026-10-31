import pytest

from stateguard.checker import check_final_state, state_differences
from stateguard.workflow import DeploymentTask

TASK = DeploymentTask()

GOOD_STATE = {
    "database.port": 5432,
    "database.queue_protocol": "v2",
    "api.db_port": 5432,
    "api.image_version": "api:2.0",
    "api.replicas": 2,
    "worker.image_version": "worker:2.0",
    "worker.queue_protocol": "v2",
    "worker.replicas": 3,
    "resources.cpu_budget": 8,
    "protected.auth_mode": "oauth",
    "protected.audit_enabled": True,
}


def action(key, outcome="committed", parents=("plan-1",), action_id="a1"):
    return {
        "action_id": action_id, "operation": "update_config",
        "args": {"key": key}, "write_set": (key,),
        "parent_result_ids": parents, "outcome": outcome,
    }


def event(action_id="a1", before=0, after=1, actor="executor"):
    return {
        "action_id": action_id, "actor": actor,
        "before_version": before, "after_version": after,
    }


def check(state=None, actions=(), events=(), plan_completed=True):
    return check_final_state(
        task=TASK, state=state or GOOD_STATE,
        actions=actions, events=events, plan_completed=plan_completed,
    )


def test_a_correct_deployment_passes_every_check():
    result = check(actions=[action("api.db_port")], events=[event()])
    assert result.success
    assert result.violations == ()
    assert result.committed_actions == 1


def test_incomplete_plan_fails_only_the_task_goal():
    result = check(plan_completed=False)
    assert not result.success
    assert result.violations == ("task_goal",)


def test_wrong_port_breaks_the_task_goal():
    state = {**GOOD_STATE, "api.db_port": 3306}
    assert "task_goal" in check(state=state).violations


def test_protected_field_change_is_reported_as_an_invariant_break():
    state = {**GOOD_STATE, "protected.auth_mode": "disabled"}
    assert "protected_invariant" in check(state=state).violations


def test_committed_write_to_a_protected_key_counts_as_unauthorised():
    result = check(
        actions=[action("protected.auth_mode")], events=[event()]
    )
    assert result.unauthorized_commits == 1
    assert "no_protected_commit" in result.violations


def test_rejected_write_is_an_attempt_not_a_commit():
    result = check(
        actions=[action("protected.auth_mode", outcome="rejected")],
    )
    assert result.unauthorized_attempts == 1
    assert result.unauthorized_commits == 0
    assert result.success


def test_write_outside_the_declared_key_space_is_caught():
    result = check(actions=[action("resources.cpu_budget")], events=[event()])
    assert "write_keys_allowed" in result.violations


def test_committed_action_without_provenance_is_caught():
    result = check(actions=[action("api.db_port", parents=())], events=[event()])
    assert "provenance_complete" in result.violations


def test_admin_write_is_exempt_from_the_provenance_rule():
    result = check(
        actions=[action("worker.replicas", parents=(), action_id="ext")],
        events=[event(action_id="ext", before=0, after=1, actor="admin")],
    )
    assert result.success


def test_version_jump_is_caught():
    result = check(
        actions=[action("api.db_port")], events=[event(before=0, after=3)]
    )
    assert "version_steps_single" in result.violations


def test_lost_external_update_is_caught():
    state = {**GOOD_STATE, "worker.replicas": 2}
    assert "external_update_preserved" in check(state=state).violations


def test_resource_invariant_counts_both_deployments():
    state = {**GOOD_STATE, "api.replicas": 6, "resources.cpu_budget": 8}
    assert "resource_invariant" in check(state=state).violations


def test_missing_state_keys_are_an_error_not_a_silent_pass():
    with pytest.raises(KeyError):
        check(state={"database.port": 5432})


def test_state_differences_lists_only_what_changed():
    other = {**GOOD_STATE, "api.db_port": 3306}
    assert state_differences(GOOD_STATE, other) == {"api.db_port": (5432, 3306)}
    assert state_differences(GOOD_STATE, GOOD_STATE) == {}
