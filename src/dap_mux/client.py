"""
Per-client connection state.

A ``ClientConnection`` manages one downstream DAP client (e.g. an
editor or REPL). It reads messages from the client, rewrites sequence
numbers, and delivers them to a callback. Outbound messages (responses
and events) are queued for delivery back to the client.

"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from loguru import logger

from dap_mux.protocol import DapMessage, read_message, write_message

logger = logger.bind(library="dap_mux")


class ClientConnection:
    """
    Manage one downstream DAP client connection.

    Each client has a unique *client_id* (assigned by the multiplexer)
    and its own send queue. The read loop calls *on_message* with the
    client id and the raw message for the multiplexer to route.

    """

    def __init__(  # noqa: D107
        self,
        client_id: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        on_message: Callable[[str, DapMessage], Awaitable[None]],
        on_disconnect: Callable[[str], Awaitable[None]],
    ) -> None:
        self.client_id = client_id
        self._reader = reader
        self._writer = writer
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self._send_queue: asyncio.Queue[DapMessage] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the read and write loops as background tasks."""
        self._tasks = [
            asyncio.create_task(self._read_loop(), name=f"client-read-{self.client_id}"),
            asyncio.create_task(self._write_loop(), name=f"client-write-{self.client_id}"),
        ]
        logger.info("Client {} connected", self.client_id)

    async def close(self) -> None:
        """Shut down this client connection and cancel background tasks."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except ConnectionError, OSError:
            pass
        logger.info("Client {} disconnected", self.client_id)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, msg: DapMessage) -> None:
        """Enqueue a message for delivery to this client."""
        await self._send_queue.put(msg)

    # ------------------------------------------------------------------
    # Internal loops
    # ------------------------------------------------------------------

    async def _read_loop(self) -> None:
        """Read messages from the client until disconnect."""
        try:
            while True:
                msg = await read_message(self._reader)
                await self._on_message(self.client_id, msg)
        except ConnectionError, asyncio.IncompleteReadError:
            logger.info("Client {} connection closed", self.client_id)
            await self._on_disconnect(self.client_id)
        except asyncio.CancelledError:
            raise

    async def _write_loop(self) -> None:
        """Drain the send queue, writing each message to the client."""
        try:
            while True:
                msg = await self._send_queue.get()
                await write_message(self._writer, msg)
        except ConnectionError, OSError:
            logger.warning("Client {} connection lost during write", self.client_id)
        except asyncio.CancelledError:
            raise


__all__ = ("ClientConnection",)
