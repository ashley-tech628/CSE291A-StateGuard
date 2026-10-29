"""SQLite field versions, atomic event logging, and idempotent writes."""

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import AgentResult, ExecutionTrace, StateEvent, ToolAction


class VersionConflict(Exception):
    pass


@dataclass(frozen=True)
class FieldValue:
    value: Any
    version: int


class StateStore:
    def __init__(self, path: str | Path):
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS fields (
                key TEXT PRIMARY KEY, value_json TEXT NOT NULL, version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS state_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL, key TEXT NOT NULL,
                old_value_json TEXT NOT NULL, new_value_json TEXT NOT NULL,
                before_version INTEGER NOT NULL, after_version INTEGER NOT NULL,
                actor TEXT NOT NULL, action_id TEXT NOT NULL UNIQUE,
                timestamp_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tool_actions (
                action_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                request_json TEXT NOT NULL, action_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agent_results (
                run_id TEXT NOT NULL, result_id TEXT NOT NULL,
                result_json TEXT NOT NULL, PRIMARY KEY(run_id, result_id)
            );
        """)

    def close(self) -> None:
        self.connection.close()

    def seed(self, key: str, value: Any) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO fields VALUES (?, ?, 0)",
                (key, json.dumps(value, sort_keys=True)),
            )

    def read(self, key: str) -> FieldValue:
        row = self.connection.execute(
            "SELECT value_json, version FROM fields WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise KeyError(key)
        return FieldValue(json.loads(row["value_json"]), row["version"])

    def record_result(self, result: AgentResult) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO agent_results VALUES (?, ?, ?)",
                (result.run_id, result.result_id, json.dumps(asdict(result), sort_keys=True)),
            )

    def update(
        self, *, run_id: str, key: str, value: Any, expected_version: int,
        actor: str, action_id: str, parent_result_ids: tuple[str, ...] = (),
    ) -> tuple[ToolAction, StateEvent]:
        request = dict(run_id=run_id, key=key, value=value,
                       expected_version=expected_version, actor=actor,
                       parent_result_ids=parent_result_ids)
        request_json = json.dumps(request, sort_keys=True)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            prior = self.connection.execute(
                "SELECT request_json, action_json FROM tool_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
            if prior is not None:
                if prior["request_json"] != request_json:
                    raise ValueError(f"action_id {action_id} reused with different request")
                action = _load_action(prior["action_json"])
                event = self._event_for_action(action_id)
                self.connection.commit()
                return action, event

            before = self.connection.execute(
                "SELECT value_json, version FROM fields WHERE key = ?", (key,)
            ).fetchone()
            if before is None:
                raise KeyError(key)
            if before["version"] != expected_version:
                raise VersionConflict(
                    f"{key}: expected {expected_version}, found {before['version']}"
                )
            new_version = expected_version + 1
            self.connection.execute(
                "UPDATE fields SET value_json = ?, version = ? WHERE key = ?",
                (json.dumps(value, sort_keys=True), new_version, key),
            )
            self.connection.execute("""
                INSERT INTO state_events
                (run_id, key, old_value_json, new_value_json, before_version,
                 after_version, actor, action_id, timestamp_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, key, before["value_json"], json.dumps(value, sort_keys=True),
                  expected_version, new_version, actor, action_id,
                  datetime.now(timezone.utc).isoformat()))
            action = ToolAction(
                run_id=run_id, action_id=action_id, operation="update_config",
                args={"key": key, "value": value}, expected_version=expected_version,
                parent_result_ids=parent_result_ids, write_set=(key,), outcome="committed",
            )
            self.connection.execute(
                "INSERT INTO tool_actions VALUES (?, ?, ?, ?)",
                (action_id, run_id, request_json, json.dumps(asdict(action), sort_keys=True)),
            )
            event = self._event_for_action(action_id)
            self.connection.commit()
            return action, event
        except Exception:
            self.connection.rollback()
            raise

    def _event_for_action(self, action_id: str) -> StateEvent:
        row = self.connection.execute(
            "SELECT * FROM state_events WHERE action_id = ?", (action_id,)
        ).fetchone()
        return StateEvent(
            run_id=row["run_id"], key=row["key"],
            old_value=json.loads(row["old_value_json"]),
            new_value=json.loads(row["new_value_json"]),
            before_version=row["before_version"], after_version=row["after_version"],
            actor=row["actor"], action_id=row["action_id"],
            sequence=row["sequence"], timestamp_utc=row["timestamp_utc"],
        )

    def trace(self, run_id: str) -> ExecutionTrace:
        result_rows = self.connection.execute(
            "SELECT result_json FROM agent_results WHERE run_id = ? ORDER BY rowid", (run_id,)
        ).fetchall()
        action_rows = self.connection.execute(
            "SELECT action_json FROM tool_actions WHERE run_id = ? ORDER BY rowid", (run_id,)
        ).fetchall()
        event_rows = self.connection.execute(
            "SELECT action_id FROM state_events WHERE run_id = ? ORDER BY sequence", (run_id,)
        ).fetchall()
        return ExecutionTrace(
            run_id=run_id,
            results=tuple(_load_result(r["result_json"]) for r in result_rows),
            actions=tuple(_load_action(r["action_json"]) for r in action_rows),
            events=tuple(self._event_for_action(r["action_id"]) for r in event_rows),
        )


def _load_result(data: str) -> AgentResult:
    obj = json.loads(data)
    obj["parent_result_ids"] = tuple(obj["parent_result_ids"])
    return AgentResult(**obj)


def _load_action(data: str) -> ToolAction:
    obj = json.loads(data)
    obj["parent_result_ids"] = tuple(obj["parent_result_ids"])
    obj["write_set"] = tuple(obj["write_set"])
    return ToolAction(**obj)
