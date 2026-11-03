"""Recovery boundary tests for durable provenance and conditional writes."""

from pathlib import Path

import pytest

from stateguard.fault_runner import run_paired
from stateguard.faults import get_case
from stateguard.provenance import build_provenance
from stateguard.recovery_assessment import assess_recovery
from stateguard.state import StateStore, VersionConflict
from stateguard.workloads import default_task


def test_fault_path_is_durable_and_excludes_independent_admin_write(tmp_path: Path):
    pair = run_paired(
        task=default_task(), case=get_case("incorrect-db-port-3306"),
        workdir=tmp_path, seed=7,
    )
    faulty_id = pair.fault.applied_cases[0]["result_id"]
    store = StateStore(tmp_path / "fault.sqlite3")
    try:
        durable = store.trace(pair.fault.trace.attempt_id)
        assert len(durable.results) == len(pair.fault.trace.results)
        assert len(durable.actions) == len(pair.fault.trace.actions)
        graph = build_provenance(durable)
    finally:
        store.close()

    assert graph.issues == ()
    impact = graph.impacted_by(faulty_id)
    assert faulty_id in impact.result_ids
    assert any("planner" in rid for rid in impact.result_ids)
    assert len(impact.action_ids) == 4
    assert all("external-worker-scale" not in aid for aid in impact.action_ids)
    assert "api.db_port@1" in impact.state_versions
    assert "worker.replicas@1" not in impact.state_versions


def test_stale_read_is_visible_as_unobserved_source(tmp_path: Path):
    pair = run_paired(
        task=default_task(), case=get_case("stale-protocol-superseded-doc"),
        workdir=tmp_path, seed=7,
    )
    graph = build_provenance(pair.fault.trace)
    assert any("database.queue_protocol@-1" in issue for issue in graph.issues)


def test_lost_ack_retry_cannot_overwrite_later_admin_update(tmp_path: Path):
    store = StateStore(tmp_path / "state.sqlite3")
    try:
        store.seed("api.db_port", 5431)
        request = dict(run_id="r", key="api.db_port", value=3306,
                       expected_version=0, actor="executor", action_id="write-1",
                       parent_result_ids=("faulty-plan",))
        _, first_event = store.update(**request)
        store.update(run_id="r", key="api.db_port", value=6432,
                     expected_version=1, actor="admin", action_id="admin-1")
        _, replayed_event = store.update(**request)
        assert replayed_event.sequence == first_event.sequence
        assert store.read("api.db_port").value == 6432
        assert store.read("api.db_port").version == 2
        assert len(store.trace("r").events) == 2
        with pytest.raises(VersionConflict):
            store.update(run_id="r", key="api.db_port", value=5432,
                         expected_version=1, actor="executor", action_id="new-write",
                         parent_result_ids=("replanned",))
    finally:
        store.close()


def test_recovery_preflight_preserves_valid_results_and_detects_same_key_conflict(
    tmp_path: Path,
):
    pair = run_paired(
        task=default_task(), case=get_case("incorrect-db-port-3306"),
        workdir=tmp_path, seed=7,
    )
    faulty_id = pair.fault.applied_cases[0]["result_id"]
    store = StateStore(tmp_path / "fault.sqlite3")
    try:
        trace = store.trace(pair.fault.trace.attempt_id)
        initial = assess_recovery(store=store, trace=trace, faulty_result_id=faulty_id)
        assert initial.preflight_passed
        assert any("planner" in rid for rid in initial.invalid_result_ids)
        assert {r.agent_id for r in trace.results
                if r.result_id in initial.reusable_result_ids} == {"dependency", "resource"}

        current = store.read("api.db_port")
        store.update(run_id=trace.run_id, key="api.db_port", value=6432,
                     expected_version=current.version, actor="admin", action_id="later-admin")
        after_admin = assess_recovery(store=store, trace=trace, faulty_result_id=faulty_id)
        assert after_admin.conflicting_keys == ("api.db_port",)
        assert not after_admin.preflight_passed
        assert "resource" in {r.agent_id for r in trace.results
                              if r.result_id in after_admin.reusable_result_ids}
    finally:
        store.close()
