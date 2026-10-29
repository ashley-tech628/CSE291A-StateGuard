"""Shared Phase 1 contracts. Changes require review by all three owners."""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class AgentResult:
    run_id: str
    result_id: str
    agent_id: str
    parent_result_ids: tuple[str, ...]
    read_set: dict[str, int]
    content: dict[str, Any]
    status: Literal["ok", "error", "timeout"] = "ok"
    schema_version: int = 1
    tokens: int = 0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class ToolAction:
    run_id: str
    action_id: str
    operation: str
    args: dict[str, Any]
    expected_version: int | None
    parent_result_ids: tuple[str, ...]
    write_set: tuple[str, ...]
    outcome: Literal["committed", "rejected", "read_only"]
    effect_class: Literal["reversible", "compensatable", "irreversible"] = "reversible"


@dataclass(frozen=True)
class StateEvent:
    run_id: str
    key: str
    old_value: Any
    new_value: Any
    before_version: int | None
    after_version: int
    actor: str
    action_id: str
    sequence: int
    timestamp_utc: str


@dataclass(frozen=True)
class FaultSpec:
    target_result_id: str
    fault_type: Literal["incorrect", "stale", "timeout", "adversarial"]
    replacement_value: Any = None
    seed: int = 0


@dataclass(frozen=True)
class ExecutionTrace:
    run_id: str
    results: tuple[AgentResult, ...] = field(default_factory=tuple)
    actions: tuple[ToolAction, ...] = field(default_factory=tuple)
    events: tuple[StateEvent, ...] = field(default_factory=tuple)
