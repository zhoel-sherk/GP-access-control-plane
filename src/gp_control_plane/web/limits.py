"""web.limits — shared HTTP/media constants for the web layer.

Central home for constants previously living on the legacy ``api_server._http``
request-handler module (NDJSON media type and request/upload size limits), so
they survive the removal of that module.
"""

from __future__ import annotations

from gp_control_plane.resource_budget import (
    BACKUP_UPLOAD_MAX_BYTES,
    JSON_REQUEST_MAX_BYTES,
)

MAX_BACKUP_UPLOAD_BYTES = BACKUP_UPLOAD_MAX_BYTES
MAX_JSON_REQUEST_BYTES = JSON_REQUEST_MAX_BYTES

NDJSON_CONTENT_TYPE = "application/x-ndjson; charset=utf-8"
