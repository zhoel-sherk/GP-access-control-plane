"""api_server POST routing handler — moved from api_server.py (package split).

JSON POST endpoints delegate to the unified ``web.api`` handler layer; only
the multipart/raw backup upload transport is handled here.
"""

from __future__ import annotations

from http import HTTPStatus
from urllib.parse import urlparse

from gp_control_plane import core_api
from gp_control_plane.backups import import_snapshot_archive
from gp_control_plane.state import has_active_runtime
from gp_control_plane.web.api import (
    ApiHttpError,
    HandlerContext,
    StorageUnavailableError,
    json_post,
)
from gp_control_plane.web.api_server._errors import (
    RequestBodyTooLarge,
    RuntimeBusyError,
)
from gp_control_plane.web.routes import JSON_POST_ROUTE_PATHS


class PostMixin:
    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if not self._authorize_api(path):
            return
        if path == "/api/core/backups/upload":
            try:
                if has_active_runtime(self.config.output.state_dir):
                    raise RuntimeBusyError()
                imported = import_snapshot_archive(self.config.output.state_dir, self._request_upload_bytes())
                self._json(core_api.backup_snapshot_payload(imported.get("snapshot") or {}), status=HTTPStatus.CREATED)
            except Exception as exc:  # noqa: BLE001
                if isinstance(exc, RuntimeBusyError):
                    self._json({"error": "runtime_busy"}, status=HTTPStatus.CONFLICT)
                elif isinstance(exc, RequestBodyTooLarge):
                    self._json({"error": str(exc)}, status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                else:
                    self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if path not in JSON_POST_ROUTE_PATHS:
            self._not_found()
            return
        if path.startswith("/api/web/") and not self.ui_enabled:
            self._not_found()
            return
        try:
            payload = self._request_json()
        except RequestBodyTooLarge as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        ctx = HandlerContext(
            config=self.config,
            runner=self.runner,
            ui_enabled=self.ui_enabled,
            runtime_role=self.runtime_role,
            web_install_enabled=self.web_install_enabled,
            method="POST",
            path=path,
            body=payload,
            authorization=self.headers.get("Authorization"),
        )
        try:
            response_payload, status = json_post(ctx)
        except ApiHttpError as exc:
            self._api_http_error(exc)
            return
        except StorageUnavailableError:
            self._storage_unavailable()
            return
        self._json(response_payload, status=HTTPStatus(status))
