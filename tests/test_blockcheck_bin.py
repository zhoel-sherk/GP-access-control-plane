"""Unit tests for blockcheck2.sh/blockcheck.sh resolution outside PATH."""

from __future__ import annotations

import stat
from pathlib import Path

from gp_control_plane import blockcheck_bin as bb


def _make_exec(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_which_wins_when_available(monkeypatch, tmp_path):
    fake = _make_exec(tmp_path / "bin" / "blockcheck2.sh")
    monkeypatch.setattr(bb.shutil, "which", lambda name: fake if name.startswith("blockcheck") else None)
    assert bb.resolve_blockcheck_binary() == fake


def test_home_local_bin_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(bb.shutil, "which", lambda name: None)
    monkeypatch.setenv("HOME", str(tmp_path))
    fake = _make_exec(tmp_path / ".local" / "bin" / "blockcheck.sh")
    monkeypatch.setattr(bb, "_is_executable", lambda path: path == fake)
    assert bb.resolve_blockcheck_binary() == fake


def test_none_when_absent(monkeypatch):
    monkeypatch.setattr(bb.shutil, "which", lambda name: None)
    monkeypatch.setattr(bb, "_is_executable", lambda path: False)
    assert bb.resolve_blockcheck_binary() is None


def test_fallback_includes_install_wrapper_dir():
    names = bb._fallback_candidates()
    assert "/usr/local/libexec/gp-control-plane/blockcheck2.sh" in names
    assert "/opt/zapret2/blockcheck2.sh" in names
