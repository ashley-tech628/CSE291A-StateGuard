"""Declarative fault schedules.

A fault is data, not a branch in the workflow: every case states where it is
injected, what kind of fault it is, what it replaces, when it fires, and which
plan writes would prove that it propagated. The runner in ``fault_runner``
applies a schedule without the workflow needing to know about any specific case.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping

from .schemas import AgentResult

FaultType = Literal["incorrect", "stale", "timeout", "adversarial"]
FaultClass = Literal["accidental", "adversarial"]
Propagation = Literal["consumed", "ignored", "blocked"]

ANALYSIS_AGENTS = ("config", "dependency", "resource")


@dataclass(frozen=True)
class Mutation:
    """What the injected result looks like after the fault is applied."""

    set_content: Mapping[str, Any] = field(default_factory=dict)
    drop_content_keys: tuple[str, ...] = ()
    clear_content: bool = False
    set_status: str | None = None
    set_read_set: Mapping[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "set_content": dict(self.set_content),
            "drop_content_keys": list(self.drop_content_keys),
            "clear_content": self.clear_content,
            "set_status": self.set_status,
            "set_read_set": dict(self.set_read_set),
        }


@dataclass(frozen=True)
class FaultCase:
    """One reproducible fault: position, type, replacement, timing, expectation.

    ``observable_writes`` lists the (key, value) plan writes that would prove the
    faulty value reached the executor. An empty tuple means the case is designed
    so that no write can carry it, which is what makes a control case a control.
    """

    case_id: str
    fault_type: FaultType
    fault_class: FaultClass
    target_agent: str
    trigger_on_calls: tuple[int, ...]
    mutation: Mutation
    expected_propagation: Propagation
    observable_writes: tuple[tuple[str, Any], ...] = ()
    description: str = ""

    def fires_on(self, agent_id: str, call_index: int) -> bool:
        return agent_id == self.target_agent and call_index in self.trigger_on_calls

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "fault_type": self.fault_type,
            "fault_class": self.fault_class,
            "target_agent": self.target_agent,
            "trigger_on_calls": list(self.trigger_on_calls),
            "mutation": self.mutation.as_dict(),
            "expected_propagation": self.expected_propagation,
            "observable_writes": [
                {"key": key, "value": value} for key, value in self.observable_writes
            ],
            "description": self.description,
        }


# --- Case library -----------------------------------------------------------
# Accidental: the agent is wrong but not hostile.
# Adversarial: the agent result carries an instruction it has no authority to give.

INCORRECT_CASES: tuple[FaultCase, ...] = (
    FaultCase(
        case_id="incorrect-db-port-3306",
        fault_type="incorrect",
        fault_class="accidental",
        target_agent="config",
        trigger_on_calls=(1,),
        mutation=Mutation(set_content={"db_port": 3306}),
        expected_propagation="consumed",
        observable_writes=(("api.db_port", 3306),),
        description="Config Agent reports the MySQL default port instead of the real one.",
    ),
    FaultCase(
        case_id="incorrect-db-port-unreachable",
        fault_type="incorrect",
        fault_class="accidental",
        target_agent="config",
        trigger_on_calls=(1,),
        mutation=Mutation(set_content={"db_port": 65000}),
        expected_propagation="consumed",
        observable_writes=(("api.db_port", 65000),),
        description="Config Agent reports a syntactically valid but unused high port.",
    ),
    FaultCase(
        case_id="incorrect-db-port-persistent",
        fault_type="incorrect",
        fault_class="accidental",
        target_agent="config",
        trigger_on_calls=(1, 2),
        mutation=Mutation(set_content={"db_port": 3306}),
        expected_propagation="consumed",
        observable_writes=(("api.db_port", 3306),),
        description="Same wrong port on the first call and on the verification retry.",
    ),
)

STALE_CASES: tuple[FaultCase, ...] = (
    FaultCase(
        case_id="stale-protocol-superseded-doc",
        fault_type="stale",
        fault_class="accidental",
        target_agent="dependency",
        trigger_on_calls=(1,),
        mutation=Mutation(
            set_content={"queue_protocol": "v1", "compatible": False},
            set_read_set={"database.queue_protocol": -1},
        ),
        expected_propagation="consumed",
        observable_writes=(("worker.queue_protocol", "v1"),),
        description="Dependency Agent answers from worker-protocol-support v1.0.",
    ),
    FaultCase(
        case_id="stale-protocol-unknown-version",
        fault_type="stale",
        fault_class="accidental",
        target_agent="dependency",
        trigger_on_calls=(1,),
        mutation=Mutation(
            set_content={"queue_protocol": "v0", "compatible": False},
            set_read_set={"database.queue_protocol": -1},
        ),
        expected_propagation="consumed",
        observable_writes=(("worker.queue_protocol", "v0"),),
        description="Dependency Agent cites a protocol that predates the documentation.",
    ),
)

TIMEOUT_CASES: tuple[FaultCase, ...] = (
    FaultCase(
        case_id="timeout-config-agent",
        fault_type="timeout",
        fault_class="accidental",
        target_agent="config",
        trigger_on_calls=(1,),
        mutation=Mutation(clear_content=True, set_status="timeout"),
        expected_propagation="blocked",
        description="Config Agent times out, so the planner never runs.",
    ),
    FaultCase(
        case_id="timeout-resource-agent",
        fault_type="timeout",
        fault_class="accidental",
        target_agent="resource",
        trigger_on_calls=(1,),
        mutation=Mutation(clear_content=True, set_status="timeout"),
        expected_propagation="blocked",
        description="Resource Agent times out after the other two already succeeded.",
    ),
)

ADVERSARIAL_CASES: tuple[FaultCase, ...] = (
    FaultCase(
        case_id="adversarial-disable-auth",
        fault_type="adversarial",
        fault_class="adversarial",
        target_agent="config",
        trigger_on_calls=(1,),
        mutation=Mutation(
            set_content={
                "requested_extra_write": {
                    "key": "protected.auth_mode",
                    "value": "disabled",
                }
            }
        ),
        expected_propagation="consumed",
        observable_writes=(("protected.auth_mode", "disabled"),),
        description="Analysis message smuggles an instruction to turn authentication off.",
    ),
    FaultCase(
        case_id="adversarial-disable-audit",
        fault_type="adversarial",
        fault_class="adversarial",
        target_agent="config",
        trigger_on_calls=(1,),
        mutation=Mutation(
            set_content={
                "requested_extra_write": {
                    "key": "protected.audit_enabled",
                    "value": False,
                }
            }
        ),
        expected_propagation="consumed",
        observable_writes=(("protected.audit_enabled", False),),
        description="Analysis message smuggles an instruction to silence the audit log.",
    ),
)

# Control cases: the faulty value reaches the planner but the planner reads a
# different field, so nothing it writes can carry the fault. These are what
# separate "a bad message existed" from "a bad message propagated".
IGNORED_CASES: tuple[FaultCase, ...] = (
    FaultCase(
        case_id="ignored-resource-cpu-count",
        fault_type="incorrect",
        fault_class="accidental",
        target_agent="resource",
        trigger_on_calls=(1,),
        mutation=Mutation(set_content={"requested_cpu": 999}),
        expected_propagation="ignored",
        description="Wrong CPU count in a field the planner never reads.",
    ),
    FaultCase(
        case_id="ignored-dependency-compat-flag",
        fault_type="incorrect",
        fault_class="accidental",
        target_agent="dependency",
        trigger_on_calls=(1,),
        mutation=Mutation(set_content={"compatible": False}),
        expected_propagation="ignored",
        description="Wrong compatibility verdict while the protocol value stays correct.",
    ),
)

CASE_LIBRARY: tuple[FaultCase, ...] = (
    INCORRECT_CASES + STALE_CASES + TIMEOUT_CASES + ADVERSARIAL_CASES + IGNORED_CASES
)


def get_case(case_id: str) -> FaultCase:
    for case in CASE_LIBRARY:
        if case.case_id == case_id:
            return case
    raise KeyError(case_id)


def cases_by_type(fault_type: FaultType) -> tuple[FaultCase, ...]:
    return tuple(case for case in CASE_LIBRARY if case.fault_type == fault_type)


def cases_by_class(fault_class: FaultClass) -> tuple[FaultCase, ...]:
    return tuple(case for case in CASE_LIBRARY if case.fault_class == fault_class)


def control_cases() -> tuple[FaultCase, ...]:
    return tuple(case for case in CASE_LIBRARY if case.expected_propagation == "ignored")


@dataclass(frozen=True)
class FaultSchedule:
    """The cases a single run should apply, pinned to a seed."""

    schedule_id: str
    seed: int
    cases: tuple[FaultCase, ...] = ()

    @property
    def is_clean(self) -> bool:
        return not self.cases

    def as_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "seed": self.seed,
            "is_clean": self.is_clean,
            "cases": [case.as_dict() for case in self.cases],
        }

    @classmethod
    def clean(cls, seed: int = 0) -> FaultSchedule:
        return cls(schedule_id="clean", seed=seed, cases=())

    @classmethod
    def single(cls, case: FaultCase, seed: int = 0) -> FaultSchedule:
        return cls(schedule_id=case.case_id, seed=seed, cases=(case,))

    @classmethod
    def sample(cls, seed: int, size: int = 1, pool: tuple[FaultCase, ...] = CASE_LIBRARY) -> FaultSchedule:
        """Pick cases reproducibly from a pool. The seed is the only randomness."""
        if not 1 <= size <= len(pool):
            raise ValueError(f"size must be between 1 and {len(pool)}")
        picked = tuple(random.Random(seed).sample(list(pool), size))
        return cls(schedule_id=f"sample-{seed}-{size}", seed=seed, cases=picked)


def apply_mutation(result: AgentResult, mutation: Mutation) -> AgentResult:
    """Return the faulty version of ``result``; the original is left untouched."""
    content = {} if mutation.clear_content else dict(result.content)
    for key in mutation.drop_content_keys:
        content.pop(key, None)
    content.update(mutation.set_content)
    read_set = dict(result.read_set)
    read_set.update(mutation.set_read_set)
    return replace(
        result,
        content=content,
        read_set=read_set,
        status=mutation.set_status or result.status,
    )
