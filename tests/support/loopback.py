"""Real loopback servers on 127.0.0.1 (threads, no network): redirects, connection reuse, drops."""

import contextlib
import socket
import socketserver
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class Seen:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class Record:
    requests: list[Seen] = field(default_factory=list)
    connections: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class _Server(ThreadingHTTPServer):
    def server_bind(self) -> None:
        # HTTPServer.server_bind calls getfqdn(), which can take half a minute.
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]


class HttpServer:
    """An HTTP/1.1 keep-alive server; `respond(handler, seen)` writes each answer."""

    def __init__(self, respond: Callable[[BaseHTTPRequestHandler, Seen], None]) -> None:
        record = self.record = Record()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self) -> None:
                super().setup()
                with record.lock:
                    record.connections += 1

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                seen = Seen(
                    self.command,
                    self.path,
                    {k.lower(): v for k, v in self.headers.items()},
                    self.rfile.read(length),
                )
                with record.lock:
                    record.requests.append(seen)
                respond(self, seen)

            def do_GET(self) -> None:
                self.do_POST()  # a GET has no body: Content-Length is absent and reads as 0

            def log_message(self, format: str, *args: Any) -> None:
                return

        self._server = _Server(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.01), daemon=True
        )

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "HttpServer":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def send(handler: BaseHTTPRequestHandler, status: int, body: bytes = b"", **headers: str) -> None:
    handler.send_response(status)
    for name, value in headers.items():
        handler.send_header(name.replace("_", "-"), value)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class RawServer:
    """Accepts connections and lets `behave(conn, request_bytes)` decide what to send (or not)."""

    def __init__(self, behave: Callable[[socket.socket, bytes], None]) -> None:
        self.record = Record()
        self._behave = behave
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(16)
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._listener.getsockname()[1]}"

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._listener.accept()
            except OSError:
                return
            with self.record.lock:
                self.record.connections += 1
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                data += chunk
            head, _, rest = data.partition(b"\r\n\r\n")
            length = 0
            for line in head.split(b"\r\n")[1:]:
                name, _, value = line.partition(b":")
                if name.strip().lower() == b"content-length":
                    length = int(value)
            while len(rest) < length:
                rest += conn.recv(65536)
            with self.record.lock:
                self.record.requests.append(Seen("POST", "/", {}, rest))
            try:
                self._behave(conn, head + b"\r\n\r\n" + rest)
            except OSError:
                return

    def __enter__(self) -> "RawServer":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop = True
        # On Linux close() alone does not wake a thread blocked in accept(); shutdown() does.
        with contextlib.suppress(OSError):
            self._listener.shutdown(socket.SHUT_RDWR)
        self._listener.close()
        self._thread.join(timeout=5)
