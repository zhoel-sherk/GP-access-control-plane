from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gp_control_plane.engine_cleaner import (
    detect_engine_switch,
    force_clean_engine_switch,
)
from gp_control_plane.storage import append_run


def _run(run_id: str, engine: str | None, *, kind: str = "standard-discovery") -> dict[str, object]:
    payload: dict[str, object] = {
        "id": run_id,
        "kind": kind,
        "status": "stopped",
        "domains": ["discord.com"],
    }
    if engine is not None:
        payload["discovery_engine"] = engine
    return payload


class DetectEngineSwitchTests(unittest.TestCase):
    def test_no_history_means_no_switch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_dir = Path(raw)
            self.assertIsNone(detect_engine_switch(state_dir, "blockcheck2"))
            self.assertIsNone(detect_engine_switch(state_dir, "blockchecks"))

    def test_bc2_to_bs_detects_switch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_dir = Path(raw)
            append_run(state_dir, _run("a" * 32, None))  # blockcheck2 default
            self.assertEqual("blockcheck2", detect_engine_switch(state_dir, "blockchecks"))

    def test_bs_to_bc2_detects_switch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_dir = Path(raw)
            append_run(state_dir, _run("a" * 32, "blockchecks"))
            self.assertEqual("blockchecks", detect_engine_switch(state_dir, "blockcheck2"))

    def test_same_engine_is_not_a_switch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_dir = Path(raw)
            append_run(state_dir, _run("a" * 32, "blockchecks"))
            self.assertIsNone(detect_engine_switch(state_dir, "blockchecks"))

    def test_newest_run_wins_over_older(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_dir = Path(raw)
            append_run(state_dir, _run("a" * 32, None))
            append_run(state_dir, _run("b" * 32, "blockchecks"))
            self.assertEqual("blockchecks", detect_engine_switch(state_dir, "blockcheck2"))

    def test_triage_history_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_dir = Path(raw)
            append_run(state_dir, _run("a" * 32, "blockchecks", kind="triage"))
            self.assertIsNone(detect_engine_switch(state_dir, "blockcheck2"))


class ForceCleanEngineSwitchTests(unittest.TestCase):
    def test_cleans_previous_engine_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_dir = Path(raw)
            append_run(state_dir, _run("a" * 32, None))
            with mock.patch("gp_control_plane.engine_cleaner._invoke_root") as invoke:
                invoke.return_value = mock.Mock(returncode=0, stderr="")
                result = force_clean_engine_switch(state_dir, "blockchecks")
            self.assertTrue(result["cleaned"])
            self.assertEqual("blockcheck2", result["previous_engine"])
            self.assertEqual("blockchecks", result["next_engine"])
            invoke.assert_called_once_with(["cleanup-residue", "blockcheck2"])

    def test_no_switch_skips_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_dir = Path(raw)
            append_run(state_dir, _run("a" * 32, "blockchecks"))
            with mock.patch("gp_control_plane.engine_cleaner._invoke_root") as invoke:
                result = force_clean_engine_switch(state_dir, "blockchecks")
            self.assertFalse(result["cleaned"])
            self.assertEqual("no_engine_switch", result["reason"])
            invoke.assert_not_called()

    def test_active_run_blocks_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_dir = Path(raw)
            append_run(state_dir, _run("a" * 32, None))
            with mock.patch("gp_control_plane.engine_cleaner._invoke_root") as invoke:
                with mock.patch(
                    "gp_control_plane.engine_cleaner.read_state",
                    return_value={"current_run_id": "z" * 32},
                ):
                    result = force_clean_engine_switch(state_dir, "blockchecks")
            self.assertFalse(result["cleaned"])
            self.assertEqual("active_run", result["reason"])
            invoke.assert_not_called()

    def test_bs_cleanup_drops_stale_campaign_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state_dir = root / "gp_state"
            state_dir.mkdir()
            bs_state = root / "bs_state"
            bs_state.mkdir(parents=True)
            lock = bs_state / "run.lock"
            lock.write_text('{"pid": 424242, "command": "dead"}', encoding="utf-8")
            append_run(state_dir, _run("a" * 32, "blockchecks"))
            with mock.patch("gp_control_plane.engine_cleaner._invoke_root") as invoke:
                invoke.return_value = mock.Mock(returncode=0, stderr="")
                with mock.patch(
                    "gp_control_plane.engine_cleaner.blockchecks_state_dir", return_value=bs_state
                ):
                    with mock.patch(
                        "gp_control_plane.engine_cleaner.campaign_lock_info", return_value=None
                    ):
                        result = force_clean_engine_switch(state_dir, "blockcheck2")
            self.assertTrue(result["cleaned"])
            self.assertTrue(result["stale_lock_removed"])
            self.assertFalse(lock.exists())
            invoke.assert_called_once_with(["cleanup-residue", "blockchecks"])


if __name__ == "__main__":
    unittest.main()
