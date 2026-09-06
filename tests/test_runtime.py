from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gp_control_plane.engine_common._logtail import latest_log_tail_for_run
from gp_control_plane.runtime import enrich_active_run, read_runtime
from gp_control_plane.state import update_state


def _set_current(state_dir: Path, run_id: str | None, status: str) -> None:
    def mark(state: dict[str, object]) -> dict[str, object]:
        state["current_run_id"] = run_id
        state["current_run_name"] = run_id
        state["current_run_status"] = status
        return state

    update_state(state_dir, mark)


class RuntimeMirrorTests(unittest.TestCase):
    def test_inactive_default(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            rt = read_runtime(Path(raw))
            self.assertFalse(rt["active"])
            self.assertIsNone(rt["run_id"])

    def test_transition_mirrors_and_clears(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_dir = Path(raw)
            _set_current(state_dir, "a" * 32, "running")
            rt = read_runtime(state_dir)
            self.assertTrue(rt["active"])
            self.assertEqual("a" * 32, rt["run_id"])
            self.assertEqual("running", rt["status"])
            _set_current(state_dir, None, "")
            rt = read_runtime(state_dir)
            self.assertFalse(rt["active"])
            self.assertIsNone(rt["run_id"])

    def test_extended_fields_survive_status_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_dir = Path(raw)
            run_id = "b" * 32
            _set_current(state_dir, run_id, "running")
            enrich_active_run(state_dir, run_id=run_id, engine="blockcheck2", kind="standard-discovery")
            _set_current(state_dir, run_id, "stopping")
            rt = read_runtime(state_dir)
            self.assertEqual("blockcheck2", rt["engine"])
            self.assertEqual("stopping", rt["status"])
            # A different run id drops the extended fields of the old run.
            _set_current(state_dir, "c" * 32, "running")
            rt = read_runtime(state_dir)
            self.assertNotIn("engine", rt)

    def test_enrich_ignores_foreign_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_dir = Path(raw)
            run_id = "d" * 32
            _set_current(state_dir, run_id, "running")
            enrich_active_run(state_dir, run_id="f" * 32, engine="blockchecks")
            self.assertNotIn("engine", read_runtime(state_dir))


class LogTailForRunTests(unittest.TestCase):
    def test_returns_none_without_stdout_log(self) -> None:
        run = {"id": "a" * 32, "kind": "standard-discovery", "status": "running"}
        self.assertIsNone(latest_log_tail_for_run(run))

    def test_returns_tail_for_runtime_style_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            log_file = root / "stdout.log"
            log_file.write_text("line1\nline2\n", encoding="utf-8")
            run = {
                "id": "a" * 32,
                "kind": "standard-discovery",
                "status": "running",
                "stdout_log": str(log_file),
                "progress_log": str(root / "missing-progress.json"),
            }
            payload = latest_log_tail_for_run(run)
            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertEqual("a" * 32, payload["run_id"])
            self.assertIn("line2", payload["stdout_tail"])


if __name__ == "__main__":
    unittest.main()
