"""bottle_server._routes — Bottle app creation and main routing setup.

Routes are registered by walking the single ``web.routes.ROUTES`` contract:
JSON GET/POST endpoints dispatch to the unified ``web.api`` handler layer,
while transport-shaped endpoints (HTML/docs, NDJSON export, download, upload,
SSE) are served by local adapter functions registered for the same paths.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from http import HTTPStatus
from typing import Any

from gp_control_plane import auth as _auth_api
from gp_control_plane import core_api
from gp_control_plane.auth import AuthenticationError
from gp_control_plane.backups import import_snapshot_archive, snapshot_file_path
from gp_control_plane.config import AppConfig
from gp_control_plane.state import has_active_runtime
from gp_control_plane.storage import is_storage_unavailable_error
from gp_control_plane.web import limits as _limits
from gp_control_plane.web.api import (
    ApiHttpError,
    HandlerContext,
    StorageUnavailableError,
    json_get,
    json_post,
)
from gp_control_plane.web.api_server._errors import RequestBodyTooLarge
from gp_control_plane.web.api_server._helpers import _query_one
from gp_control_plane.web.bottle_server._sse import stream_web_events
from gp_control_plane.web.docs import (
    OPENAPI_JSON_CONTENT_TYPE,
    SWAGGER_HTML_CONTENT_TYPE,
    openapi_json_bytes,
    swagger_ui_html,
)
from gp_control_plane.web.errors import error_payload, normalize_error_payload
from gp_control_plane.web.limits import NDJSON_CONTENT_TYPE
from gp_control_plane.web.routes import ROUTES, route_for
from gp_control_plane.web.ui import index_html as ui_index_html
from gp_control_plane.web.ui import static_root
from gp_control_plane.web.vendor.bottle import Bottle, HTTPResponse, request, response, static_file

_STORAGE_ERROR_JSON = error_payload("storage_unavailable", "Storage is temporarily unavailable.")


def create_bottle_app(
    config: AppConfig,
    runner: Any,
    *,
    runtime_role: str = "monolith",
    ui_enabled: bool = True,
) -> Bottle:
    """Create and configure Bottle WSGI application from the route contract."""
    app = Bottle()

    def _authorize(path: str) -> None:
        if not path.startswith("/api/"):
            return
        route = route_for(request.method, path)
        if route and not route.auth_required:
            return
        _auth_api.require_bearer_token(config.output.state_dir, request.get_header("Authorization"))

    def _json(payload: dict[str, Any], status: int = 200) -> HTTPResponse:
        norm = normalize_error_payload(payload, HTTPStatus(status))
        data = json.dumps(norm, ensure_ascii=False, separators=(",", ":"))
        return HTTPResponse(
            body=data,
            status=status,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

    def _get_query_dict() -> dict[str, list[str]]:
        return {k: request.query.getall(k) for k in request.query}

    def _request_json() -> dict[str, Any]:
        try:
            length = int(request.get_header("Content-Length") or "0")
        except ValueError:
            length = 0
        max_json = _limits.MAX_JSON_REQUEST_BYTES
        if length > max_json:
            raise RequestBodyTooLarge("request body is too large")
        try:
            raw = request.body.read(length or max_json).decode("utf-8")
            if not raw.strip():
                return {}
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, RequestBodyTooLarge):
                raise
            return {}

    def _make_ctx(method: str) -> HandlerContext:
        return HandlerContext(
            config=config,
            runner=runner,
            ui_enabled=ui_enabled,
            runtime_role=runtime_role,
            web_install_enabled=ui_enabled,
            method=method,
            path=request.path,
            query=_get_query_dict(),
            body=_request_json() if method == "POST" else None,
            authorization=request.get_header("Authorization"),
        )

    def _json_api_route(method: str) -> Callable[[], HTTPResponse]:
        def handler() -> HTTPResponse:
            try:
                ctx = _make_ctx(method)
            except RequestBodyTooLarge as exc:
                return _json(error_payload("request_too_large", str(exc)), 413)
            try:
                if method == "GET":
                    payload, status = json_get(ctx)
                else:
                    payload, status = json_post(ctx)
            except ApiHttpError as exc:
                headers = {"Content-Type": "application/json; charset=utf-8"}
                if exc.headers:
                    headers.update(exc.headers)
                return HTTPResponse(
                    body=json.dumps(exc.payload, ensure_ascii=False, separators=(",", ":")),
                    status=exc.status,
                    headers=headers,
                )
            except StorageUnavailableError:
                return HTTPResponse(
                    body=json.dumps(_STORAGE_ERROR_JSON, ensure_ascii=False, separators=(",", ":")),
                    status=503,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
            return _json(payload, status)

        return handler

    def root_page() -> HTTPResponse:
        html = ui_index_html()
        data = html.encode("utf-8")
        if request.method == "HEAD":
            return HTTPResponse(
                body=b"",
                status=200,
                headers={
                    "Content-Type": "text/html; charset=utf-8",
                    "Cache-Control": "no-store",
                    "Content-Length": str(len(data)),
                },
            )
        return HTTPResponse(
            body=data,
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
        )

    def openapi_route() -> HTTPResponse:
        data = openapi_json_bytes(core_only=not ui_enabled)
        if request.method == "HEAD":
            return HTTPResponse(
                body=b"",
                status=200,
                headers={"Content-Type": OPENAPI_JSON_CONTENT_TYPE, "Content-Length": str(len(data))},
            )
        return HTTPResponse(
            body=data,
            status=200,
            headers={"Content-Type": OPENAPI_JSON_CONTENT_TYPE, "Cache-Control": "no-store"},
        )

    def swagger_route() -> HTTPResponse:
        data = swagger_ui_html().encode("utf-8")
        if request.method == "HEAD":
            return HTTPResponse(
                body=b"",
                status=200,
                headers={"Content-Type": SWAGGER_HTML_CONTENT_TYPE, "Content-Length": str(len(data))},
            )
        return HTTPResponse(
            body=data,
            status=200,
            headers={"Content-Type": SWAGGER_HTML_CONTENT_TYPE, "Cache-Control": "no-store"},
        )

    def export_strategy_candidates() -> Any:
        query = _get_query_dict()
        if request.method == "HEAD":
            return HTTPResponse(status=200, headers={"Content-Type": NDJSON_CONTENT_TYPE, "Content-Length": "0"})
        iterator = core_api.iter_strategy_candidates_export_lines(config, query)
        try:
            first_line = next(iterator)
        except StopIteration:
            first_line = None
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, ValueError):
                return _json({"error": str(exc)}, 400)
            if is_storage_unavailable_error(exc):
                return HTTPResponse(
                    body=json.dumps(_STORAGE_ERROR_JSON, ensure_ascii=False, separators=(",", ":")),
                    status=503,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
            return _json(error_payload("internal_error", str(exc)), 500)

        def body() -> Any:
            if first_line is not None:
                yield first_line
            while True:
                try:
                    line = next(iterator)
                except StopIteration:
                    return
                except Exception:  # noqa: BLE001 - mid-stream failure truncates the stream
                    return
                yield line

        response.content_type = NDJSON_CONTENT_TYPE
        response.set_header("Cache-Control", "no-store")
        return body()

    def download_backup_archive() -> HTTPResponse:
        query_dict = _get_query_dict()
        snapshot_id = _query_one(query_dict, "snapshot_id") or _query_one(query_dict, "snapshot")
        try:
            file_path = snapshot_file_path(config.output.state_dir, snapshot_id, "archive")
            if not file_path.is_file():
                return _json(error_payload("not_found", "Snapshot archive was not found."), 404)
            data = file_path.read_bytes()
            return HTTPResponse(
                body=data,
                status=200,
                headers={
                    "Content-Type": "application/zip",
                    "Content-Disposition": f'attachment; filename="{file_path.name}"',
                    "Content-Length": str(len(data)),
                },
            )
        except Exception:  # noqa: BLE001
            return _json(error_payload("not_found", "Snapshot archive was not found."), 404)

    def upload_backup() -> HTTPResponse:
        try:
            if has_active_runtime(config.output.state_dir):
                return _json(error_payload("runtime_busy", "Backup mutations are blocked while another job is running."), 409)
            content_length = int(request.get_header("Content-Length") or "0")
            max_upload = _limits.MAX_BACKUP_UPLOAD_BYTES
            if content_length > max_upload:
                return _json(error_payload("request_too_large", "request body is too large"), 413)
            body = request.body.read(max_upload + 1)
            if len(body) > max_upload:
                return _json(error_payload("request_too_large", "request body is too large"), 413)
            imported = import_snapshot_archive(config.output.state_dir, body)
            return _json(core_api.backup_snapshot_payload(imported.get("snapshot") or {}), 201)
        except Exception as exc:  # noqa: BLE001
            return _json({"error": str(exc)}, 400)

    def events_stream() -> Any:
        auth_header = request.get_header("Authorization")
        response.content_type = "text/event-stream; charset=utf-8"
        response.set_header("Cache-Control", "no-store")
        return stream_web_events(config, auth_header)

    @app.hook("before_request")
    def before_request_hook() -> None:
        if request.method == "OPTIONS":
            return
        try:
            _authorize(request.path)
        except AuthenticationError:
            err_data = json.dumps(
                error_payload("authentication_required", "A Bearer token is required."),
                ensure_ascii=False,
            )
            raise HTTPResponse(
                body=err_data,
                status=401,
                headers={"Content-Type": "application/json; charset=utf-8", "WWW-Authenticate": "Bearer"},
            ) from None
        except Exception as exc:  # noqa: BLE001
            if is_storage_unavailable_error(exc):
                raise HTTPResponse(
                    body=json.dumps(_STORAGE_ERROR_JSON, ensure_ascii=False, separators=(",", ":")),
                    status=503,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                ) from None
            raise

    @app.error(404)
    def error404(err: Any) -> HTTPResponse:
        return _json({"error": "not found"}, 404)

    @app.error(500)
    def error500(err: Any) -> HTTPResponse:
        exc = getattr(err, "exception", None)
        if exc and is_storage_unavailable_error(exc):
            return HTTPResponse(
                body=json.dumps(_STORAGE_ERROR_JSON, ensure_ascii=False, separators=(",", ":")),
                status=503,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        return _json(error_payload("internal_error", str(exc or "Internal Server Error")), 500)

    json_dispatch = {"json-get", "json-post", "json-get-post"}
    for spec in ROUTES:
        methods: set[str] = set(spec.methods)
        if not ui_enabled and (spec.path == "/" or spec.namespace == "web"):
            continue
        dispatch = spec.dispatch
        if dispatch in json_dispatch:
            if "GET" in methods:
                app.route(spec.path, method="GET")(_json_api_route("GET"))
            if "POST" in methods:
                app.route(spec.path, method="POST")(_json_api_route("POST"))
            continue
        if dispatch == "sse":
            if ui_enabled:
                app.route(spec.path, method="GET")(events_stream)
            continue
        if dispatch == "html":
            app.route(spec.path, method="GET")(root_page)
        elif dispatch == "openapi-json":
            app.route(spec.path, method="GET")(openapi_route)
        elif dispatch == "swagger-ui":
            app.route(spec.path, method="GET")(swagger_route)
        elif dispatch == "ndjson-stream":
            app.route(spec.path, method="GET")(export_strategy_candidates)
        elif dispatch == "download":
            app.route(spec.path, method="GET")(download_backup_archive)
        elif dispatch == "upload":
            app.route(spec.path, method="POST")(upload_backup)

    def static_asset(filepath: str) -> Any:
        served = static_file(filepath, root=str(static_root()))
        if isinstance(served, HTTPResponse):
            served.set_header("Cache-Control", "public, max-age=31536000, immutable")
        return served

    if ui_enabled:
        app.route("/static/<filepath:path>", method="GET")(static_asset)

    return app
