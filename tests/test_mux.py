"""Tests for the single-client DAP multiplexer (M2)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from conftest import FakeAdapter, FakeClient


class TestSingleClientProxy:
    """A single client talking to the adapter through the mux."""

    @pytest.mark.asyncio
    async def test_initialize(self, client: FakeClient, fake_adapter: FakeAdapter) -> None:
        """Client sends initialize, gets capabilities back."""
        seq = await client.send("initialize", {"clientID": "test", "adapterID": "debugpy"})
        resp = await client.wait_for_response("initialize")

        assert resp["success"] is True
        assert resp["request_seq"] == seq
        assert "supportsConfigurationDoneRequest" in resp["body"]

    @pytest.mark.asyncio
    async def test_threads(self, client: FakeClient) -> None:
        """Client queries threads through the proxy."""
        seq = await client.send("threads")
        resp = await client.wait_for_response("threads")

        assert resp["success"] is True
        assert resp["request_seq"] == seq
        assert len(resp["body"]["threads"]) == 1
        assert resp["body"]["threads"][0]["name"] == "MainThread"

    @pytest.mark.asyncio
    async def test_stack_trace(self, client: FakeClient) -> None:
        """Client queries stack trace through the proxy."""
        seq = await client.send("stackTrace", {"threadId": 1})
        resp = await client.wait_for_response("stackTrace")

        assert resp["success"] is True
        assert resp["request_seq"] == seq
        assert resp["body"]["stackFrames"][0]["name"] == "main"
        assert resp["body"]["stackFrames"][0]["line"] == 10

    @pytest.mark.asyncio
    async def test_evaluate(self, client: FakeClient) -> None:
        """Client evaluates an expression through the proxy."""
        seq = await client.send("evaluate", {"expression": "x + 1", "context": "repl"})
        resp = await client.wait_for_response("evaluate")

        assert resp["success"] is True
        assert resp["request_seq"] == seq
        assert resp["body"]["result"] == "<eval: x + 1>"

    @pytest.mark.asyncio
    async def test_seq_rewriting(self, client: FakeClient, fake_adapter: FakeAdapter) -> None:
        """Proxy rewrites seq numbers — adapter sees monotonic proxy seqs."""
        await client.send("initialize", {"clientID": "test", "adapterID": "debugpy"})
        await client.wait_for_response("initialize")
        await client.send("configurationDone")
        await client.wait_for_response("configurationDone")

        # The adapter should have seen seq 1 and 2 (proxy-assigned),
        # not the client's original seq numbers.
        adapter_seqs = [m["seq"] for m in fake_adapter.received]
        assert adapter_seqs == [1, 2]

    @pytest.mark.asyncio
    async def test_event_forwarded(self, client: FakeClient, fake_adapter: FakeAdapter) -> None:
        """Adapter events are forwarded to the client."""
        await fake_adapter.send_event("stopped", {"reason": "breakpoint", "threadId": 1})
        event = await client.wait_for_event("stopped")

        assert event["body"]["reason"] == "breakpoint"
        assert event["body"]["threadId"] == 1

    @pytest.mark.asyncio
    async def test_multiple_events(self, client: FakeClient, fake_adapter: FakeAdapter) -> None:
        """Multiple events are all forwarded."""
        await fake_adapter.send_event("output", {"category": "stdout", "output": "hello\n"})
        await fake_adapter.send_event("output", {"category": "stdout", "output": "world\n"})

        await client.wait_for_event("output")
        await asyncio.sleep(0.05)

        output_events = [m for m in client.received if m.get("event") == "output"]
        assert len(output_events) == 2


class TestFullConversation:
    """Simulate a realistic debug session through the proxy."""

    @pytest.mark.asyncio
    async def test_initialize_attach_stopped_inspect(
        self,
        client: FakeClient,
        fake_adapter: FakeAdapter,
    ) -> None:
        """Walk through: initialize → attach → configurationDone → stopped → threads → stackTrace."""
        # Initialize
        await client.send("initialize", {"clientID": "helix", "adapterID": "debugpy"})
        resp = await client.wait_for_response("initialize")
        assert resp["success"] is True

        # Attach
        await client.send("attach", {"connect": {"host": "127.0.0.1", "port": 5678}})
        resp = await client.wait_for_response("attach")
        assert resp["success"] is True

        # Configuration done
        await client.send("configurationDone")
        resp = await client.wait_for_response("configurationDone")
        assert resp["success"] is True

        # Adapter sends stopped event
        await fake_adapter.send_event("stopped", {"reason": "breakpoint", "threadId": 1})
        event = await client.wait_for_event("stopped")
        assert event["body"]["reason"] == "breakpoint"

        # Client queries threads and stack
        await client.send("threads")
        resp = await client.wait_for_response("threads")
        assert resp["body"]["threads"][0]["id"] == 1

        await client.send("stackTrace", {"threadId": 1})
        resp = await client.wait_for_response("stackTrace")
        assert resp["body"]["stackFrames"][0]["source"]["path"] == "target.py"


class TestClientDisconnect:
    """Client disconnection handling."""

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self, client: FakeClient, mux_port: int) -> None:
        """Disconnecting a client removes it from the mux."""
        # The client is connected (fixture ensures this).
        # Send a request to create a pending entry.
        await client.send("initialize", {"clientID": "test", "adapterID": "debugpy"})
        await client.wait_for_response("initialize")

        # Close the client.
        await client.close()

        # Give the mux time to notice the disconnect.
        await asyncio.sleep(0.1)

        # Connect a new client to verify the mux is still alive.
        from conftest import FakeClient as FakeClient_

        c2 = FakeClient_()
        await c2.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)
        await c2.send("threads")
        resp = await c2.wait_for_response("threads")
        assert resp["success"] is True
        await c2.close()
