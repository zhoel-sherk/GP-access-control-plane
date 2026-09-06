"""gp_control_plane.storage._errors — moved from storage.py (split)."""
from __future__ import annotations

import inspect
import logging
import sqlite3

log = logging.getLogger(__name__)


class StorageUnavailableError(RuntimeError):
    """A transient SQLite failure that an API adapter may expose as HTTP 503."""

    status_code = 503


_TRANSIENT_SQLITE_PRIMARY_CODES = frozenset(
    {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
        sqlite3.SQLITE_IOERR,
    }
)


_TRANSIENT_SQLITE_MESSAGES = (
    "database is locked",
    "database is busy",
    "database schema is locked",
    "disk i/o error",
)


def is_storage_unavailable_error(error: BaseException) -> bool:
    """Return whether *error* is a known temporary SQLite availability failure."""
    if isinstance(error, StorageUnavailableError):
        return True
    if not isinstance(error, sqlite3.OperationalError):
        return False
    error_code = getattr(error, "sqlite_errorcode", None)
    if isinstance(error_code, int) and (error_code & 0xFF) in _TRANSIENT_SQLITE_PRIMARY_CODES:
        return True
    return any(message in str(error).lower() for message in _TRANSIENT_SQLITE_MESSAGES)


def _storage_caller_chain() -> str:
    """Best-effort short chain of the non-sqlite callers (e.g. the endpoint)."""
    try:
        frames = inspect.stack()
    except Exception:  # noqa: BLE001 — diagnostics must never raise
        return ""
    parts: list[str] = []
    for frame in frames[1:8]:
        module = str(frame.frame.f_globals.get("__name__") or "")
        if module.startswith("sqlite3") or module.startswith("gp_control_plane.storage._errors"):
            continue
        parts.append(f"{module.rsplit('.', 1)[-1]}.{frame.function}")
    return " <- ".join(parts[-3:])


def _raise_storage_unavailable(error: sqlite3.OperationalError) -> None:
    """Map only known temporary SQLite availability failures to a stable error."""
    if is_storage_unavailable_error(error):
        log.error(
            "storage unavailable mapped to 503; sqlite_errorcode=%r message=%r caller=%s",
            getattr(error, "sqlite_errorcode", None),
            str(error),
            _storage_caller_chain(),
        )
        raise StorageUnavailableError("storage is temporarily unavailable") from error
    raise error
