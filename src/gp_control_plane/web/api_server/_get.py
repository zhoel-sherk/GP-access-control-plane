"""api_server GET/HEAD routing handler — moved from api_server.py (package split).

JSON GET endpoints delegate to the unified ``web.api`` handler layer; only
transport-shaped GETs (HTML/docs, NDJSON export, archive download, SSE) are
handled here.
"""

from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

from gp_control_plane.web.api import (
    ApiHttpError,
    HandlerContext,
    StorageUnavailableError,
    json_get,
)
from gp_control_plane.web.api_server._helpers import _query_one
from gp_control_plane.web.api_server._http import NDJSON_CONTENT_TYPE
from gp_control_plane.web.api_server._pages import index_html
from gp_control_plane.web.docs import (
    SWAGGER_HTML_CONTENT_TYPE,
    SWAGGER_PATHS,
    swagger_ui_html,
)
from gp_control_plane.web.routes import JSON_GET_ROUTE_PATHS, JSON_HEAD_ROUTE_PATHS


class GetMixin:
    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if not self._authorize_api(path):
            return
        query = parse_qs(parsed_url.query)
        if path == "/":
            if self.ui_enabled:
                self._html()
            else:
                self._json({"error": "web ui is disabled in core mode"}, status=HTTPStatus.NOT_FOUND)
        elif path == "/openapi.json":
            self._openapi_json()
        elif path in SWAGGER_PATHS:
            self._swagger()
        elif path == "/api/core/strategy-candidates/export":
            self._stream_strategy_candidates_export(query)
        elif path in JSON_GET_ROUTE_PATHS:
            if path.startswith("/api/web/") and not self.ui_enabled:
                self._not_found()
                return
            self._json_get_api(path, query)
        elif path == "/api/core/backups/download-archive":
            core_query = {"snapshot": [_query_one(query, "snapshot_id")], "file": ["archive"]}
            self._download_backup(core_query)
        elif path == "/api/web/events/stream":
            if not self.ui_enabled:
                self._not_found()
                return
            self._events()
        else:
            self._not_found()

    def _json_get_api(self, path: str, query: dict[str, list[str]]) -> None:
        ctx = HandlerContext(
            config=self.config,
            runner=self.runner,
            ui_enabled=self.ui_enabled,
            runtime_role=self.runtime_role,
            web_install_enabled=self.web_install_enabled,
            method="GET",
            path=path,
            query=query,
            authorization=self.headers.get("Authorization"),
        )
        try:
            payload, status = json_get(ctx)
        except ApiHttpError as exc:
            self._api_http_error(exc)
            return
        except StorageUnavailableError:
            self._storage_unavailable()
            return
        self._json(payload, status=HTTPStatus(status))

    def do_HEAD(self) -> None:
        path = urlparse(self.path).path
        if not self._authorize_api(path):
            return
        if path == "/":
            if self.ui_enabled:
                data = index_html().encode("utf-8")
                self._head(HTTPStatus.OK, "text/html; charset=utf-8", len(data))
            else:
                self._head(HTTPStatus.NOT_FOUND, "application/json; charset=utf-8", 0)
        elif path == "/openapi.json":
            self._head_openapi_json()
        elif path in SWAGGER_PATHS:
            data = swagger_ui_html().encode("utf-8")
            self._head(HTTPStatus.OK, SWAGGER_HTML_CONTENT_TYPE, len(data))
        elif path == "/api/core/strategy-candidates/export":
            self._head(HTTPStatus.OK, NDJSON_CONTENT_TYPE, 0)
        elif path == "/api/web/events/stream" and self.ui_enabled:
            self._head(HTTPStatus.OK, "text/event-stream; charset=utf-8", 0)
        elif path.startswith("/api/web/") and not self.ui_enabled:
            self._head(HTTPStatus.NOT_FOUND, "application/json; charset=utf-8", 0)
        elif path in JSON_HEAD_ROUTE_PATHS:
            self._head(HTTPStatus.OK, "application/json; charset=utf-8", 0)
        else:
            self._head(HTTPStatus.NOT_FOUND, "application/json; charset=utf-8", 0)
