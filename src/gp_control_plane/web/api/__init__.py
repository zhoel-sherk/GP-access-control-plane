"""web.api — single canonical HTTP handler layer shared by both web engines.

Each request-facing endpoint is expressed here as a pure handler taking a
``HandlerContext`` and returning ``(payload, status)``. The legacy
``api_server`` mixins and the Bottle app both delegate to this layer, so a
given path/method has exactly one implementation and one place to mock
external calls (e.g. ``bs_triage_domain``, ``export_nfconf``).

Transport concerns that are inherently server-specific (HTML assembly,
streaming writes, multipart uploads, HEAD semantics) stay in each engine but
dispatch through the same JSON tables below for the JSON API surface.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any

from gp_control_plane.config import AppConfig
from gp_control_plane.storage import is_storage_unavailable_error
from gp_control_plane.web.errors import error_payload


@dataclass
class HandlerContext:
    """Everything a unified JSON handler needs, independent of transport."""

    config: AppConfig
    runner: Any = None
    ui_enabled: bool = True
    runtime_role: str = "monolith"
    web_install_enabled: bool | None = True
    method: str = "GET"
    path: str = "/"
    query: dict[str, list[str]] = field(default_factory=dict)
    body: dict[str, Any] | None = None
    authorization: str | None = None


class ApiHttpError(Exception):
    """Handler-level HTTP error already shaped as a JSON payload."""

    def __init__(self, payload: dict[str, Any], status: int, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(str(payload))
        self.payload = payload
        self.status = int(status)
        self.headers = headers


class StorageUnavailableError(Exception):
    """Marker the engines map to their storage-unavailable JSON response."""


def _is_storage_error(error: BaseException) -> bool:
    return is_storage_unavailable_error(error)


# Tables are populated by importing the namespace modules at the bottom of
# this module (register_get / register_post decorate those handlers).
GET_HANDLERS: dict[str, Callable[[HandlerContext], dict[str, Any]]] = {}
# POST route metadata: handler(ctx) -> (payload, status), plus the HTTP
# statuses to use when the handler raises a generic error vs. a ValueError.
PostRoute = tuple[
    Callable[[HandlerContext], tuple[dict[str, Any], int]],
    int,
    int,
]
POST_HANDLERS: dict[str, PostRoute] = {}


def register_get(path: str) -> Callable[[Callable[[HandlerContext], dict[str, Any]]], Callable[[HandlerContext], dict[str, Any]]]:
    def decorate(fn: Callable[[HandlerContext], dict[str, Any]]) -> Callable[[HandlerContext], dict[str, Any]]:
        GET_HANDLERS[path] = fn
        return fn

    return decorate


def register_post(
    path: str,
    *,
    error_status: int = HTTPStatus.BAD_REQUEST,
    value_error_status: int = HTTPStatus.BAD_REQUEST,
) -> Callable[[Callable[[HandlerContext], tuple[dict[str, Any], int]]], Callable[[HandlerContext], tuple[dict[str, Any], int]]]:
    def decorate(
        fn: Callable[[HandlerContext], tuple[dict[str, Any], int]],
    ) -> Callable[[HandlerContext], tuple[dict[str, Any], int]]:
        POST_HANDLERS[path] = (fn, error_status, value_error_status)
        return fn

    return decorate


def json_get(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    """Dispatch a JSON GET to its handler, applying per-path error mapping.

    Mirrors the legacy ``api_server._get`` behaviour so a unified handler
    keeps identical semantics for every path that used to be special-cased.
    """
    path = ctx.path
    handler = GET_HANDLERS[path]
    try:
        return handler(ctx), HTTPStatus.OK
    except ApiHttpError:
        raise
    except Exception as exc:  # noqa: BLE001
        if _is_storage_error(exc):
            raise StorageUnavailableError() from exc
        if path == "/api/core/clean-install-vaults/status" and isinstance(exc, FileNotFoundError):
            return error_payload("not_found", "Clean-install vault was not found."), HTTPStatus.NOT_FOUND
        if path in {"/api/core/clean-install-vaults/list", "/api/core/clean-install-vaults/status"}:
            return error_payload("invalid_request", str(exc)), HTTPStatus.BAD_REQUEST
        if path in {"/api/core/presets/v2fly/category-domains", "/api/core/strategy-candidates"}:
            return {"error": str(exc)}, HTTPStatus.BAD_REQUEST
        raise


def json_post(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    """Dispatch a JSON POST to its handler with legacy error semantics.

    Mirrors ``api_server._post._dispatch_json_post``: storage errors surface
    as ``StorageUnavailableError``, auth/password/runtime-busy/value errors map
    to their documented statuses, everything else uses the route error status.
    """
    path = ctx.path
    handler, error_status, value_error_status = POST_HANDLERS[path]
    try:
        return handler(ctx)
    except ApiHttpError:
        raise
    except Exception as exc:  # noqa: BLE001
        if _is_storage_error(exc):
            raise StorageUnavailableError() from exc
        from gp_control_plane.auth import AuthenticationError, PasswordValidationError
        from gp_control_plane.web.api_server._errors import RuntimeBusyError

        if isinstance(exc, RuntimeBusyError):
            return {"error": "runtime_busy"}, HTTPStatus.CONFLICT
        if isinstance(exc, AuthenticationError):
            raise ApiHttpError(
                error_payload("authentication_required", "A Bearer token is required."),
                HTTPStatus.UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        if isinstance(exc, PasswordValidationError):
            return error_payload("invalid_request", str(exc)), HTTPStatus.BAD_REQUEST
        if isinstance(exc, ValueError):
            return {"error": str(exc)}, value_error_status
        return {"error": str(exc)}, error_status


from gp_control_plane.web.api import auth, core, service, web  # noqa: E402,F401
