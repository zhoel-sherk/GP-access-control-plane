"""bottle_server._server — clean WSGI launcher for the Bottle WebUI server."""

from __future__ import annotations

from gp_control_plane.config import AppConfig
from gp_control_plane.engine_common import close_stale_running_runs
from gp_control_plane.web import api_server
from gp_control_plane.web import server as web_server
from gp_control_plane.web.api_server._server import _recover_runtime_before_serve
from gp_control_plane.web.bottle_server._routes import create_bottle_app


def serve_web_bottle(
    config: AppConfig,
    host: str = "127.0.0.1",
    port: int = 8080,
    *,
    ui_enabled: bool = True,
) -> None:
    """Start GP Control Plane Web UI using the Bottle WSGI application."""
    _recover_runtime_before_serve(config)
    close_stale_running_runs(config.output.state_dir)
    runner = api_server.JobRunner(
        config.output.state_dir,
        on_idle=lambda: api_server.create_post_run_snapshot(config.output.state_dir),
    )
    runtime_role = "monolith" if ui_enabled else "core"
    app = create_bottle_app(config, runner, runtime_role=runtime_role, ui_enabled=ui_enabled)
    mode = "web UI (Bottle)" if ui_enabled else "core API (Bottle)"
    print(f"GP control plane {mode} listening on http://{host}:{port}")
    web_server.serve(app, host=host, port=port)
