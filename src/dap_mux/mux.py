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
import enum
import itertools
from typing import Any

from loguru import logger

from dap_mux.client import ClientConnection
from dap_mux.compat import (
    is_known_reverse_request,
    pick_reverse_request_target,
    rewrite_stale_variable_error,
    should_filter_event,
)
from dap_mux.protocol import DapMessage, is_event, is_request, is_response
from dap_mux.seq import SeqMap
from dap_mux.upstream import UpstreamConnection

logger = logger.bind(library="dap_mux")


class SessionPhase(enum.IntEnum):
    """Linear phases of a DAP session, in order of progression."""

    PRE_INIT = 0
    INITIALIZING = 1  # first initialize forwarded, awaiting adapter response
    INITIALIZED = 2  # adapter responded; capabilities cached
    CONFIGURED = 3  # first configurationDone forwarded; session running


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
        self._phase = SessionPhase.PRE_INIT
        self._pending_initialize: list[tuple[str, DapMessage]] = []
        self._cached_capabilities: dict[str, Any] | None = None
        self._client_init_args: dict[str, dict[str, Any]] = {}
        self._initialized_event: DapMessage | None = None
        self._last_stopped_event: DapMessage | None = None

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

        command = msg.get("command", "?")

        # Cache initialize arguments for reverse request routing.
        if command == "initialize":
            self._client_init_args[client_id] = msg.get("arguments", {})

        # Late-join: respond to initialize locally from cached capabilities.
        # DAP spec says initialize can only be sent once to the adapter.
        if command == "initialize" and self._phase >= SessionPhase.INITIALIZED:
            await self._respond_with_cached_initialize(client_id, msg)
            return

        # In-flight guard: if an initialize is already being forwarded to the
        # adapter but hasn't been responded to yet, buffer this one.  Real
        # adapters (debugpy) silently ignore a second initialize, which would
        # leave the second client waiting forever.
        if command == "initialize" and self._phase == SessionPhase.INITIALIZING:
            self._pending_initialize.append((client_id, msg))
            logger.debug("[{}] initialize buffered (first initialize still in-flight)", client_id)
            return

        if command == "initialize":
            self._phase = SessionPhase.INITIALIZING

        # Session-start phase: once the session is configured, late-joining
        # clients must not re-send attach/launch/configurationDone to the
        # adapter — doing so disrupts the running session for everyone.
        if command in ("attach", "launch") and self._phase == SessionPhase.CONFIGURED:
            await self._respond_synthetic_success(client_id, msg)
            return

        if command == "configurationDone":
            if self._phase == SessionPhase.CONFIGURED:
                await self._respond_synthetic_success(client_id, msg)
                return
            # Mark configured before forwarding so a concurrent
            # configurationDone from another client is intercepted.
            self._phase = SessionPhase.CONFIGURED

        # Session-lifecycle commands: forwarding disconnect, terminate, or
        # restart would kill or disrupt the shared session for all clients.
        # The mux owns the session lifetime; individual clients cannot end it.
        if command in ("disconnect", "terminate", "restart"):
            await self._respond_synthetic_success(client_id, msg)
            return

        original_seq = msg["seq"]
        proxy_seq = self._seq_map.allocate(client_id, original_seq)

        forwarded: dict[str, Any] = {**msg, "seq": proxy_seq}
        await self._upstream.send(forwarded)

        logger.debug("[{}→DA] {} seq={} (proxy_seq={})", client_id, command, original_seq, proxy_seq)

    async def _handle_upstream_message(self, msg: DapMessage) -> None:
        """Route a message from the adapter to the appropriate client(s)."""
        if is_response(msg):
            msg = rewrite_stale_variable_error(msg)
            await self._route_response(msg)
        elif is_event(msg):
            if should_filter_event(msg):
                return
            await self._broadcast_event(msg)
        elif is_known_reverse_request(msg):
            await self._route_reverse_request(msg)
        else:
            logger.warning("Unexpected message type from adapter: {}", msg.get("type"))

    async def _route_response(self, msg: DapMessage) -> None:
        """Send a response back to the client that made the request."""
        request_seq = msg.get("request_seq")
        if request_seq is None:
            logger.warning("Response missing request_seq: {}", msg)
            return

        # Cache capabilities from the first initialize response.
        if msg.get("command") == "initialize" and msg.get("success") and self._phase == SessionPhase.INITIALIZING:
            self._phase = SessionPhase.INITIALIZED
            self._cached_capabilities = msg.get("body")
            logger.debug("Cached adapter capabilities from initialize response")
            for buf_client_id, buf_msg in self._pending_initialize:
                await self._respond_with_cached_initialize(buf_client_id, buf_msg)
            self._pending_initialize.clear()

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

    async def _respond_with_cached_initialize(self, client_id: str, msg: DapMessage) -> None:
        """Respond to a late-joining client's initialize with cached capabilities."""
        client = self._clients.get(client_id)
        if client is None:
            return

        response: dict[str, Any] = {
            "seq": 0,
            "type": "response",
            "request_seq": msg["seq"],
            "success": True,
            "command": "initialize",
        }
        if self._cached_capabilities is not None:
            response["body"] = self._cached_capabilities

        await client.send(response)
        logger.debug("[MUX→{}] initialize (cached capabilities)", client_id)

        if self._initialized_event is not None:
            await client.send(self._initialized_event)
            logger.debug("[MUX→{}] initialized (replayed for late joiner)", client_id)

        if self._last_stopped_event is not None:
            await client.send(self._last_stopped_event)
            logger.debug("[MUX→{}] stopped (replayed for late joiner)", client_id)

    async def _respond_synthetic_success(self, client_id: str, msg: DapMessage) -> None:
        """Return a synthetic success response without forwarding *msg* upstream."""
        client = self._clients.get(client_id)
        if client is None:
            return
        response: dict[str, Any] = {
            "seq": 0,
            "type": "response",
            "request_seq": msg["seq"],
            "success": True,
            "command": msg.get("command", ""),
        }
        await client.send(response)
        logger.debug("[MUX→{}] {} (synthetic success)", client_id, msg.get("command"))

    async def _broadcast_event(self, msg: DapMessage) -> None:
        """Send an event to all connected clients."""
        event_name = msg.get("event", "?")
        logger.debug("[DA→*] event={}", event_name)
        if event_name == "initialized":
            self._initialized_event = msg
        elif event_name == "stopped":
            self._last_stopped_event = msg
        elif event_name in ("continued", "terminated"):
            self._last_stopped_event = None
        for client in self._clients.values():
            await client.send(msg)

    async def _route_reverse_request(self, msg: DapMessage) -> None:
        """Route a reverse request from the adapter to the best client."""
        target_id = pick_reverse_request_target(self._client_init_args, msg)
        if target_id is None:
            return
        client = self._clients.get(target_id)
        if client is None:
            logger.warning("Target client {} for reverse request is gone", target_id)
            return
        await client.send(msg)
        command = msg.get("command", "?")
        logger.debug("[DA→{}] reverse request: {}", target_id, command)

    async def _handle_client_disconnect(self, client_id: str) -> None:
        """Clean up when a client disconnects."""
        removed = self._seq_map.cleanup(client_id)
        self._client_init_args.pop(client_id, None)
        client = self._clients.pop(client_id, None)
        if client is not None:
            await client.close()
        logger.info("Client {} removed ({} pending requests cleaned up)", client_id, removed)


__all__ = ("Multiplexer", "SessionPhase")
