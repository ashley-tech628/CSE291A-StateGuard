import pytest

from stateguard.faults import (
    ANALYSIS_AGENTS,
    CASE_LIBRARY,
    FaultSchedule,
    Mutation,
    apply_mutation,
    cases_by_class,
    cases_by_type,
    control_cases,
    get_case,
)
from stateguard.schemas import AgentResult


def result(**overrides) -> AgentResult:
    base = dict(
        run_id="run", result_id="run-config-1", agent_id="config",
        parent_result_ids=(), read_set={"database.port": 0},
        content={"db_port": 5432}, status="ok",
    )
    base.update(overrides)
    return AgentResult(**base)


def test_case_ids_are_unique():
    ids = [case.case_id for case in CASE_LIBRARY]
    assert len(ids) == len(set(ids))


def test_library_covers_all_four_fault_types():
    for fault_type in ("incorrect", "stale", "timeout", "adversarial"):
        assert cases_by_type(fault_type), f"no case for {fault_type}"


def test_accidental_and_adversarial_are_both_represented_and_disjoint():
    accidental = set(c.case_id for c in cases_by_class("accidental"))
    adversarial = set(c.case_id for c in cases_by_class("adversarial"))
    assert accidental and adversarial
    assert not accidental & adversarial
    assert accidental | adversarial == {c.case_id for c in CASE_LIBRARY}


def test_every_case_targets_a_real_stage():
    for case in CASE_LIBRARY:
        assert case.target_agent in ANALYSIS_AGENTS + ("planner",)
        assert case.trigger_on_calls, f"{case.case_id} never fires"


def test_control_cases_declare_no_observable_write():
    controls = control_cases()
    assert len(controls) >= 1
    for case in controls:
        assert case.observable_writes == ()
        assert case.expected_propagation == "ignored"


def test_only_blocked_cases_omit_observable_writes_otherwise():
    for case in CASE_LIBRARY:
        if case.expected_propagation == "consumed":
            assert case.observable_writes, f"{case.case_id} claims to propagate silently"


def test_fires_on_respects_agent_and_call_index():
    case = get_case("incorrect-db-port-3306")
    assert case.fires_on("config", 1)
    assert not case.fires_on("config", 2)
    assert not case.fires_on("dependency", 1)


def test_persistent_case_fires_on_the_retry_too():
    case = get_case("incorrect-db-port-persistent")
    assert case.fires_on("config", 1) and case.fires_on("config", 2)


def test_apply_mutation_leaves_the_original_untouched():
    original = result()
    faulty = apply_mutation(original, Mutation(set_content={"db_port": 3306}))
    assert original.content == {"db_port": 5432}
    assert faulty.content == {"db_port": 3306}
    assert faulty.result_id == original.result_id


def test_apply_mutation_can_clear_content_and_set_status():
    faulty = apply_mutation(result(), Mutation(clear_content=True, set_status="timeout"))
    assert faulty.content == {}
    assert faulty.status == "timeout"


def test_apply_mutation_can_mark_the_read_set_stale():
    faulty = apply_mutation(result(), Mutation(set_read_set={"database.port": -1}))
    assert faulty.read_set == {"database.port": -1}


def test_apply_mutation_can_drop_a_field():
    faulty = apply_mutation(result(), Mutation(drop_content_keys=("db_port",)))
    assert faulty.content == {}


def test_schedule_sampling_is_reproducible_from_the_seed():
    first = FaultSchedule.sample(seed=7, size=3)
    again = FaultSchedule.sample(seed=7, size=3)
    other = FaultSchedule.sample(seed=8, size=3)
    assert [c.case_id for c in first.cases] == [c.case_id for c in again.cases]
    assert [c.case_id for c in first.cases] != [c.case_id for c in other.cases]


def test_schedule_sampling_rejects_impossible_sizes():
    with pytest.raises(ValueError):
        FaultSchedule.sample(seed=1, size=0)
    with pytest.raises(ValueError):
        FaultSchedule.sample(seed=1, size=len(CASE_LIBRARY) + 1)


def test_clean_schedule_is_empty_and_serialisable():
    schedule = FaultSchedule.clean(seed=7)
    assert schedule.is_clean
    assert schedule.as_dict()["cases"] == []


def test_single_schedule_round_trips_the_case_definition():
    payload = FaultSchedule.single(get_case("stale-protocol-superseded-doc"), seed=7).as_dict()
    case = payload["cases"][0]
    assert case["fault_type"] == "stale"
    assert case["mutation"]["set_read_set"] == {"database.queue_protocol": -1}
    assert case["observable_writes"] == [{"key": "worker.queue_protocol", "value": "v1"}]
