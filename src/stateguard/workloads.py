"""Versioned deployment tasks and the knowledge material agents read.

Owned by the faults-and-evaluation workstream. A workload is reproducible only
when the task parameters AND the documentation the agents consult are both
pinned, so every run records a task version and a knowledge pack version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .experiment import build_pilot_tasks
from .workflow import DeploymentTask


@dataclass(frozen=True)
class KnowledgeItem:
    """One piece of documentation an agent may consult."""

    doc_id: str
    doc_version: str
    valid_as_of: str
    content: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "doc_version": self.doc_version,
            "valid_as_of": self.valid_as_of,
            "content": self.content,
        }


@dataclass(frozen=True)
class KnowledgePack:
    """The set of documents a run is allowed to read, pinned by version."""

    pack_version: str
    items: tuple[KnowledgeItem, ...]

    def get(self, doc_id: str) -> KnowledgeItem:
        for item in self.items:
            if item.doc_id == doc_id:
                return item
        raise KeyError(doc_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pack_version": self.pack_version,
            "items": [item.as_dict() for item in self.items],
        }


# The worker protocol document exists in two versions. The current one is what a
# correct Dependency Agent reads; the superseded one is the ground truth behind
# every "stale information" fault case.
WORKER_PROTOCOL_CURRENT = KnowledgeItem(
    doc_id="worker-protocol-support",
    doc_version="2.0",
    valid_as_of="2026-10-01",
    content={"supported_protocols": ["v2"], "deprecated_protocols": ["v1"]},
)

WORKER_PROTOCOL_SUPERSEDED = KnowledgeItem(
    doc_id="worker-protocol-support",
    doc_version="1.0",
    valid_as_of="2025-06-01",
    content={"supported_protocols": ["v1"], "deprecated_protocols": []},
)

RESOURCE_POLICY_CURRENT = KnowledgeItem(
    doc_id="resource-policy",
    doc_version="1.2",
    valid_as_of="2026-09-15",
    content={"cpu_units_per_replica": 1, "counts_api_and_worker": True},
)

CURRENT_KNOWLEDGE = KnowledgePack(
    pack_version="2026.10",
    items=(WORKER_PROTOCOL_CURRENT, RESOURCE_POLICY_CURRENT),
)

SUPERSEDED_KNOWLEDGE = KnowledgePack(
    pack_version="2025.06",
    items=(WORKER_PROTOCOL_SUPERSEDED, RESOURCE_POLICY_CURRENT),
)


@dataclass(frozen=True)
class VersionedTask:
    """A deployment task plus the exact material the agents are allowed to use."""

    task: DeploymentTask
    task_version: str
    knowledge: KnowledgePack
    notes: str = ""

    @property
    def task_id(self) -> str:
        return self.task.task_id

    def fingerprint(self) -> str:
        """Stable identifier for one reproducible workload configuration."""
        return f"{self.task_id}@{self.task_version}+kb{self.knowledge.pack_version}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_version": self.task_version,
            "fingerprint": self.fingerprint(),
            "knowledge": self.knowledge.as_dict(),
            "notes": self.notes,
            "parameters": {
                "target_api_image": self.task.target_api_image,
                "target_worker_image": self.task.target_worker_image,
                "database_port": self.task.database_port,
                "queue_protocol": self.task.queue_protocol,
                "cpu_budget": self.task.cpu_budget,
                "api_replicas": self.task.api_replicas,
                "worker_replicas": self.task.worker_replicas,
            },
        }


TASK_VERSION = "1.0"


def build_versioned_tasks() -> tuple[VersionedTask, ...]:
    """The pilot workloads, each pinned to a task version and knowledge pack."""
    return tuple(
        VersionedTask(
            task=task,
            task_version=TASK_VERSION,
            knowledge=CURRENT_KNOWLEDGE,
            notes="Phase 1 pilot workload variant.",
        )
        for task in build_pilot_tasks()
    )


def default_task() -> VersionedTask:
    """The single workload used for the paired clean/fault deliverable."""
    return build_versioned_tasks()[0]


def find_task(task_id: str) -> VersionedTask:
    for versioned in build_versioned_tasks():
        if versioned.task_id == task_id:
            return versioned
    raise KeyError(task_id)
