"""GP web UI — SPA shell rendered from external static assets.

The document is a Bottle ``SimpleTemplate`` shell (``views/index.tpl``) that
links stylesheets and scripts by ``<link>/<script src>`` with content-hash
cache-busting; no inline ``<style>`` or ``<script>`` blocks are emitted.
Static assets live under ``web/ui/static/{css,js,html}`` and are served by
the Bottle app (never inlined).
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from gp_control_plane.web.vendor.bottle import SimpleTemplate

_UI_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _UI_DIR / "static"
_TEMPLATE = _UI_DIR / "views" / "index.tpl"


def static_root() -> Path:
    """Filesystem root the /static route maps to."""
    return _STATIC_DIR


def _ordered_names(subdir: str) -> tuple[str, ...]:
    return tuple(sorted(p.name for p in (_STATIC_DIR / subdir).glob("*") if p.is_file()))


def _stamp(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _asset_version(subdir: str, name: str) -> str:
    digest = hashlib.sha1((_STATIC_DIR / subdir / name).read_bytes()).hexdigest()
    return digest[:10]


@lru_cache(maxsize=1)
def _render_shell(signature: tuple[tuple[str, str], ...]) -> str:
    del signature  # cache key only; asset content is stable per signature
    css_links = "\n".join(
        f'<link rel="stylesheet" href="/static/css/{name}?v={_asset_version("css", name)}">'
        for name in _ordered_names("css")
    )
    script_tags = "\n".join(
        f'<script src="/static/js/{name}?v={_asset_version("js", name)}"></script>'
        for name in _ordered_names("js")
    )
    body_html = "\n".join(
        (_STATIC_DIR / "html" / name).read_text(encoding="utf-8") for name in _ordered_names("html")
    )
    template = SimpleTemplate(_TEMPLATE.read_text(encoding="utf-8"))
    return template.render(css_links=css_links, body_html=body_html, script_tags=script_tags)


def _signature() -> tuple[tuple[str, str], ...]:
    parts: list[tuple[str, str]] = [("tpl", _stamp(_TEMPLATE))]
    for subdir in ("css", "js", "html"):
        for name in _ordered_names(subdir):
            parts.append((f"{subdir}/{name}", _stamp(_STATIC_DIR / subdir / name)))
    return tuple(parts)


def index_html() -> str:
    """Render the SPA shell (cached; recomputed when any asset file changes)."""
    return _render_shell(_signature())


__all__ = ["index_html", "static_root"]
