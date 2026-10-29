import tempfile
import unittest
from pathlib import Path

from stateguard.demo import run_clean_demo
from stateguard.state import StateStore, VersionConflict


class StateTests(unittest.TestCase):
    def test_clean_trace_links_consumed_result_to_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            summary = run_clean_demo(root / "state.db", root / "trace.json")
            self.assertTrue(summary["success"])
            store = StateStore(root / "state.db")
            try:
                trace = store.trace("demo-001")
                self.assertEqual(trace.results[1].parent_result_ids, ("config-1",))
                self.assertEqual(trace.actions[0].parent_result_ids, ("plan-1",))
                self.assertEqual(trace.events[0].before_version, 0)
                self.assertEqual(store.read("api.db_port").version, 1)
            finally:
                store.close()

    def test_stale_write_does_not_add_event(self):
        with tempfile.TemporaryDirectory() as folder:
            store = StateStore(Path(folder) / "state.db")
            try:
                store.seed("api.db_port", 5431)
                store.update(run_id="r", key="api.db_port", value=5432,
                             expected_version=0, actor="executor", action_id="a1")
                with self.assertRaises(VersionConflict):
                    store.update(run_id="r", key="api.db_port", value=3306,
                                 expected_version=0, actor="executor", action_id="a2")
                self.assertEqual(len(store.trace("r").events), 1)
                self.assertEqual(store.read("api.db_port").value, 5432)
            finally:
                store.close()

    def test_retry_same_action_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            store = StateStore(Path(folder) / "state.db")
            try:
                store.seed("api.db_port", 5431)
                kwargs = dict(run_id="r", key="api.db_port", value=5432,
                              expected_version=0, actor="executor", action_id="a1")
                first = store.update(**kwargs)
                second = store.update(**kwargs)
                self.assertEqual(first[1].sequence, second[1].sequence)
                self.assertEqual(store.read("api.db_port").version, 1)
                self.assertEqual(len(store.trace("r").events), 1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
