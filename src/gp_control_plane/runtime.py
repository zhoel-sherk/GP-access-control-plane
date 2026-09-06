"""Canonical active-run record (``runtime.json``).

Discovery status/log readers used to scan the SQLite ``runs`` table for the
active run, which made live endpoints (status/log/history) fragile under heavy
writer load.  The active run now lives in a small file record that is kept in
sync with ``state.json`` transitions (single writer: the job runner thread) and
enriched by the discovery runners with engine/kind/log paths once they open
their log files.

Readers treat this file as the source of truth for *what is running right now*;
the SQLite ``runs`` table remains an append-only history (resume/backups).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

RUNTIME_FILE_NAME = "runtime.json"

_EXTENDED_KEYS = frozenset(
    {
        "engine",
        "kind",
        "phase",
        "started_at",
        "domains",
        "log_paths",
    }
)


def runtime_path(state_dir: Path) -> Path:
    return state_dir / RUNTIME_FILE_NAME


def read_runtime(state_dir: Path) -> dict[str, Any]:
    """Return the active-run record (never raises; defaults to inactive)."""
    path = runtime_path(state_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"active": False, "run_id": None}
    if not isinstance(raw, dict):
        return {"active": False, "run_id": None}
    raw.setdefault("active", bool(str(raw.get("run_id") or "").strip()))
    return raw


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    try:
        for _attempt in range(20):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                time.sleep(0.02)
    finally:
        tmp.unlink(missing_ok=True)


def sync_runtime_from_state(state_dir: Path, state: dict[str, Any]) -> None:
    """Mirror the current_run_* keys of ``state.json`` into the runtime record.

    Extended fields (engine/kind/log_paths...) of the same run are preserved;
    a cleared run resets the record.  Called under the state-update lock.
    """
    run_id = str(state.get("current_run_id") or "").strip()
    previous = read_runtime(state_dir)
    preserved: dict[str, Any] = {}
    if run_id and str(previous.get("run_id") or "") == run_id:
        for key in _EXTENDED_KEYS:
            if key in previous:
                preserved[key] = previous[key]
    payload: dict[str, Any] = {
        "active": bool(run_id),
        "run_id": run_id or None,
        "status": str(state.get("current_run_status") or ("running" if run_id else "")),
        "updated_at": _now_iso(),
    }
    if run_id:
        name = str(state.get("current_run_name") or "").strip()
        if name:
            payload["name"] = name
    payload.update(preserved)
    _write(runtime_path(state_dir), payload)


def enrich_active_run(state_dir: Path, *, run_id: str, **fields: Any) -> None:
    """Attach engine/kind/log-path metadata to the active run record.

    Called once by a discovery runner right after it opens its log files.
    Keeps extended keys only if the record still refers to *run_id*.
    """
    run_id = str(run_id or "")
    if not run_id:
        return
    path = runtime_path(state_dir)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(record, dict) or str(record.get("run_id") or "") != run_id:
        return
    changed = False
    for key in _EXTENDED_KEYS:
        if key in fields:
            record[key] = fields[key]
            changed = True
    if not changed:
        return
    record["updated_at"] = _now_iso()
    _write(path, record)


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "RUNTIME_FILE_NAME",
    "enrich_active_run",
    "read_runtime",
    "runtime_path",
    "sync_runtime_from_state",
]
