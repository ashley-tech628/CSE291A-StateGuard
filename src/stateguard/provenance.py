"""Typed provenance graph for one completed workflow attempt.

The graph records observed dependencies. A parent-result edge is conservative:
the planner names whole inputs, so an unused field can still appear affected.
This is preferable to silently reusing a result whose field-level use is unknown.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str


@dataclass(frozen=True)
class Impact:
    faulty_result_id: str
    result_ids: tuple[str, ...]
    action_ids: tuple[str, ...]
    event_sequences: tuple[int, ...]
    state_versions: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProvenanceGraph:
    nodes: dict[str, dict[str, Any]]
    edges: tuple[Edge, ...]
    issues: tuple[str, ...]

    def impacted_by(self, faulty_result_id: str) -> Impact:
        root = f"result:{faulty_result_id}"
        if root not in self.nodes or self.nodes[root]["type"] != "result":
            raise KeyError(faulty_result_id)
        outgoing: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            outgoing[edge.source].append(edge.target)
        seen = {root}
        pending = deque([root])
        while pending:
            for target in outgoing[pending.popleft()]:
                if target not in seen:
                    seen.add(target)
                    pending.append(target)
        return Impact(
            faulty_result_id=faulty_result_id,
            result_ids=tuple(sorted(
                node["result_id"] for key, node in self.nodes.items()
                if key in seen and node["type"] == "result"
            )),
            action_ids=tuple(sorted(
                node["action_id"] for key, node in self.nodes.items()
                if key in seen and node["type"] == "action"
            )),
            event_sequences=tuple(sorted(
                node["sequence"] for key, node in self.nodes.items()
                if key in seen and node["type"] == "event"
            )),
            state_versions=tuple(sorted(
                key.removeprefix("state:") for key, node in self.nodes.items()
                if key in seen and node["type"] == "state_version"
            )),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "nodes": self.nodes,
            "edges": [asdict(edge) for edge in self.edges],
            "issues": list(self.issues),
        }


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"unsupported trace record: {type(value).__name__}")


def build_provenance(trace: Any) -> ProvenanceGraph:
    """Build and audit a graph from an AttemptTrace or durable ExecutionTrace.

    Missing parents, actions, or state versions are reported in ``issues``.
    No edge is invented for an unobserved dependency.
    """
    data = _mapping(trace)
    results = [_mapping(item) for item in data.get("results", ())]
    actions = [_mapping(item) for item in data.get("actions", ())]
    events = [_mapping(item) for item in data.get("events", ())]
    nodes: dict[str, dict[str, Any]] = {}
    edges: set[Edge] = set()
    issues: list[str] = []
    produced_versions: set[str] = set()

    for result in results:
        rid = result["result_id"]
        node_id = f"result:{rid}"
        if node_id in nodes:
            issues.append(f"duplicate result_id: {rid}")
        nodes[node_id] = {"type": "result", "result_id": rid,
                          "agent_id": result["agent_id"], "status": result["status"]}
    for action in actions:
        aid = action["action_id"]
        node_id = f"action:{aid}"
        if node_id in nodes:
            issues.append(f"duplicate action_id: {aid}")
        nodes[node_id] = {"type": "action", "action_id": aid,
                          "operation": action["operation"],
                          "outcome": action["outcome"]}
    for event in events:
        sequence = event["sequence"]
        node_id = f"event:{sequence}"
        if node_id in nodes:
            issues.append(f"duplicate event sequence: {sequence}")
        nodes[node_id] = {"type": "event", "sequence": sequence,
                          "actor": event["actor"], "key": event["key"]}
        version_id = f"state:{event['key']}@{event['after_version']}"
        produced_versions.add(version_id)
        nodes[version_id] = {"type": "state_version", "key": event["key"],
                             "version": event["after_version"]}
        if event["after_version"] != event["before_version"] + 1:
            issues.append(f"nonconsecutive state version: {node_id}")
        edges.add(Edge(node_id, version_id, "produces_write"))

    action_by_id = {action["action_id"]: action for action in actions}
    for result in results:
        target = f"result:{result['result_id']}"
        for parent in result.get("parent_result_ids", ()):
            source = f"result:{parent}"
            if source in nodes:
                edges.add(Edge(source, target, "consumes"))
            else:
                issues.append(f"missing parent result: {parent} -> {result['result_id']}")
        for key, version in result.get("read_set", {}).items():
            source = f"state:{key}@{version}"
            if source not in nodes:
                nodes[source] = {"type": "state_version", "key": key,
                                 "version": version}
            if version != 0 and source not in produced_versions:
                issues.append(f"unobserved read version: {result['result_id']} {key}@{version}")
            edges.add(Edge(source, target, "reads_from"))

    for action in actions:
        target = f"action:{action['action_id']}"
        for parent in action.get("parent_result_ids", ()):
            source = f"result:{parent}"
            if source in nodes:
                edges.add(Edge(source, target, "triggers"))
            else:
                issues.append(f"missing action parent: {parent} -> {action['action_id']}")
        # The executor's conditional write depends on the field version it saw.
        # An independent administrator update does not inherit this dependency.
        if action.get("parent_result_ids") and action.get("expected_version") is not None:
            for key in action.get("write_set", ()):
                source = f"state:{key}@{action['expected_version']}"
                if source not in nodes:
                    nodes[source] = {"type": "state_version", "key": key,
                                     "version": action["expected_version"]}
                edges.add(Edge(source, target, "checks_version"))

    for event in events:
        aid = event["action_id"]
        if aid not in action_by_id:
            issues.append(f"missing action for event: {event['sequence']} ({aid})")
            continue
        if event["key"] not in action_by_id[aid].get("write_set", ()):
            issues.append(f"event key absent from action write_set: {aid} {event['key']}")
        edges.add(Edge(f"action:{aid}", f"event:{event['sequence']}", "commits"))

    return ProvenanceGraph(nodes, tuple(sorted(edges, key=lambda e: (e.source, e.target, e.kind))),
                           tuple(sorted(set(issues))))
