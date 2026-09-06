"""web.server — clean threaded WSGI server for the Bottle app.

Built only from the standard library (``wsgiref`` + ``socketserver``), with no
dependency on the legacy ``api_server`` request-handler stack. Actively served
connections are tracked so callers (and tests) can force-close them on
shutdown.
"""

from __future__ import annotations

import socket
import socketserver
import threading
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer


class ThreadingWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    """Thread-per-request WSGI server with active-connection tracking."""

    daemon_threads = True
    request_queue_size = 128

    def __init__(self, server_address: tuple[str, int], handler_cls: Any = WSGIRequestHandler) -> None:
        self._request_lock = threading.Lock()
        self._active_request_sockets: set[socket.socket] = set()
        self._active_request_handler_count = 0
        super().__init__(server_address, handler_cls)

    def process_request(self, request: Any, client_address: Any) -> None:
        with self._request_lock:
            self._active_request_sockets.add(request)
            self._active_request_handler_count += 1
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._forget_request(request)
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._forget_request(request)

    def _forget_request(self, request: Any) -> None:
        with self._request_lock:
            self._active_request_sockets.discard(request)
            self._active_request_handler_count -= 1

    @property
    def active_request_handler_count(self) -> int:
        with self._request_lock:
            return self._active_request_handler_count

    @property
    def active_request_sockets(self) -> tuple[socket.socket, ...]:
        with self._request_lock:
            return tuple(self._active_request_sockets)

    def close_active_request_connections(self) -> None:
        for request in self.active_request_sockets:
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                request.close()
            except OSError:
                pass

    def server_close(self) -> None:
        self.close_active_request_connections()
        super().server_close()


class QuietWSGIRequestHandler(WSGIRequestHandler):
    def log_message(self, _format: str, *args: Any) -> None:
        return


def make_server(app: Any, host: str = "127.0.0.1", port: int = 8080, *, quiet: bool = True) -> ThreadingWSGIServer:
    """Build a threaded WSGI server hosting ``app`` on the given address."""
    handler_cls = QuietWSGIRequestHandler if quiet else WSGIRequestHandler
    server = ThreadingWSGIServer((host, port), handler_cls)
    server.set_app(app)
    return server


def serve(app: Any, host: str = "127.0.0.1", port: int = 8080) -> None:
    """Run ``app`` until interrupted (production entrypoint)."""
    server = make_server(app, host=host, port=port)
    server.serve_forever()
