"""Conservative preflight for state-aware selective replay.

This module decides what may be reused after a fault is identified. It does
not claim that recomputation or compensation has occurred; a replay executor
must still use conditional writes and run the final checker.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .provenance import build_provenance
from .schemas import ExecutionTrace
from .state import StateStore


@dataclass(frozen=True)
class RecoveryAssessment:
    faulty_result_id: str
    invalid_result_ids: tuple[str, ...]
    reusable_result_ids: tuple[str, ...]
    affected_action_ids: tuple[str, ...]
    conflicting_keys: tuple[str, ...]
    irreversible_action_ids: tuple[str, ...]
    provenance_issues: tuple[str, ...]
    preflight_passed: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_recovery(
    *, store: StateStore, trace: ExecutionTrace, faulty_result_id: str,
) -> RecoveryAssessment:
    """Inspect one attempt against the *current* SQLite state.

    Every result with an outdated or unobserved read is an additional invalid
    root. Descendants are invalidated even if their own read_set is unchanged.
    A later write to an affected field blocks automatic compensation; replay
    must re-read/re-plan rather than overwrite the newer value.
    """
    graph = build_provenance(trace)
    by_id = {result.result_id: result for result in trace.results}
    if faulty_result_id not in by_id:
        raise KeyError(faulty_result_id)

    invalid_roots = {faulty_result_id}
    for result in trace.results:
        if result.status != "ok":
            invalid_roots.add(result.result_id)
        if result.agent_id != "planner" and not result.read_set:
            invalid_roots.add(result.result_id)
        if any(parent not in by_id for parent in result.parent_result_ids):
            invalid_roots.add(result.result_id)
        for key, version in result.read_set.items():
            try:
                if version < 0 or store.read(key).version != version:
                    invalid_roots.add(result.result_id)
            except KeyError:
                invalid_roots.add(result.result_id)

    invalid: set[str] = set()
    actions: set[str] = set()
    events: set[int] = set()
    for root in invalid_roots:
        impact = graph.impacted_by(root)
        invalid.update(impact.result_ids)
        actions.update(impact.action_ids)
        events.update(impact.event_sequences)

    conflicting: set[str] = set()
    for event in trace.events:
        if event.sequence in events:
            try:
                if store.read(event.key).version != event.after_version:
                    conflicting.add(event.key)
            except KeyError:
                conflicting.add(event.key)

    irreversible = {
        action.action_id for action in trace.actions
        if action.action_id in actions and action.outcome == "committed"
        and action.effect_class == "irreversible"
    }
    # A fabricated or broken provenance link prevents a proof of safe reuse.
    # An unobserved read is handled by invalidating its result above.
    blocking_issues = tuple(issue for issue in graph.issues
                            if not issue.startswith("unobserved read version:"))
    reusable = tuple(sorted(
        rid for rid, result in by_id.items()
        if rid not in invalid and result.status == "ok"
    ))
    return RecoveryAssessment(
        faulty_result_id=faulty_result_id,
        invalid_result_ids=tuple(sorted(invalid)),
        reusable_result_ids=reusable,
        affected_action_ids=tuple(sorted(actions)),
        conflicting_keys=tuple(sorted(conflicting)),
        irreversible_action_ids=tuple(sorted(irreversible)),
        provenance_issues=graph.issues,
        preflight_passed=not (conflicting or blocking_issues),
    )
