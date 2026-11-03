import pytest

from stateguard.workloads import (
    CURRENT_KNOWLEDGE,
    SUPERSEDED_KNOWLEDGE,
    build_versioned_tasks,
    default_task,
    find_task,
)


def test_every_task_is_versioned_and_uniquely_fingerprinted():
    tasks = build_versioned_tasks()
    assert len(tasks) == 8
    assert all(task.task_version for task in tasks)
    assert len({task.fingerprint() for task in tasks}) == len(tasks)


def test_fingerprint_names_both_the_task_and_the_knowledge_version():
    task = default_task()
    assert task.task_version in task.fingerprint()
    assert task.knowledge.pack_version in task.fingerprint()


def test_superseded_pack_is_the_ground_truth_behind_stale_faults():
    current = CURRENT_KNOWLEDGE.get("worker-protocol-support")
    superseded = SUPERSEDED_KNOWLEDGE.get("worker-protocol-support")
    assert current.content["supported_protocols"] == ["v2"]
    assert superseded.content["supported_protocols"] == ["v1"]
    assert superseded.valid_as_of < current.valid_as_of


def test_workload_serialises_parameters_and_knowledge():
    payload = default_task().as_dict()
    assert payload["parameters"]["database_port"] == 5432
    assert payload["knowledge"]["items"][0]["doc_version"] == "2.0"


def test_find_task_rejects_unknown_ids():
    assert find_task("deploy-api-v2-03").task_id == "deploy-api-v2-03"
    with pytest.raises(KeyError):
        find_task("no-such-task")
