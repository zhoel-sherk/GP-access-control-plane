"""web.api.web — Web UI API handlers (shared JSON surface)."""

from __future__ import annotations

from typing import Any

from gp_control_plane.web.api import HandlerContext, register_get, register_post
from gp_control_plane.web.api_server._payloads import (
    web_json_get_payload,
    web_json_post_response,
)

WEB_GET_PATHS = (
    "/api/web/run-preferences",
    "/api/web/runs/history-page",
    "/api/web/candidate-domain-index-page",
    "/api/web/strategy-candidates-page",
    "/api/web/presets",
    "/api/web/presets/domains",
    "/api/web/bs-dns-pins",
    "/api/web/events",
)

WEB_POST_PATHS = (
    "/api/web/run-preferences",
    "/api/web/presets/save",
    "/api/web/presets/delete-user-lists",
)


def web_json_get(ctx: HandlerContext) -> dict[str, Any]:
    return web_json_get_payload(ctx.config, ctx.path, ctx.query)


def web_json_post(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    return web_json_post_response(ctx.config, ctx.path, ctx.body or {})


for _path in WEB_GET_PATHS:
    register_get(_path)(web_json_get)

for _path in WEB_POST_PATHS:
    register_post(_path, error_status=400, value_error_status=400)(web_json_post)
