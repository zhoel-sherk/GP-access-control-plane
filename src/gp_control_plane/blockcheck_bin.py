"""Resolve blockcheck2.sh / blockcheck.sh independently of the process PATH.

`shutil.which` misses the script when the service runs under a restricted
`secure_path` (e.g. `sudo`), even though the install-linux.sh wrapper lives in
`/usr/local/libexec/gp-control-plane/`. Mirror the candidate list that `bs`
resolution already uses so blockcheck2 discovery works regardless of PATH.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_BLOCKCHECK_NAMES = ("blockcheck2.sh", "blockcheck.sh")
_NFQWS2_NAME = "nfqws2"


def _is_executable(path: str | None) -> bool:
    if not path:
        return False
    return Path(path).is_file() and os.access(path, os.X_OK)


def _fallback_candidates() -> list[str]:
    root = Path.home()
    candidates: list[str] = []
    for name in _BLOCKCHECK_NAMES:
        candidates.extend(
            [
                f"/usr/local/libexec/gp-control-plane/{name}",
                f"/opt/zapret2/{name}",
                str(root / ".local" / "bin" / name),
                f"/usr/local/bin/{name}",
                f"/usr/bin/{name}",
            ]
        )
    return candidates


def resolve_blockcheck_binary() -> str | None:
    """Return an executable blockcheck script path, or None."""
    for name in _BLOCKCHECK_NAMES:
        found = shutil.which(name)
        if _is_executable(found):
            return found
    for candidate in _fallback_candidates():
        if _is_executable(candidate):
            return candidate
    return None


def _nfqws2_candidates() -> list[str]:
    root = Path.home()
    return [
        f"/usr/local/libexec/gp-control-plane/{_NFQWS2_NAME}",
        f"/opt/zapret2/nfq2/{_NFQWS2_NAME}",
        str(root / ".local" / "bin" / _NFQWS2_NAME),
        f"/usr/local/bin/{_NFQWS2_NAME}",
        f"/usr/bin/{_NFQWS2_NAME}",
    ]


def resolve_nfqws2_binary() -> str | None:
    """Return an executable nfqws2 path, or None (independent of PATH)."""
    env_path = os.environ.get("BLOCKCHECKS_NFQWS2") or os.environ.get("NFQWS2_PATH") or ""
    if _is_executable(env_path.strip()):
        return env_path.strip()
    found = shutil.which(_NFQWS2_NAME)
    if _is_executable(found):
        return found
    for candidate in _nfqws2_candidates():
        if _is_executable(candidate):
            return candidate
    return None


__all__ = ["resolve_blockcheck_binary", "resolve_nfqws2_binary"]
