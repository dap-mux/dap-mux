"""
Connection to the upstream debug adapter.

An ``UpstreamConnection`` manages the TCP link to a single debug
adapter (e.g. debugpy). It reads messages from the adapter and
delivers them to a callback, and accepts outbound messages via an
asyncio queue.

"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from loguru import logger

from dap_mux.protocol import DapMessage, read_message, write_message

logger = logger.bind(library="dap_mux")


class UpstreamConnection:
    """
    Manage the connection to a debug adapter.

    The connection is established via :meth:`connect` and torn down
    via :meth:`close`. While open, two concurrent tasks run:

    * A **read loop** that passes every incoming message to *on_message*.
    * A **write loop** that drains the outbound queue.

    """

    def __init__(self, on_message: Callable[[DapMessage], Awaitable[None]]) -> None:  # noqa: D107
        self._on_message = on_message
        self._writer: asyncio.StreamWriter | None = None
        self._send_queue: asyncio.Queue[DapMessage] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(
        self,
        host: str,
        port: int,
        *,
        retry_timeout: float = 10.0,
        retry_interval: float = 0.1,
    ) -> None:
        """
        Open a TCP connection to the debug adapter at *host*:*port*.

        Retries on ``ConnectionRefusedError`` until *retry_timeout* seconds
        have elapsed so callers don't need a separate readiness probe.  A
        probe-then-connect pattern makes debug adapters (like debugpy) see a
        spurious connect/disconnect that can cause them to exit early.

        """
        deadline = asyncio.get_event_loop().time() + retry_timeout
        last_exc: Exception = ConnectionRefusedError("never attempted")
        while asyncio.get_event_loop().time() < deadline:
            try:
                reader, writer = await asyncio.open_connection(host, port)
                self._writer = writer
                self._tasks = [
                    asyncio.create_task(self._read_loop(reader), name="upstream-read"),
                    asyncio.create_task(self._write_loop(writer), name="upstream-write"),
                ]
                logger.info("Connected to debug adapter at {}:{}", host, port)
                return
            except (ConnectionRefusedError, OSError) as exc:
                last_exc = exc
                await asyncio.sleep(retry_interval)
        msg = f"Timed out connecting to debug adapter at {host}:{port} after {retry_timeout}s"
        raise TimeoutError(msg) from last_exc

    async def close(self) -> None:
        """Shut down the connection and cancel background tasks."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except ConnectionError, OSError:
                pass
            self._writer = None
        logger.info("Disconnected from debug adapter")

    @property
    def is_connected(self) -> bool:
        """Whether the upstream connection is open."""
        return self._writer is not None

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, msg: DapMessage) -> None:
        """Enqueue a message for delivery to the debug adapter."""
        await self._send_queue.put(msg)

    # ------------------------------------------------------------------
    # Internal loops
    # ------------------------------------------------------------------

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        """Read messages from the adapter until the connection closes."""
        try:
            while True:
                msg = await read_message(reader)
                await self._on_message(msg)
        except ConnectionError, asyncio.IncompleteReadError:
            logger.info("Debug adapter connection closed")
        except asyncio.CancelledError:
            raise

    async def _write_loop(self, writer: asyncio.StreamWriter) -> None:
        """Drain the send queue, writing each message to the adapter."""
        try:
            while True:
                msg = await self._send_queue.get()
                await write_message(writer, msg)
        except ConnectionError, OSError:
            logger.warning("Debug adapter connection lost during write")
        except asyncio.CancelledError:
            raise


__all__ = ("UpstreamConnection",)
