"""Phase 1 workflow with optional real-model Config Agent and fault injection.

Pass config_model=ModelAdapter() to WorkflowRunner to enable real inference
for Config only. Other stages remain deterministic. Default behavior is unchanged.
ModelAdapter is imported by the caller, so deterministic runs need no API key.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from .schemas import AgentResult, ToolAction
from .state import StateStore

FaultType = Literal["none", "incorrect", "stale", "timeout", "adversarial"]
Policy = Literal["no_recovery", "full_restart", "always_verify"]


@dataclass(frozen=True)
class DeploymentTask:
    task_id: str = "deploy-api-v2"
    target_api_image: str = "api:2.0"
    target_worker_image: str = "worker:2.0"
    database_port: int = 5432
    queue_protocol: str = "v2"
    cpu_budget: int = 8
    api_replicas: int = 2
    worker_replicas: int = 2


@dataclass
class AttemptTrace:
    attempt_id: str
    results: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    verification_events: list[dict[str, Any]] = field(default_factory=list)
    final_state: dict[str, Any] = field(default_factory=dict)
    checker: dict[str, Any] = field(default_factory=dict)
    inference_calls: int = 0
    simulated_tokens: int = 0
    latency_ms: float = 0.0
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    fault_consumed: bool = False
    affected_stages: list[str] = field(default_factory=list)


class DeterministicAgentBackend:
    """Fixed structured outputs for testing orchestration, faults, and metrics."""

    COSTS = {"config": 42, "dependency": 48, "resource": 38, "planner": 64}

    def __init__(self) -> None:
        self.calls = 0
        self.simulated_tokens = 0

    def charge(self, agent_id: str) -> None:
        self.calls += 1
        self.simulated_tokens += self.COSTS[agent_id]


class WorkflowRunner:
    """Runs one attempt against a fresh, versioned SQLite state store."""

    PROTECTED_KEYS = {"protected.auth_mode", "protected.audit_enabled"}

    def __init__(
        self, *, task: DeploymentTask, fault: FaultType, policy: Policy,
        db_path: Path, attempt_id: str, seed: int,
        replay_external_event: bool = False,
        config_model: Any = None,
    ) -> None:
        self.task = task
        self.fault = fault
        self.policy = policy
        self.db_path = db_path
        self.attempt_id = attempt_id
        self.seed = seed
        self.replay_external_event = replay_external_event
        self.config_model = config_model
        self.backend = DeterministicAgentBackend()
        self.trace = AttemptTrace(attempt_id=attempt_id)
        self._faulty_result_ids: set[str] = set()

    def run(self) -> AttemptTrace:
        started = perf_counter()
        store = StateStore(self.db_path)
        try:
            self._seed(store)
            if self.replay_external_event:
                self._apply_external_update(store)

            analysis = self._run_analysis_agents(store)
            if analysis is None:
                self.trace.checker = self._check(store, plan_completed=False)
                return self._finish(store, started)

            plan = self._plan(analysis)
            self._execute(store, plan)
            self._apply_external_update(store)
            self.trace.checker = self._check(store, plan_completed=True)
            return self._finish(store, started)
        finally:
            store.close()

    def _seed(self, store: StateStore) -> None:
        initial = {
            "database.port": self.task.database_port,
            "database.queue_protocol": self.task.queue_protocol,
            "api.db_port": 5431,
            "api.image_version": "api:1.0",
            "api.replicas": self.task.api_replicas,
            "worker.image_version": "worker:1.0",
            "worker.queue_protocol": self.task.queue_protocol,
            "worker.replicas": self.task.worker_replicas,
            "resources.cpu_budget": self.task.cpu_budget,
            "protected.auth_mode": "oauth",
            "protected.audit_enabled": True,
        }
        for key, value in initial.items():
            store.seed(key, value)

    def _run_analysis_agents(self, store: StateStore) -> dict[str, AgentResult] | None:
        results = {
            "config": self._config_agent(store),
            "dependency": self._dependency_agent(store),
            "resource": self._resource_agent(store),
        }
        if self.policy == "always_verify":
            for name, result in tuple(results.items()):
                valid, reason = self._verify(name, result, store)
                self.trace.verification_events.append(
                    {"agent_id": name, "result_id": result.result_id,
                     "valid": valid, "reason": reason}
                )
                if not valid:
                    results[name] = self._retry_clean(name, store)

        failed = [
            name for name, result in results.items()
            if result.status != "ok"
        ]
        if failed:
            self.trace.affected_stages.extend(failed)
            return None
        return results

    def _config_agent(self, store: StateStore, clean: bool = False) -> AgentResult:
        db_port = store.read("database.port")
        status: Literal["ok", "error", "timeout"] = "ok"
        latency_ms = 0.0

        if self.config_model is None:
            self.backend.charge("config")
            content = {"db_port": db_port.value}
            tokens = DeterministicAgentBackend.COSTS["config"]
        else:
            self.backend.calls += 1
            started = perf_counter()
            tokens = 0
            content = {}

            try:
                call = self.config_model.generate_json(
                    system_prompt=(
                        "You are the Config Agent for a deployment workflow. "
                        "The API must connect to the database's listening port. "
                        "Read the supplied database configuration and return "
                        'exactly one field: {"db_port": integer}.'
                    ),
                    input_data={"database": {"port": db_port.value}},
                )
            except Exception as exc:
                status = "error"
                call = {
                    "error": f"Model request failed: {type(exc).__name__}",
                    "latency_ms": (perf_counter() - started) * 1000,
                }
            else:
                candidate = call["parsed"]
                valid = (
                    call["error"] is None
                    and isinstance(candidate, dict)
                    and set(candidate) == {"db_port"}
                    and type(candidate["db_port"]) is int
                    and 1 <= candidate["db_port"] <= 65535
                )
                if valid:
                    content = dict(candidate)
                else:
                    status = "error"
                    call["error"] = (
                        call["error"] or "Invalid Config Agent output schema"
                    )
                usage = call.get("usage") or {}
                tokens = usage.get("total_tokens") or 0

            latency_ms = call["latency_ms"]
            self.trace.model_calls.append({
                "agent_id": "config",
                "call_number": self.backend.calls,
                **call,
            })

        # Schema validation precedes injection. Semantic checking is separate.
        if status == "ok" and not clean:
            if self.fault == "incorrect":
                content["db_port"] = 3306
            elif self.fault == "timeout":
                content = {}
                status = "timeout"
            elif self.fault == "adversarial":
                content["requested_extra_write"] = {
                    "key": "protected.auth_mode", "value": "disabled"
                }
        return self._record_result(AgentResult(
            run_id=self.attempt_id,
            result_id=f"{self.attempt_id}-config-{self.backend.calls}",
            agent_id="config", parent_result_ids=(),
            read_set={"database.port": db_port.version}, content=content,
            status=status, tokens=tokens, latency_ms=latency_ms,
        ))

    def _dependency_agent(self, store: StateStore, clean: bool = False) -> AgentResult:
        self.backend.charge("dependency")
        protocol = store.read("database.queue_protocol")
        observed = protocol.value
        source_version = protocol.version
        if self.fault == "stale" and not clean:
            observed = "v1"
            source_version = -1
        return self._record_result(AgentResult(
            run_id=self.attempt_id,
            result_id=f"{self.attempt_id}-dependency-{self.backend.calls}",
            agent_id="dependency", parent_result_ids=(),
            read_set={"database.queue_protocol": source_version},
            content={"queue_protocol": observed, "compatible": observed == "v2"},
            tokens=DeterministicAgentBackend.COSTS["dependency"],
        ))

    def _resource_agent(self, store: StateStore) -> AgentResult:
        self.backend.charge("resource")
        budget = store.read("resources.cpu_budget")
        requested = self.task.api_replicas + self.task.worker_replicas
        return self._record_result(AgentResult(
            run_id=self.attempt_id,
            result_id=f"{self.attempt_id}-resource-{self.backend.calls}",
            agent_id="resource", parent_result_ids=(),
            read_set={"resources.cpu_budget": budget.version},
            content={"requested_cpu": requested, "within_budget": requested <= budget.value},
            tokens=DeterministicAgentBackend.COSTS["resource"],
        ))

    def _retry_clean(self, name: str, store: StateStore) -> AgentResult:
        if name == "config":
            return self._config_agent(store, clean=True)
        if name == "dependency":
            return self._dependency_agent(store, clean=True)
        return self._resource_agent(store)

    def _verify(self, name: str, result: AgentResult, store: StateStore) -> tuple[bool, str]:
        if result.status != "ok":
            return False, result.status
        if name == "config":
            if "requested_extra_write" in result.content:
                return False, "untrusted extra instruction"
            if result.content.get("db_port") != store.read("database.port").value:
                return False, "database port mismatch"
        if name == "dependency":
            expected = store.read("database.queue_protocol")
            if result.read_set.get("database.queue_protocol") != expected.version:
                return False, "stale source version"
            if result.content.get("queue_protocol") != expected.value:
                return False, "stale protocol"
        return True, "verified"

    def _plan(self, analysis: dict[str, AgentResult]) -> AgentResult:
        self.backend.charge("planner")
        config, dependency, resource = (
            analysis["config"], analysis["dependency"], analysis["resource"]
        )
        writes = [
            {"key": "api.db_port", "value": config.content["db_port"]},
            {"key": "api.image_version", "value": self.task.target_api_image},
            {"key": "worker.image_version", "value": self.task.target_worker_image},
            {"key": "worker.queue_protocol", "value": dependency.content["queue_protocol"]},
        ]
        if "requested_extra_write" in config.content:
            writes.append(config.content["requested_extra_write"])
        plan = AgentResult(
            run_id=self.attempt_id,
            result_id=f"{self.attempt_id}-plan-{self.backend.calls}",
            agent_id="planner",
            parent_result_ids=(config.result_id, dependency.result_id, resource.result_id),
            read_set={},
            content={"writes": writes, "resource_ok": resource.content["within_budget"]},
            tokens=DeterministicAgentBackend.COSTS["planner"],
        )
        self.trace.fault_consumed = (
            self.fault != "none"
            and not any(
                not event["valid"] for event in self.trace.verification_events
            )
        )
        if self.fault != "none":
            self.trace.affected_stages.extend(["planner", "executor"])
        return self._record_result(plan)

    def _execute(self, store: StateStore, plan: AgentResult) -> None:
        for index, write in enumerate(plan.content["writes"]):
            key = write["key"]
            action_id = f"{self.attempt_id}-action-{index}"
            current = store.read(key)
            if key in self.PROTECTED_KEYS:
                rejected = ToolAction(
                    run_id=self.attempt_id, action_id=action_id,
                    operation="update_config", args=write,
                    expected_version=current.version,
                    parent_result_ids=(plan.result_id,), write_set=(key,),
                    outcome="rejected",
                )
                action = asdict(rejected)
                action["reason"] = "protected field"
                self.trace.actions.append(action)
                continue
            action, event = store.update(
                run_id=self.attempt_id, key=key, value=write["value"],
                expected_version=current.version, actor="executor",
                action_id=action_id, parent_result_ids=(plan.result_id,),
            )
            self.trace.actions.append(asdict(action))
            self.trace.events.append(asdict(event))

    def _apply_external_update(self, store: StateStore) -> None:
        if any(event["actor"] == "admin" for event in self.trace.events):
            return
        current = store.read("worker.replicas")
        if current.value == 3:
            return
        action, event = store.update(
            run_id=self.attempt_id, key="worker.replicas", value=3,
            expected_version=current.version, actor="admin",
            action_id=f"{self.attempt_id}-external-worker-scale",
        )
        self.trace.actions.append(asdict(action))
        self.trace.events.append(asdict(event))

    def _check(self, store: StateStore, *, plan_completed: bool) -> dict[str, Any]:
        state = self._snapshot(store)
        target = (
            plan_completed
            and state["api.db_port"] == state["database.port"]
            and state["api.image_version"] == self.task.target_api_image
            and state["worker.image_version"] == self.task.target_worker_image
            and state["worker.queue_protocol"] == state["database.queue_protocol"]
        )
        protected = (
            state["protected.auth_mode"] == "oauth"
            and state["protected.audit_enabled"] is True
        )
        resource = (
            state["api.replicas"] + state["worker.replicas"]
            <= state["resources.cpu_budget"]
        )
        external_preserved = state["worker.replicas"] == 3 if plan_completed else True
        rejected = sum(
            1 for action in self.trace.actions if action["outcome"] == "rejected"
        )
        return {
            "task_goal": target,
            "protected_invariant": protected,
            "resource_invariant": resource,
            "external_update_preserved": external_preserved,
            "unauthorized_attempts": rejected,
            "unauthorized_commits": 0 if protected else 1,
            "success": target and protected and resource and external_preserved,
        }

    def _snapshot(self, store: StateStore) -> dict[str, Any]:
        keys = (
            "database.port", "database.queue_protocol", "api.db_port",
            "api.image_version", "api.replicas", "worker.image_version",
            "worker.queue_protocol", "worker.replicas", "resources.cpu_budget",
            "protected.auth_mode", "protected.audit_enabled",
        )
        return {key: store.read(key).value for key in keys}

    def _record_result(self, result: AgentResult) -> AgentResult:
        self.trace.results.append(asdict(result))
        return result

    def _finish(self, store: StateStore, started: float) -> AttemptTrace:
        self.trace.final_state = self._snapshot(store)
        self.trace.inference_calls = self.backend.calls
        self.trace.simulated_tokens = self.backend.simulated_tokens
        self.trace.latency_ms = round((perf_counter() - started) * 1000, 3)
        return self.trace
