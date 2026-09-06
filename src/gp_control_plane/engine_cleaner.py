"""Force-cleanup of discovery-engine residue when switching engines.

Switching discovery engines back-to-back (blockcheck2 <-> blockcheckS) can
leave host residue behind when the previous engine was stopped or crashed
mid-probe: transient nft tables named ``blockcheck<pid>_test`` (created and
deleted by the nfq feature probe), orphaned ``bs-p-*`` netns pools and stale
``/dev/shm/blockchecks`` shm files.  A dirty environment then makes the next
engine run fail at teardown (e.g. ``bs`` exiting rc=1 on netns destroy).

This module runs a privileged, strictly-validated residue sweep *for the
engine being left* right before a run of the other engine is started.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from gp_control_plane.discovery_engine import (
    ENGINE_BLOCKCHECK2,
    ENGINE_BLOCKCHECKS,
    blockchecks_state_dir,
    campaign_lock_info,
    normalize_engine,
)
from gp_control_plane.state import read_state
from gp_control_plane.storage import read_latest_run_payloads

DEFAULT_ROOT_HELPER = "/usr/local/libexec/gp-control-plane/gp-root-helper"
log = logging.getLogger(__name__)


def _root_helper_path() -> str:
    return os.environ.get("GP_ROOT_HELPER", DEFAULT_ROOT_HELPER)


def _invoke_root(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    helper = _root_helper_path()
    if os.geteuid() == 0:
        prefix = [helper]
    else:
        sudo = shutil.which("sudo")
        prefix = [sudo, "-n", helper] if sudo else [helper]
    return subprocess.run(
        [*prefix, *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _engine_of_run(run: dict[str, Any]) -> str:
    """Engine that produced a persisted run payload.

    blockcheckS runs record ``discovery_engine="blockchecks"``; blockcheck2
    runs leave the field unset, which normalizes to the blockcheck2 default.
    """
    return normalize_engine(run.get("discovery_engine"))


def _previous_discovery_engine(state_dir: Path) -> str | None:
    """Engine of the most recent non-triage discovery run, newest first."""
    for run in reversed(read_latest_run_payloads(state_dir, limit=100)):
        if not isinstance(run, dict):
            continue
        kind = str(run.get("kind") or "")
        if kind == "triage":
            continue
        if not (str(run.get("id") or "") and (run.get("domains") or run.get("stdout_log"))):
            continue
        return _engine_of_run(run)
    return None


def detect_engine_switch(state_dir: Path, next_engine: str) -> str | None:
    """Return the engine being switched away from, or None if no switch."""
    next_engine = normalize_engine(next_engine)
    previous = _previous_discovery_engine(state_dir)
    if previous is None or previous == next_engine:
        return None
    return previous


def _drop_stale_campaign_lock() -> bool:
    lock = blockchecks_state_dir() / "run.lock"
    if not lock.is_file():
        return False
    if campaign_lock_info() is not None:
        return False
    try:
        lock.unlink()
    except OSError as exc:  # pragma: no cover - best-effort cleanup
        log.warning("could not remove stale blockcheckS run.lock %s: %s", lock, exc)
        return False
    log.info("removed stale blockcheckS run.lock: %s", lock)
    return True


def force_clean_engine(engine: str) -> dict[str, Any]:
    """Force-remove residue of *engine* (the engine being left behind)."""
    engine = normalize_engine(engine)
    result = _invoke_root(["cleanup-residue", engine])
    payload: dict[str, Any] = {
        "engine": engine,
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stderr": str(result.stderr).strip()[:500],
    }
    if result.returncode == 0:
        log.info("engine residue cleanup ok for %s", engine)
    else:
        log.warning("engine residue cleanup failed for %s: %s", engine, result.stderr.strip())
    if engine == ENGINE_BLOCKCHECKS:
        payload["stale_lock_removed"] = _drop_stale_campaign_lock()
    return payload


def force_clean_engine_switch(state_dir: Path, next_engine: str) -> dict[str, Any]:
    """Clean residue of the engine being left, if a switch is detected.

    Never runs while a discovery run is active.  Returns a short result
    payload suitable for attaching to a run record or a response.
    """
    next_engine = normalize_engine(next_engine)
    state = read_state(state_dir)
    if not isinstance(state, dict):
        return {"cleaned": False, "reason": "state_unreadable", "next_engine": next_engine}
    if str(state.get("current_run_id") or "").strip():
        return {"cleaned": False, "reason": "active_run", "next_engine": next_engine}
    previous = detect_engine_switch(state_dir, next_engine)
    if previous is None:
        return {
            "cleaned": False,
            "reason": "no_engine_switch",
            "next_engine": next_engine,
            "previous_engine": previous,
        }
    result = force_clean_engine(previous)
    result.update(
        {
            "cleaned": bool(result.get("ok")),
            "previous_engine": previous,
            "next_engine": next_engine,
        }
    )
    return result


__all__ = [
    "ENGINE_BLOCKCHECK2",
    "ENGINE_BLOCKCHECKS",
    "detect_engine_switch",
    "force_clean_engine",
    "force_clean_engine_switch",
]
