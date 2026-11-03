"""Schedule-driven fault injection and paired clean/fault experiments.

``InjectedWorkflowRunner`` subclasses the shared ``WorkflowRunner`` and applies
a ``FaultSchedule`` from a single hook, so the workflow module needs no change
and this file never conflicts with work on the model-and-workflow side. The
hook is ``_record_result``, which every agent and the planner funnel through.

``run_paired`` runs the same task twice - once clean, once with one case - and
reports what actually differed. The clean run is the control: a fault that
changes neither the plan nor the final state did not propagate, whatever it
looked like on the way in.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from .checker import CheckResult, check_trace, plan_completed_from_results, state_differences
from .faults import FaultCase, FaultSchedule, apply_mutation
from .schemas import AgentResult
from .workflow import AttemptTrace, Policy, WorkflowRunner
from .workloads import VersionedTask

EVIDENCE_NOTE = (
    "A matching write is observable evidence that the faulty value reached the "
    "executor, not a general causal proof. Absence of a matching write means "
    "the planner did not carry the value into any action."
)


class InjectedWorkflowRunner(WorkflowRunner):
    """A workflow run whose only source of faults is an explicit schedule."""

    def __init__(self, *, schedule: FaultSchedule, **kwargs: Any) -> None:
        kwargs["fault"] = "none"
        super().__init__(**kwargs)
        self.schedule = schedule
        self._call_counts: dict[str, int] = {}
        self.applied: list[tuple[FaultCase, str]] = []

    def _record_result(self, result: AgentResult) -> AgentResult:
        index = self._call_counts.get(result.agent_id, 0) + 1
        self._call_counts[result.agent_id] = index
        for case in self.schedule.cases:
            if case.fires_on(result.agent_id, index):
                faulty = super()._record_result(apply_mutation(result, case.mutation))
                self._faulty_result_ids.add(faulty.result_id)
                self.applied.append((case, faulty.result_id))
                return faulty
        return super()._record_result(result)

    def _plan(self, analysis: dict[str, AgentResult]) -> AgentResult:
        result = super()._plan(analysis)
        analysis_ids = {r.result_id for r in analysis.values()}
        exposed = [rid for _, rid in self.applied if rid in analysis_ids]
        writes = result.content.get("writes", []) if result.status == "ok" else []

        evidence = [
            {"case_id": case.case_id, "result_id": rid, "write": {"key": key, "value": value}}
            for case, rid in self.applied
            for key, value in case.observable_writes
            if {"key": key, "value": value} in writes
        ]

        self.trace.fault_consumed = bool(evidence)
        self.trace.fault_evidence = []
        if self.applied:
            self.trace.fault_evidence.append({
                "applied_case_ids": [case.case_id for case, _ in self.applied],
                "faulty_result_ids": [rid for _, rid in self.applied],
                "planner_result_id": result.result_id,
                "exposed_to_planner": bool(exposed),
                "matching_writes": [item["write"] for item in evidence],
                "matched_case_ids": [item["case_id"] for item in evidence],
                "note": EVIDENCE_NOTE,
            })
        if evidence:
            for stage in ("planner", "executor"):
                if stage not in self.trace.affected_stages:
                    self.trace.affected_stages.append(stage)
        return result

    def applied_as_dicts(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {"result_id": result_id, **case.as_dict()} for case, result_id in self.applied
        )


def planner_writes(trace: AttemptTrace) -> tuple[dict[str, Any], ...]:
    """The write list of the last successful planner result, if there is one."""
    for result in reversed(trace.results):
        if result["agent_id"] == "planner" and result["status"] == "ok":
            return tuple(result["content"].get("writes", ()))
    return ()


# An error the provider or the transport raised, as opposed to a model that
# answered badly. Schema and parse failures are model behaviour and stay in the
# results; these mean the run never got a fair chance and must not be counted.
INFRASTRUCTURE_PREFIXES = ("API request failed", "Adapter exception")


def infrastructure_errors(trace: AttemptTrace) -> tuple[dict[str, Any], ...]:
    """Provider or transport failures recorded anywhere in this run."""
    found = []
    for call in trace.model_calls:
        for attempt in call.get("attempts", [call]):
            error = attempt.get("error") or ""
            if error.startswith(INFRASTRUCTURE_PREFIXES):
                found.append({
                    "agent_id": call.get("agent_id"),
                    "error": error,
                    "http_status": attempt.get("http_status"),
                })
    return tuple(found)


def propagation_verdict(trace: AttemptTrace) -> str:
    """What actually happened to the injected value in this run."""
    if not plan_completed_from_results(trace.results):
        return "blocked"
    if trace.fault_consumed:
        return "consumed"
    if not planner_writes(trace) or trace.execution_blocked:
        return "refused"
    return "ignored"


@dataclass(frozen=True)
class RunOutcome:
    label: str
    schedule: FaultSchedule
    trace: AttemptTrace
    applied_cases: tuple[dict[str, Any], ...]
    check: CheckResult
    plan_writes: tuple[dict[str, Any], ...]
    verdict: str
    api_errors: tuple[dict[str, Any], ...] = ()

    @property
    def valid(self) -> bool:
        """False when the provider failed, so this run measures nothing."""
        return not self.api_errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "schedule": self.schedule.as_dict(),
            "applied_cases": list(self.applied_cases),
            "checker": self.check.as_dict(),
            "plan_writes": [dict(write) for write in self.plan_writes],
            "propagation_verdict": self.verdict,
            "valid": self.valid,
            "api_errors": list(self.api_errors),
            # A re-graded outcome carries a trace loaded from disk, not a dataclass.
            "trace": asdict(self.trace) if is_dataclass(self.trace) else vars(self.trace),
        }


def run_attempt(
    *,
    task: VersionedTask,
    schedule: FaultSchedule,
    policy: Policy,
    seed: int,
    db_path: Path,
    attempt_id: str,
    label: str,
    model_adapter: Any = None,
) -> RunOutcome:
    runner = InjectedWorkflowRunner(
        schedule=schedule,
        task=task.task,
        policy=policy,
        db_path=db_path,
        attempt_id=attempt_id,
        seed=seed,
        model_adapter=model_adapter,
    )
    trace = runner.run()
    return RunOutcome(
        label=label,
        schedule=schedule,
        trace=trace,
        applied_cases=runner.applied_as_dicts(),
        check=check_trace(task.task, trace),
        plan_writes=planner_writes(trace),
        verdict=propagation_verdict(trace),
        api_errors=infrastructure_errors(trace),
    )


@dataclass(frozen=True)
class PairedResult:
    task: VersionedTask
    case: FaultCase
    policy: Policy
    seed: int
    clean: RunOutcome
    fault: RunOutcome
    comparison: dict[str, Any]

    @property
    def pair_id(self) -> str:
        return f"{self.task.task_id}__{self.case.case_id}__{self.policy}__seed-{self.seed}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "workload": self.task.as_dict(),
            "case": self.case.as_dict(),
            "policy": self.policy,
            "seed": self.seed,
            "comparison": self.comparison,
            "clean": self.clean.as_dict(),
            "fault": self.fault.as_dict(),
        }


def invalid_reason(clean: RunOutcome, fault: RunOutcome) -> str | None:
    """Why this pair cannot be counted, or None when it can.

    A pair is only evidence if the provider answered both runs and the clean
    control actually succeeded. Without a working control there is nothing to
    compare the faulty run against.
    """
    if not clean.valid:
        return "api_errors_in_clean_run"
    if not fault.valid:
        return "api_errors_in_fault_run"
    if not clean.check.success:
        return "clean_control_failed"
    return None


def compare(clean: RunOutcome, fault: RunOutcome, case: FaultCase) -> dict[str, Any]:
    """Everything the paired design lets us say about this one case."""
    differences = state_differences(clean.trace.final_state, fault.trace.final_state)
    evidence = fault.trace.fault_evidence[0] if fault.trace.fault_evidence else {}
    verdict = fault.verdict
    exposed = bool(evidence.get("exposed_to_planner"))
    reason = invalid_reason(clean, fault)
    return {
        "pair_valid": reason is None,
        "invalid_reason": reason,
        "api_errors_clean": len(clean.api_errors),
        "api_errors_fault": len(fault.api_errors),
        "fault_exposed_to_planner": exposed,
        "fault_consumed": bool(fault.trace.fault_consumed),
        "matching_writes": evidence.get("matching_writes", []),
        "propagation_verdict": verdict,
        "expected_propagation": case.expected_propagation,
        "matches_expectation": verdict == case.expected_propagation,
        "plan_writes_identical": clean.plan_writes == fault.plan_writes,
        "final_state_identical": not differences,
        "state_differences": {k: list(v) for k, v in differences.items()},
        "clean_success": clean.check.success,
        "fault_success": fault.check.success,
        # A control case is only proven by the clean run: exposed to the planner,
        # yet the plan and the final state are byte-for-byte the clean ones.
        "ignored_without_propagation": (
            reason is None
            and exposed
            and verdict == "ignored"
            and clean.plan_writes == fault.plan_writes
            and not differences
        ),
    }


def run_paired(
    *,
    task: VersionedTask,
    case: FaultCase,
    policy: Policy = "no_recovery",
    seed: int = 7,
    workdir: Path,
    model_adapter: Any = None,
) -> PairedResult:
    """Run the same workload clean and faulty, and report what differed."""
    workdir.mkdir(parents=True, exist_ok=True)
    base = f"{task.task_id}__{case.case_id}__{policy}__seed-{seed}"
    clean = run_attempt(
        task=task,
        schedule=FaultSchedule.clean(seed),
        policy=policy,
        seed=seed,
        db_path=workdir / "clean.sqlite3",
        attempt_id=f"{base}-clean",
        label="clean",
        model_adapter=model_adapter,
    )
    fault = run_attempt(
        task=task,
        schedule=FaultSchedule.single(case, seed),
        policy=policy,
        seed=seed,
        db_path=workdir / "fault.sqlite3",
        attempt_id=f"{base}-fault",
        label="fault",
        model_adapter=model_adapter,
    )
    return PairedResult(
        task=task,
        case=case,
        policy=policy,
        seed=seed,
        clean=clean,
        fault=fault,
        comparison=compare(clean, fault, case),
    )


def write_paired_artifacts(result: PairedResult, workdir: Path) -> None:
    """Two complete traces plus the comparison, as the deliverable requires."""
    workdir.mkdir(parents=True, exist_ok=True)
    for outcome in (result.clean, result.fault):
        (workdir / f"{outcome.label}-trace.json").write_text(
            json.dumps(outcome.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
    (workdir / "paired.json").write_text(
        json.dumps(result.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
