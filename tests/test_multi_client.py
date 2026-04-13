"""Tests for multi-client DAP multiplexer (M3)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from conftest import FakeAdapter, FakeClient


class TestTwoClients:
    """Two clients sharing one debug session through the mux."""

    @pytest.mark.asyncio
    async def test_both_receive_events(
        self,
        client: FakeClient,
        mux_port: int,
        fake_adapter: FakeAdapter,
    ) -> None:
        """An event from the adapter reaches both connected clients."""
        from conftest import FakeClient as FC

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        await fake_adapter.send_event("stopped", {"reason": "breakpoint", "threadId": 1})

        evt1 = await client.wait_for_event("stopped")
        evt2 = await c2.wait_for_event("stopped")
        assert evt1["body"]["reason"] == "breakpoint"
        assert evt2["body"]["reason"] == "breakpoint"

        await c2.close()

    @pytest.mark.asyncio
    async def test_responses_routed_to_correct_client(
        self,
        client: FakeClient,
        mux_port: int,
    ) -> None:
        """Each client gets only its own responses, not the other's."""
        from conftest import FakeClient as FC

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        seq1 = await client.send("threads")
        seq2 = await c2.send("stackTrace", {"threadId": 1})

        resp1 = await client.wait_for_response("threads")
        resp2 = await c2.wait_for_response("stackTrace")

        assert resp1["request_seq"] == seq1
        assert resp1["command"] == "threads"
        assert resp2["request_seq"] == seq2
        assert resp2["command"] == "stackTrace"

        # Verify no cross-contamination: client should not have
        # stackTrace responses, c2 should not have threads responses.
        c1_commands = [m["command"] for m in client.received if m.get("type") == "response"]
        c2_commands = [m["command"] for m in c2.received if m.get("type") == "response"]
        assert "stackTrace" not in c1_commands
        assert "threads" not in c2_commands

        await c2.close()

    @pytest.mark.asyncio
    async def test_concurrent_requests(
        self,
        client: FakeClient,
        mux_port: int,
    ) -> None:
        """Both clients send requests concurrently; both get correct responses."""
        from conftest import FakeClient as FC

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        # Fire requests from both clients without waiting.
        seq_a = await client.send("evaluate", {"expression": "a", "context": "repl"})
        seq_b = await c2.send("evaluate", {"expression": "b", "context": "repl"})

        resp_a = await client.wait_for_response("evaluate")
        resp_b = await c2.wait_for_response("evaluate")

        assert resp_a["request_seq"] == seq_a
        assert resp_a["body"]["result"] == "<eval: a>"
        assert resp_b["request_seq"] == seq_b
        assert resp_b["body"]["result"] == "<eval: b>"

        await c2.close()

    @pytest.mark.asyncio
    async def test_client_disconnect_doesnt_affect_other(
        self,
        client: FakeClient,
        mux_port: int,
        fake_adapter: FakeAdapter,
    ) -> None:
        """One client disconnecting doesn't disrupt the other."""
        from conftest import FakeClient as FC

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        # c2 disconnects.
        await c2.close()
        await asyncio.sleep(0.1)

        # client should still work.
        seq = await client.send("threads")
        resp = await client.wait_for_response("threads")
        assert resp["success"] is True
        assert resp["request_seq"] == seq

        # Events still reach the surviving client.
        await fake_adapter.send_event("continued", {"threadId": 1})
        evt = await client.wait_for_event("continued")
        assert evt["body"]["threadId"] == 1


class TestLateJoinInitialize:
    """A client connecting after the session is already initialized."""

    @pytest.mark.asyncio
    async def test_late_join_gets_cached_capabilities(
        self,
        client: FakeClient,
        mux_port: int,
        fake_adapter: FakeAdapter,
    ) -> None:
        """A second client's initialize gets cached capabilities without hitting the adapter."""
        # First client initializes normally.
        await client.send("initialize", {"clientID": "helix", "adapterID": "debugpy"})
        resp1 = await client.wait_for_response("initialize")
        assert resp1["success"] is True

        adapter_msg_count = len(fake_adapter.received)

        # Second client connects and initializes.
        from conftest import FakeClient as FC

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        await c2.send("initialize", {"clientID": "repl", "adapterID": "debugpy"})
        resp2 = await c2.wait_for_response("initialize")

        assert resp2["success"] is True
        assert resp2["body"] == resp1["body"]

        # The adapter should NOT have received a second initialize.
        assert len(fake_adapter.received) == adapter_msg_count

        await c2.close()

    @pytest.mark.asyncio
    async def test_late_join_can_send_other_requests(
        self,
        client: FakeClient,
        mux_port: int,
    ) -> None:
        """After late-join initialize, the client can send normal requests."""
        # First client initializes.
        await client.send("initialize", {"clientID": "helix", "adapterID": "debugpy"})
        await client.wait_for_response("initialize")

        # Second client late-joins and then queries.
        from conftest import FakeClient as FC

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        await c2.send("initialize", {"clientID": "repl", "adapterID": "debugpy"})
        await c2.wait_for_response("initialize")

        seq = await c2.send("threads")
        resp = await c2.wait_for_response("threads")
        assert resp["success"] is True
        assert resp["request_seq"] == seq

        await c2.close()
