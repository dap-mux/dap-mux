"""
The DAP multiplexer.

The ``Multiplexer`` is the central component: it connects upstream to
a debug adapter, accepts downstream client connections, and routes
messages between them. Requests from clients are forwarded upstream
with rewritten sequence numbers; responses are routed back to the
originating client; events are broadcast to all connected clients.

"""

from __future__ import annotations

import asyncio
import itertools
from typing import Any

from loguru import logger

from dap_mux.client import ClientConnection
from dap_mux.protocol import DapMessage, is_event, is_request, is_response
from dap_mux.seq import SeqMap
from dap_mux.upstream import UpstreamConnection

logger = logger.bind(library="dap_mux")


class Multiplexer:
    """
    DAP multiplexer: one upstream adapter, many downstream clients.

    Use :meth:`connect_upstream` to establish the adapter connection,
    then :meth:`serve` to start accepting client connections. Call
    :meth:`close` to tear everything down.

    """

    def __init__(self) -> None:  # noqa: D107
        self._seq_map = SeqMap()
        self._upstream = UpstreamConnection(on_message=self._handle_upstream_message)
        self._clients: dict[str, ClientConnection] = {}
        self._client_counter = itertools.count(1)
        self._server: asyncio.Server | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect_upstream(self, host: str, port: int) -> None:
        """Connect to the debug adapter at *host*:*port*."""
        await self._upstream.connect(host, port)

    async def serve(self, host: str, port: int) -> int:
        """
        Start accepting client connections on *host*:*port*.

        Returns the actual port the server is listening on (useful
        when *port* is 0 for OS-assigned).

        """
        self._server = await asyncio.start_server(self._accept_client, host, port)
        actual_port = self._server.sockets[0].getsockname()[1]
        logger.info("Multiplexer listening for clients on {}:{}", host, actual_port)
        return actual_port

    async def close(self) -> None:
        """Shut down all connections and the client listener."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        for client in list(self._clients.values()):
            await client.close()
        self._clients.clear()

        await self._upstream.close()
        logger.info("Multiplexer shut down")

    @property
    def client_count(self) -> int:
        """Number of currently connected clients."""
        return len(self._clients)

    # ------------------------------------------------------------------
    # Client acceptance
    # ------------------------------------------------------------------

    async def _accept_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Accept a new client connection and start its read/write loops."""
        client_id = f"client-{next(self._client_counter)}"
        client = ClientConnection(
            client_id=client_id,
            reader=reader,
            writer=writer,
            on_message=self._handle_client_message,
            on_disconnect=self._handle_client_disconnect,
        )
        self._clients[client_id] = client
        client.start()

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    async def _handle_client_message(self, client_id: str, msg: DapMessage) -> None:
        """Route a message from a downstream client to the adapter."""
        if not is_request(msg):
            logger.warning("Ignoring non-request from {}: {}", client_id, msg.get("type"))
            return

        original_seq = msg["seq"]
        proxy_seq = self._seq_map.allocate(client_id, original_seq)

        forwarded: dict[str, Any] = {**msg, "seq": proxy_seq}
        await self._upstream.send(forwarded)

        command = msg.get("command", "?")
        logger.debug("[{}→DA] {} seq={} (proxy_seq={})", client_id, command, original_seq, proxy_seq)

    async def _handle_upstream_message(self, msg: DapMessage) -> None:
        """Route a message from the adapter to the appropriate client(s)."""
        if is_response(msg):
            await self._route_response(msg)
        elif is_event(msg):
            await self._broadcast_event(msg)
        else:
            logger.warning("Unexpected message type from adapter: {}", msg.get("type"))

    async def _route_response(self, msg: DapMessage) -> None:
        """Send a response back to the client that made the request."""
        request_seq = msg.get("request_seq")
        if request_seq is None:
            logger.warning("Response missing request_seq: {}", msg)
            return

        pending = self._seq_map.resolve(request_seq)
        if pending is None:
            logger.warning("No pending request for response request_seq={}", request_seq)
            return

        client = self._clients.get(pending.client_id)
        if client is None:
            logger.debug("Client {} gone, dropping response for seq={}", pending.client_id, request_seq)
            return

        restored: dict[str, Any] = {**msg, "request_seq": pending.client_seq}
        await client.send(restored)

        command = msg.get("command", "?")
        logger.debug("[DA→{}] {} request_seq={}", pending.client_id, command, pending.client_seq)

    async def _broadcast_event(self, msg: DapMessage) -> None:
        """Send an event to all connected clients."""
        event_name = msg.get("event", "?")
        logger.debug("[DA→*] event={}", event_name)
        for client in self._clients.values():
            await client.send(msg)

    async def _handle_client_disconnect(self, client_id: str) -> None:
        """Clean up when a client disconnects."""
        removed = self._seq_map.cleanup(client_id)
        client = self._clients.pop(client_id, None)
        if client is not None:
            await client.close()
        logger.info("Client {} removed ({} pending requests cleaned up)", client_id, removed)


__all__ = ("Multiplexer",)
