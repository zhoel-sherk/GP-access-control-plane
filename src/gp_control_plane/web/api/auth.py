"""web.api.auth — health and authentication handlers (shared JSON API)."""

from __future__ import annotations

from typing import Any

from gp_control_plane.auth import change_password, health_payload, login
from gp_control_plane.web.api import HandlerContext, register_get, register_post


@register_get("/api/health")
def api_health(ctx: HandlerContext) -> dict[str, Any]:
    return health_payload()


@register_post("/api/auth/login", error_status=401, value_error_status=400)
def api_login(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    payload = ctx.body or {}
    return login(ctx.config.output.state_dir, payload), 200


@register_post("/api/auth/change-password", error_status=401, value_error_status=400)
def api_change_password(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    payload = ctx.body or {}
    return change_password(ctx.config.output.state_dir, payload, ctx.authorization), 200
