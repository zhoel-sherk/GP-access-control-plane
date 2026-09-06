from __future__ import annotations

from ..config import AppConfig


def serve_core(config: AppConfig, host: str = "127.0.0.1", port: int = 8081) -> None:
    """Headless core mode: the same Bottle app with the UI disabled."""
    from .bottle_server import serve_web_bottle

    serve_web_bottle(config, host=host, port=port, ui_enabled=False)
