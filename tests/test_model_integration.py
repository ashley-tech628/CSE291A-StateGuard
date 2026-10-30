import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from stateguard.model_adapter import ModelAdapter
from stateguard.workflow import DeploymentTask, WorkflowRunner


class FakeModel:
    model = "fake-model-no-network"

    def __init__(self, broken=None, ignore_fault=False):
        self.broken = broken
        self.ignore_fault = ignore_fault

    def generate_json(self, prompt, inputs):
        if "listening port" in prompt:
            name = "config"
            output = {"db_port": inputs["database"]["port"]}
        elif "Dependency Agent" in prompt:
            name = "dependency"
            protocol = inputs["database"]["queue_protocol"]
            output = {"queue_protocol": protocol, "compatible": protocol == "v2"}
        elif "Resource Agent" in prompt:
            name = "resource"
            n = inputs["requested_api_replicas"] + inputs["requested_worker_replicas"]
            output = {"requested_cpu": n, "within_budget": n <= inputs["cpu_budget"]}
        else:
            name = "planner"
            a, target = inputs["analysis"], inputs["deployment_target"]
            port = 5432 if self.ignore_fault else a["config"]["content"]["db_port"]
            writes = [
                {"key": "api.db_port", "value": port},
                {"key": "api.image_version", "value": target["api_image"]},
                {"key": "worker.image_version", "value": target["worker_image"]},
                {"key": "worker.queue_protocol", "value": a["dependency"]["content"]["queue_protocol"]},
            ]
            extra = a["config"]["content"].get("requested_extra_write")
            if extra:
                writes.append(extra)
            output = {"writes": writes, "resource_ok": a["resource"]["content"]["within_budget"]}
        if self.broken == name:
            output = {"bad": "schema"}
        return {"model": self.model, "messages": [{"role": "user", "content": inputs}],
                "parsed": output, "raw_response": json.dumps(output),
                "error": None, "usage": {"total_tokens": 10}, "latency_ms": 1}


def run(tmp_path, fault="none", policy="no_recovery", model=None):
    return WorkflowRunner(task=DeploymentTask(), fault=fault, policy=policy,
                          db_path=tmp_path / "state.db", attempt_id="test", seed=7,
                          model_adapter=model or FakeModel()).run()


def test_four_stages_and_separate_actual_cost(tmp_path):
    trace = run(tmp_path)
    assert trace.checker["success"]
    assert [c["agent_id"] for c in trace.model_calls] == ["config", "dependency", "resource", "planner"]
    assert trace.actual_tokens == 40
    assert trace.simulated_tokens == 0
    assert trace.real_inference_calls == 4


@pytest.mark.parametrize("fault", ["incorrect", "stale", "timeout"])
def test_real_interface_fault_failure(tmp_path, fault):
    trace = run(tmp_path, fault=fault)
    assert not trace.checker["success"]
    assert trace.fault_consumed is (fault != "timeout")


@pytest.mark.parametrize("fault", ["incorrect", "stale", "timeout", "adversarial"])
def test_verification_retries_real_interface(tmp_path, fault):
    trace = run(tmp_path, fault=fault, policy="always_verify")
    assert trace.checker["success"]
    assert trace.actual_tokens == 50
    assert trace.real_inference_calls == 5
    assert not trace.fault_consumed


@pytest.mark.parametrize("stage", ["config", "dependency", "resource", "planner"])
def test_invalid_output_stops_without_fallback(tmp_path, stage):
    trace = run(tmp_path, model=FakeModel(broken=stage))
    assert not trace.checker["success"]
    assert trace.actions == []
    assert any(c["status"] == "error" for c in trace.model_calls)


def test_failed_verifier_retry_does_not_continue(tmp_path):
    model = FakeModel()
    original = model.generate_json
    def incorrect(prompt, inputs):
        result = original(prompt, inputs)
        if "listening port" in prompt:
            result["parsed"]["db_port"] = 9999
        return result
    model.generate_json = incorrect
    trace = run(tmp_path, model=model, policy="always_verify")
    assert not trace.checker["success"]
    assert trace.actions == []
    assert trace.verification_events[0]["retry_valid"] is False


def test_fault_exposure_does_not_imply_propagation(tmp_path):
    trace = run(tmp_path, fault="incorrect", model=FakeModel(ignore_fault=True))
    assert trace.checker["success"]
    assert trace.fault_evidence[0]["exposed_to_planner"]
    assert not trace.fault_consumed


def test_adversarial_action_rejected_at_tool_layer(tmp_path):
    trace = run(tmp_path, fault="adversarial")
    assert trace.checker["unauthorized_attempts"] == 1
    assert trace.checker["unauthorized_commits"] == 0


class MockClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.chat = SimpleNamespace(completions=self)
    def create(self, **kwargs):
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


def response(content, reasoning=2):
    usage = SimpleNamespace(model_dump=lambda: {
        "prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10,
        "completion_tokens_details": {"reasoning_tokens": reasoning},
    })
    return SimpleNamespace(id="mock", model="mock", usage=usage, choices=[
        SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))])


def test_adapter_accounts_for_failed_parse_and_retry():
    client = MockClient([response("not JSON"), response('{"ok": true}')])
    out = ModelAdapter(client=client, max_attempts=2).generate_json("test", {})
    assert out["status"] == "ok"
    assert out["attempts"][0]["status"] == "error"
    assert out["retry_count"] == 1
    assert out["usage"]["total_tokens"] == 20
    assert out["usage"]["completion_tokens_details"]["reasoning_tokens"] == 4


def test_adapter_keeps_unknown_reasoning_as_null():
    out = ModelAdapter(client=MockClient([response('{"ok": true}', None)])).generate_json("test", {})
    assert out["usage"]["completion_tokens_details"]["reasoning_tokens"] is None


def test_adapter_redacts_exception_text():
    out = ModelAdapter(client=MockClient([RuntimeError("private-key-should-not-leak")])).generate_json("test", {})
    assert out["status"] == "error"
    assert "private-key-should-not-leak" not in json.dumps(out)


def test_plan_schema_rejects_boolean_port():
    assert not WorkflowRunner._valid_plan({"resource_ok": True, "writes": [
        {"key": "api.db_port", "value": True}]})


def test_smoke_cli_saves_all_scenarios_and_restart(tmp_path, monkeypatch):
    import importlib.util
    import sys
    script = Path(__file__).parents[1] / "scripts" / "run_llm_phase1.py"
    spec = importlib.util.spec_from_file_location("llm_cli_under_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class Backend(FakeModel):
        sdk_version = "mock"
        def __init__(self, **kwargs):
            super().__init__()
    monkeypatch.setattr(module, "ModelAdapter", Backend)
    output = tmp_path / "smoke"
    monkeypatch.setattr(sys, "argv", [str(script), "--suite", "smoke", "--output", str(output)])
    module.main()
    import csv
    with (output / "summary.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 8
    restart = next(r for r in rows if r["policy"] == "full_restart")
    assert restart["success"] == "True" and restart["attempts"] == "2"
    assert restart["simulated_cost_units"] == "0"
    assert len(list(output.glob("*/attempt-*.json"))) == 9
