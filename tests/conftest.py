"""
Shared test fixtures for dap-mux.

Provides ``FakeAdapter`` (a mock debug adapter) and ``FakeClient``
(a mock DAP client) for component testing without real debugpy.

"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from dap_mux.mux import Multiplexer
from dap_mux.protocol import DapMessage, read_message, write_message


class FakeAdapter:
    """
    A mock DAP debug adapter that speaks the Content-Length protocol.

    Accepts one connection, echoes success responses to all requests,
    and can emit events on demand.

    """

    def __init__(self) -> None:
        self.received: list[DapMessage] = []
        self._server: asyncio.Server | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader: asyncio.StreamReader | None = None
        self._seq = 1
        self._read_task: asyncio.Task[None] | None = None
        self._capabilities: dict[str, Any] = {
            "supportsConfigurationDoneRequest": True,
            "supportsEvaluateForHovers": True,
            "supportsSetVariable": True,
        }

    async def start(self) -> int:
        """Start listening and return the port."""
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Shut down the fake adapter."""
        if self._read_task is not None:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except ConnectionError, OSError:
                pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def send_event(self, event: str, body: dict[str, Any] | None = None) -> None:
        """Emit a DAP event to the connected proxy."""
        msg: dict[str, Any] = {"seq": self._seq, "type": "event", "event": event}
        if body is not None:
            msg["body"] = body
        self._seq += 1
        assert self._writer is not None, "No client connected to fake adapter"
        await write_message(self._writer, msg)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle the single incoming connection from the proxy."""
        self._reader = reader
        self._writer = writer
        self._read_task = asyncio.create_task(self._read_loop(reader, writer))

    async def _read_loop(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Read requests and send canned responses."""
        try:
            while True:
                msg = await read_message(reader)
                self.received.append(msg)
                await self._respond(writer, msg)
        except ConnectionError, asyncio.IncompleteReadError, asyncio.CancelledError:
            pass

    async def _respond(self, writer: asyncio.StreamWriter, request: DapMessage) -> None:
        """Send a success response for the given request."""
        command = request.get("command", "")
        response: dict[str, Any] = {
            "seq": self._seq,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": command,
        }
        self._seq += 1

        if command == "initialize":
            response["body"] = self._capabilities
        elif command == "threads":
            response["body"] = {"threads": [{"id": 1, "name": "MainThread"}]}
        elif command == "stackTrace":
            response["body"] = {
                "stackFrames": [
                    {"id": 1, "name": "main", "source": {"path": "target.py"}, "line": 10, "column": 1},
                ],
                "totalFrames": 1,
            }
        elif command == "evaluate":
            expr = request.get("arguments", {}).get("expression", "")
            response["body"] = {"result": f"<eval: {expr}>", "variablesReference": 0}

        await write_message(writer, response)


class FakeClient:
    """
    A mock DAP client that connects to the multiplexer.

    Sends requests and collects all incoming messages (responses and
    events) for assertions.

    """

    def __init__(self) -> None:
        self.received: list[DapMessage] = []
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._seq = 1
        self._read_task: asyncio.Task[None] | None = None

    async def connect(self, host: str, port: int) -> None:
        """Connect to the multiplexer."""
        self._reader, self._writer = await asyncio.open_connection(host, port)
        self._read_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        """Disconnect from the multiplexer."""
        if self._read_task is not None:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except ConnectionError, OSError:
                pass

    async def send(self, command: str, arguments: dict[str, Any] | None = None) -> int:
        """
        Send a DAP request and return the seq number used.

        The response will appear in :attr:`received` asynchronously.

        """
        msg: dict[str, Any] = {
            "seq": self._seq,
            "type": "request",
            "command": command,
        }
        if arguments is not None:
            msg["arguments"] = arguments
        seq = self._seq
        self._seq += 1
        assert self._writer is not None
        await write_message(self._writer, msg)
        return seq

    async def wait_for_response(self, command: str, timeout: float = 2.0) -> DapMessage:
        """Wait for a response to a specific command."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            for msg in self.received:
                if msg.get("type") == "response" and msg.get("command") == command:
                    return msg
            await asyncio.sleep(0.01)
        msg = f"Timed out waiting for response to {command!r}"
        raise TimeoutError(msg)

    async def wait_for_event(self, event: str, timeout: float = 2.0) -> DapMessage:
        """Wait for a specific event type."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            for msg in self.received:
                if msg.get("type") == "event" and msg.get("event") == event:
                    return msg
            await asyncio.sleep(0.01)
        msg = f"Timed out waiting for event {event!r}"
        raise TimeoutError(msg)

    async def _read_loop(self) -> None:
        """Collect all incoming messages."""
        assert self._reader is not None
        try:
            while True:
                msg = await read_message(self._reader)
                self.received.append(msg)
        except ConnectionError, asyncio.IncompleteReadError, asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def fake_adapter() -> AsyncIterator[FakeAdapter]:
    """A mock debug adapter listening on localhost."""
    adapter = FakeAdapter()
    await adapter.start()
    yield adapter
    await adapter.stop()


@pytest.fixture
async def mux(fake_adapter: FakeAdapter) -> AsyncIterator[Multiplexer]:
    """A multiplexer connected to the fake adapter, listening for clients."""
    m = Multiplexer()
    assert fake_adapter._server is not None
    adapter_port = fake_adapter._server.sockets[0].getsockname()[1]
    await m.connect_upstream("127.0.0.1", adapter_port)
    await m.serve("127.0.0.1", 0)
    yield m
    await m.close()


@pytest.fixture
async def mux_port(mux: Multiplexer) -> int:
    """The port the multiplexer is listening on for client connections."""
    assert mux._server is not None
    return mux._server.sockets[0].getsockname()[1]


@pytest.fixture
async def client(mux_port: int) -> AsyncIterator[FakeClient]:
    """A fake client connected to the multiplexer."""
    c = FakeClient()
    await c.connect("127.0.0.1", mux_port)
    # Give the mux a moment to accept the connection.
    await asyncio.sleep(0.05)
    yield c
    await c.close()
