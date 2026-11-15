"""In-process fake SSE and Centrifugo WebSocket servers on 127.0.0.1 (asyncio, no network)."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response


def connect_reply(
    *,
    ping: int | None = 25,
    pong: bool | None = True,
    ttl: int | None = 86400,
    subs: tuple[str, ...] = ("broadcast", "#42"),
    command_id: int | None = None,
) -> dict[str, Any]:
    connect: dict[str, Any] = {
        "client": "c1",
        "version": "6.7.2 OSS",
        "subs": {s: {} for s in subs},
    }
    if ping is not None:
        connect["ping"] = ping
    if pong is not None:
        connect["pong"] = pong
    if ttl is not None:
        connect.update({"expires": True, "ttl": ttl})
    reply: dict[str, Any] = {"connect": connect}
    if command_id is not None:
        reply["id"] = command_id
    return reply


def pub_message(
    channel: str, message_type: str, content: dict[str, Any], *, as_string: bool = True
) -> dict[str, Any]:
    message: Any = {"type": message_type, "content": content}
    return {
        "channel": channel,
        "pub": {"data": {"message": json.dumps(message) if as_string else message}},
    }


PRODUCT_CONTENT = {
    "id": "9000000001",
    "app_id": "730",
    "asset_id": "7000000001",
    "class_id": "7100000001",
    "instance_id": "0",
    "price": "0.020",
    "name_hash": "AK-47 | Test (Field-Tested)",
    "inspect_url": "",
    "delivery_type": "INSTANT",
    "delivery_promise": "10min",
    "float": "0.1500",
    "paint_index": "1",
    "paint_seed": "2",
    "stickers": [],
    "keychains": [],
}


@dataclass
class SseScript:
    """One SSE connection: the status and headers, then frames (bytes) and pauses (seconds)."""

    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    steps: list[bytes | float] = field(default_factory=list)
    hold: bool = True  # keep the stream open after the steps (else close it)


def sse_data(payload: dict[str, Any]) -> bytes:
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


def _is_proactor_accept(task: "asyncio.Task[Any]") -> bool:
    """The accept loop of Windows' `IocpProactor` (`asyncio.windows_events`)."""
    name = getattr(task.get_coro(), "__qualname__", "")
    return isinstance(name, str) and name.endswith("accept.<locals>.accept_coro")


class FakeSseServer:
    """Serves one `SseScript` per connection, in order (the last repeats). Records the requests."""

    def __init__(self, scripts: list[SseScript]) -> None:
        self.scripts = scripts
        self.requests: list[dict[str, Any]] = []
        self.open_streams = 0
        self._server: asyncio.Server | None = None

    @property
    def url(self) -> str:
        assert self._server is not None
        port = self._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}/sse_endpoint"

    async def __aenter__(self) -> "FakeSseServer":
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()
        # [observed 2026-11-15, CI on Windows] the proactor's accept task is cancelled by
        # `close()` but ends only on a later loop turn; tests that check for leaked tasks would
        # see it. Let it end (a bounded number of turns).
        for _ in range(100):
            if not any(_is_proactor_accept(task) for task in asyncio.all_tasks()):
                break
            await asyncio.sleep(0)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode().split("\r\n")
            method, target, _ = lines[0].split(" ")
            headers = {
                k.lower(): v for k, v in (line.split(": ", 1) for line in lines[1:] if ": " in line)
            }
            parts = urlsplit(target)
            index = min(len(self.requests), len(self.scripts) - 1)
            self.requests.append(
                {
                    "method": method,
                    "path": parts.path,
                    "query": parse_qs(parts.query),
                    "headers": headers,
                }
            )
            script = self.scripts[index]
            reason = {
                200: "OK",
                401: "Unauthorized",
                302: "Found",
                429: "Too Many Requests",
                503: "Service Unavailable",
            }.get(script.status, "X")
            out = [
                f"HTTP/1.1 {script.status} {reason}",
                "Content-Type: text/event-stream",
                "Connection: close",
            ]
            out += [f"{k}: {v}" for k, v in script.headers.items()]
            writer.write(("\r\n".join(out) + "\r\n\r\n").encode())
            await writer.drain()
            if script.status != 200:
                return
            self.open_streams += 1
            try:
                for step in script.steps:
                    if isinstance(step, float):
                        await asyncio.sleep(step)
                    else:
                        writer.write(step)
                        await writer.drain()
                if script.hold:
                    await reader.read()  # until the client goes away
            finally:
                self.open_streams -= 1
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()


WsScript = Callable[["FakeWsConnection"], Awaitable[None]]


class FakeWsConnection:
    """What a WS script sees: the commands received and helpers to answer them."""

    def __init__(self, ws: ServerConnection) -> None:
        self.ws = ws
        self.commands: list[dict[str, Any]] = []

    async def recv_command(self) -> dict[str, Any]:
        raw = await self.ws.recv()
        text = raw if isinstance(raw, str) else raw.decode()
        # a frame may hold several `\n`-separated commands; keep the first, queue the rest
        parts = [json.loads(line) for line in text.split("\n") if line]
        self.commands.extend(parts)
        return parts[0]

    async def send(self, *messages: dict[str, Any]) -> None:
        await self.ws.send("\n".join(json.dumps(m) for m in messages))

    async def send_raw(self, text: str) -> None:
        await self.ws.send(text)

    async def accept_connect(self, **reply: Any) -> dict[str, Any]:
        command = await self.recv_command()
        assert "connect" in command
        await self.send(connect_reply(command_id=command["id"], **reply))
        return command

    async def accept_subscribes(self, count: int) -> None:
        for _ in range(count):
            command = await self.recv_command()
            assert "subscribe" in command
            await self.send({"id": command["id"], "subscribe": {}})

    async def hold(self) -> None:
        """Answer pings/commands never; wait until the client closes."""
        try:
            while True:
                await self.ws.recv()
        except ConnectionClosed:
            return


class FakeCentrifugoServer:
    """Runs one `WsScript` per connection, in order (the last repeats)."""

    def __init__(
        self,
        scripts: list[WsScript],
        *,
        upgrade_status: dict[int, tuple[int, dict[str, str]]] | None = None,
    ) -> None:
        self.scripts = scripts
        self.connections: list[FakeWsConnection] = []
        self.attempts = 0
        self.upgrade_status = upgrade_status or {}
        self._server: Any = None

    @property
    def url(self) -> str:
        port = self._server.sockets[0].getsockname()[1]
        return f"ws://127.0.0.1:{port}/ws_endpoint"

    async def __aenter__(self) -> "FakeCentrifugoServer":
        self._server = await serve(
            self._handle, "127.0.0.1", 0, process_request=self._process, logger=_quiet()
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._server.close()
        await self._server.wait_closed()

    def _process(self, connection: ServerConnection, request: Request) -> Response | None:
        index = self.attempts
        self.attempts += 1
        override = self.upgrade_status.get(index)
        if override is None:
            return None
        status, headers = override
        return Response(status, "X", Headers(headers), b"")

    async def _handle(self, ws: ServerConnection) -> None:
        conn = FakeWsConnection(ws)
        self.connections.append(conn)
        index = min(len(self.connections) - 1, len(self.scripts) - 1)
        try:
            await self.scripts[index](conn)
        except ConnectionClosed:
            return  # the client left while the script was still talking


def _quiet() -> Any:
    logger = logging.getLogger("fake-centrifugo")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger
