"""State-aware selective replay against the original versioned SQLite store."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from .checker import CheckResult, check_final_state
from .recovery_assessment import RecoveryAssessment, assess_recovery
from .schemas import AgentResult
from .state import StateStore
from .workflow import AttemptTrace, DeploymentTask, WorkflowRunner


@dataclass(frozen=True)
class RecoveryResult:
    status: Literal["complete", "partial", "blocked"]
    reason: str | None
    assessment: RecoveryAssessment
    recomputed_agents: tuple[str, ...]
    reused_agents: tuple[str, ...]
    reused_from: dict[str, str]
    trace: AttemptTrace
    check: CheckResult

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "assessment": self.assessment.as_dict(),
            "recomputed_agents": list(self.recomputed_agents),
            "reused_agents": list(self.reused_agents),
            "reused_from": self.reused_from,
            "checker": self.check.as_dict(),
        }


def recover_selectively(
    *, task: DeploymentTask, db_path: Path, initial: AttemptTrace,
    faulty_result_id: str, model_adapter: Any = None,
) -> RecoveryResult:
    """Recompute invalid results and conditionally repair controlled state.

    A same-field later write, missing provenance, or irreversible action blocks
    automatic replay. This intentionally favors preserving external changes
    over forcing a task-successful final snapshot.
    """
    started = perf_counter()
    store = StateStore(db_path)
    recovery_id = f"{initial.attempt_id}-selective-recovery"
    runner = WorkflowRunner(
        task=task, fault="none", policy="selective_recovery", db_path=db_path,
        attempt_id=recovery_id, seed=0, model_adapter=model_adapter,
        external_updates=(),
    )
    runner._store = store
    recomputed: list[str] = []
    reused: list[str] = []
    reused_from: dict[str, str] = {}
    reason: str | None = None
    try:
        original = store.trace(initial.attempt_id)
        assessment = assess_recovery(
            store=store, trace=original, faulty_result_id=faulty_result_id,
        )
        if not assessment.preflight_passed:
            reason = (
                "recovery preflight blocked: "
                f"conflicts={assessment.conflicting_keys}, "
                f"irreversible={assessment.irreversible_action_ids}, "
                f"provenance={assessment.provenance_issues}"
            )
        else:
            # Capture versions before any model call. A concurrent write during
            # planning will fail the expected-version check in the tool layer.
            expected = {
                key: store.read(key).version for key in runner.ALLOWED_WRITE_KEYS
            }
            prior_by_agent = {
                result.agent_id: result for result in original.results
                if result.agent_id in ("config", "dependency", "resource")
            }
            analysis: dict[str, AgentResult] = {}
            for name in ("config", "dependency", "resource"):
                prior = prior_by_agent.get(name)
                if prior is not None and prior.result_id in assessment.reusable_result_ids:
                    copied = replace(
                        prior, run_id=recovery_id,
                        result_id=f"{recovery_id}-reused-{name}",
                        tokens=0, latency_ms=0.0,
                    )
                    analysis[name] = runner._record_result(copied)
                    reused.append(name)
                    reused_from[copied.result_id] = prior.result_id
                else:
                    if name == "config":
                        analysis[name] = runner._config_agent(store)
                    elif name == "dependency":
                        analysis[name] = runner._dependency_agent(store)
                    else:
                        analysis[name] = runner._resource_agent(store)
                    recomputed.append(name)
            if any(result.status != "ok" for result in analysis.values()):
                reason = "analysis recomputation did not produce valid results"
            else:
                plan = runner._plan(analysis)
                recomputed.append("planner")
                if plan.status != "ok":
                    reason = "planner recomputation failed"
                else:
                    runner._execute(
                        store, plan, expected_versions=expected, skip_equal=True,
                    )
                    reason = runner.trace.execution_blocked

        runner.trace.execution_blocked = reason
        runner._finish(store, started)
        check = check_final_state(
            task=task, state=runner.trace.final_state,
            actions=(*initial.actions, *runner.trace.actions),
            events=(*initial.events, *runner.trace.events),
            plan_completed=reason is None and any(
                item["agent_id"] == "planner" and item["status"] == "ok"
                for item in runner.trace.results
            ),
            execution_blocked=reason,
        )
        runner.trace.checker = check.as_dict()
        if not check.success:
            status = "blocked"
            reason = reason or "final task or safety checker failed"
        elif assessment.irreversible_action_ids:
            status = "partial"
            reason = "irreversible affected action remains"
        else:
            status = "complete"
        return RecoveryResult(
            status=status, reason=reason, assessment=assessment,
            recomputed_agents=tuple(recomputed), reused_agents=tuple(reused),
            reused_from=reused_from,
            trace=runner.trace, check=check,
        )
    finally:
        runner._store = None
        store.close()
