"""web.api.service — Service API handlers (shared JSON surface)."""

from __future__ import annotations

from typing import Any

from gp_control_plane import __version__, service_api
from gp_control_plane.settings import read_service_settings
from gp_control_plane.state import active_job_lock_payload
from gp_control_plane.web.api import HandlerContext, register_get, register_post


def _ensure_service_idle(ctx: HandlerContext) -> None:
    if active_job_lock_payload(ctx.config.output.state_dir, cleanup_stale=True):
        raise RuntimeError("service action is blocked while another job is running")


@register_get("/api/service/status")
def service_status(ctx: HandlerContext) -> dict[str, Any]:
    return service_api.service_status_payload(
        ctx.config,
        current_version=__version__,
        runtime_role=ctx.runtime_role,
        web_enabled=ctx.ui_enabled,
    )


@register_get("/api/service/releases/available")
def service_releases(ctx: HandlerContext) -> dict[str, Any]:
    return service_api.available_releases_payload(read_service_settings(ctx.config), current_version=__version__)


@register_get("/api/service/v2fly/local-storage-status")
def service_v2fly_storage_status(ctx: HandlerContext) -> dict[str, Any]:
    return service_api.v2fly_storage_status_payload(ctx.config)


@register_post("/api/service/v2fly/check-updates", error_status=409, value_error_status=400)
def service_v2fly_check_updates(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    _ensure_service_idle(ctx)
    return service_api.v2fly_check_updates_payload(ctx.config), 200


@register_post("/api/service/v2fly/update-local-storage", error_status=409, value_error_status=400)
def service_v2fly_update_storage(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    payload = ctx.body or {}
    if not payload.get("dry_run"):
        _ensure_service_idle(ctx)
    return service_api.v2fly_update_local_storage_payload(ctx.config, payload), 200
