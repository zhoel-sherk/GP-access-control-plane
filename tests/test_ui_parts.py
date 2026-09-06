"""Structure guards for the externalized GP web UI.

The SPA shell (`web/ui/views/index.tpl`, rendered by `web.ui.index_html`)
links real static assets from `web/ui/static/{css,js,html}` — no inline
``<style>``/``<script>`` blocks. These tests keep every asset file under the
size cap, verify the shell is deterministic and inline-free, and check that
each static asset is referenced through a versioned URL.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import pytest

from gp_control_plane.web.ui import index_html

_UI_DIR = Path(__file__).resolve().parents[1] / "src" / "gp_control_plane" / "web" / "ui"
_STATIC_DIR = _UI_DIR / "static"
_ASSET_LIMIT = 650
_PY_LIMIT = 800


pytestmark = pytest.mark.quality


def _physical_lines(text: str) -> int:
    if text == "":
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


class UiPartsStructureTests(unittest.TestCase):
    def test_every_static_asset_is_within_line_limit(self) -> None:
        for subdir in ("css", "js", "html"):
            for path in sorted((_STATIC_DIR / subdir).glob("*")):
                if not path.is_file():
                    continue
                self.assertLessEqual(
                    _physical_lines(path.read_text(encoding="utf-8")),
                    _ASSET_LIMIT,
                    f"{path.relative_to(_UI_DIR)} exceeds {_ASSET_LIMIT} physical lines",
                )

    def test_ui_package_python_files_are_within_line_limit(self) -> None:
        for path in _UI_DIR.rglob("*.py"):
            self.assertLessEqual(
                _physical_lines(path.read_text(encoding="utf-8")),
                _PY_LIMIT,
                f"{path.relative_to(_UI_DIR)} exceeds {_PY_LIMIT} physical lines",
            )

    def test_no_oversized_leftovers_under_ui_static(self) -> None:
        oversized: list[str] = []
        for path in _STATIC_DIR.rglob("*"):
            if path.is_dir() or path.suffix not in {".css", ".js", ".html"}:
                continue
            if _physical_lines(path.read_text(encoding="utf-8")) > _ASSET_LIMIT:
                oversized.append(f"{path.relative_to(_UI_DIR)}")
        self.assertEqual([], oversized)

    def test_index_shell_is_deterministic_and_starts_with_doctype(self) -> None:
        first = index_html()
        second = index_html()
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("<!doctype html>"))

    def test_index_shell_has_no_inline_style_or_script(self) -> None:
        html = index_html()
        self.assertEqual(html.count("<style>"), 0)
        self.assertEqual(html.count("</style>"), 0)
        self.assertEqual(html.count("<script>"), 0)

    def test_index_shell_links_every_static_asset_with_version_query(self) -> None:
        html = index_html()
        for subdir in ("css", "js"):
            names = sorted(p.name for p in (_STATIC_DIR / subdir).glob("*") if p.is_file())
            for name in names:
                self.assertIn(f"/static/{subdir}/{name}?v=", html, name)
            self.assertTrue(names, f"no assets under static/{subdir}")
        css_links = len(re.findall(r'<link rel="stylesheet" href="/static/css/[^"]+\?v=', html))
        js_tags = len(re.findall(r'<script src="/static/js/[^"]+\?v=', html))
        self.assertEqual(css_links, len(sorted(p.name for p in (_STATIC_DIR / "css").glob("*") if p.is_file())))
        self.assertEqual(js_tags, len(sorted(p.name for p in (_STATIC_DIR / "js").glob("*") if p.is_file())))


if __name__ == "__main__":
    unittest.main()
