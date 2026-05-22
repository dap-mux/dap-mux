"""Tests for multi-client DAP multiplexer (M3)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from dap_mux.mux import Multiplexer, SessionPhase

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


class TestConcurrentInitialize:
    """Two clients send initialize before the adapter responds to the first."""

    @pytest.mark.asyncio
    async def test_concurrent_initialize_both_succeed(
        self,
        mux_port: int,
        fake_adapter: FakeAdapter,
    ) -> None:
        """Both clients get an initialize response even when they race to send it."""
        from conftest import FakeClient as FC

        c1 = FC()
        c2 = FC()
        await c1.connect("127.0.0.1", mux_port)
        await c2.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        # Both send initialize without waiting.
        await c1.send("initialize", {"clientID": "helix", "adapterID": "debugpy"})
        await c2.send("initialize", {"clientID": "ipython", "adapterID": "debugpy"})

        resp1 = await c1.wait_for_response("initialize")
        resp2 = await c2.wait_for_response("initialize")

        assert resp1["success"] is True
        assert resp2["success"] is True
        assert resp1["body"] == resp2["body"]

        # The adapter must receive exactly one initialize.
        init_count = sum(1 for m in fake_adapter.received if m.get("command") == "initialize")
        assert init_count == 1

        await c1.close()
        await c2.close()


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

    @pytest.mark.asyncio
    async def test_late_join_receives_initialized_replay(
        self,
        client: FakeClient,
        mux_port: int,
        fake_adapter: FakeAdapter,
    ) -> None:
        """A late-joining client receives the cached initialized event so it can proceed."""
        await client.send("initialize", {"clientID": "helix", "adapterID": "debugpy"})
        await client.wait_for_response("initialize")
        await fake_adapter.send_event("initialized", {})
        await client.wait_for_event("initialized")

        from conftest import FakeClient as FC

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        await c2.send("initialize", {"clientID": "repl", "adapterID": "debugpy"})
        await c2.wait_for_response("initialize")

        evt = await c2.wait_for_event("initialized")
        assert evt["type"] == "event"
        assert evt["event"] == "initialized"

        await c2.close()

    @pytest.mark.asyncio
    async def test_late_join_receives_stopped_replay(
        self,
        client: FakeClient,
        mux_port: int,
        fake_adapter: FakeAdapter,
    ) -> None:
        """A client joining while the session is stopped gets the cached stopped event."""
        # First client initializes and the adapter fires a stopped event.
        await client.send("initialize", {"clientID": "helix", "adapterID": "debugpy"})
        await client.wait_for_response("initialize")
        await fake_adapter.send_event("stopped", {"reason": "breakpoint", "threadId": 1})
        await client.wait_for_event("stopped")

        # Second client connects and late-joins.
        from conftest import FakeClient as FC

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        await c2.send("initialize", {"clientID": "repl", "adapterID": "debugpy"})
        await c2.wait_for_response("initialize")

        # The mux should replay the stopped event to the late joiner.
        evt = await c2.wait_for_event("stopped")
        assert evt["body"]["reason"] == "breakpoint"
        assert evt["body"]["threadId"] == 1

        await c2.close()

    @pytest.mark.asyncio
    async def test_late_join_no_replay_after_continued(
        self,
        client: FakeClient,
        mux_port: int,
        fake_adapter: FakeAdapter,
    ) -> None:
        """No stopped replay if the session continued before the client joined."""
        await client.send("initialize", {"clientID": "helix", "adapterID": "debugpy"})
        await client.wait_for_response("initialize")

        await fake_adapter.send_event("stopped", {"reason": "breakpoint", "threadId": 1})
        await client.wait_for_event("stopped")
        await fake_adapter.send_event("continued", {"threadId": 1})
        await client.wait_for_event("continued")

        from conftest import FakeClient as FC

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        await c2.send("initialize", {"clientID": "repl", "adapterID": "debugpy"})
        await c2.wait_for_response("initialize")

        # Allow a moment for any unexpected replay to arrive.
        await asyncio.sleep(0.05)
        events = [m for m in c2.received if m.get("type") == "event"]
        assert not any(e.get("event") == "stopped" for e in events)

        await c2.close()

    @pytest.mark.asyncio
    async def test_stopped_state_replaced_by_new_stop(
        self,
        client: FakeClient,
        mux_port: int,
        fake_adapter: FakeAdapter,
    ) -> None:
        """The cached stopped event is always the most recent one."""
        await client.send("initialize", {"clientID": "helix", "adapterID": "debugpy"})
        await client.wait_for_response("initialize")

        await fake_adapter.send_event("stopped", {"reason": "breakpoint", "threadId": 1})
        await client.wait_for_event("stopped")
        await fake_adapter.send_event("continued", {"threadId": 1})
        await client.wait_for_event("continued")
        await fake_adapter.send_event("stopped", {"reason": "step", "threadId": 2})
        await client.wait_for_event("stopped")

        from conftest import FakeClient as FC

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        await c2.send("initialize", {"clientID": "repl", "adapterID": "debugpy"})
        await c2.wait_for_response("initialize")

        evt = await c2.wait_for_event("stopped")
        assert evt["body"]["reason"] == "step"
        assert evt["body"]["threadId"] == 2

        await c2.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _configure_session(client: FakeClient) -> None:
    """Drive a client through the full configuration phase."""
    await client.send("initialize", {"clientID": "first", "adapterID": "debugpy"})
    await client.wait_for_response("initialize")
    await client.send("attach", {})
    await client.wait_for_response("attach")
    await client.send("configurationDone", {})
    await client.wait_for_response("configurationDone")


# ---------------------------------------------------------------------------
# Session-phase interception
# ---------------------------------------------------------------------------


class TestSessionPhaseInterception:
    """attach/launch/configurationDone from late-joining clients are intercepted."""

    @pytest.mark.asyncio
    async def test_phase_advances_to_configured(self, client: FakeClient, mux: Multiplexer) -> None:
        """configurationDone advances the session phase to CONFIGURED."""
        assert mux._phase == SessionPhase.PRE_INIT
        await _configure_session(client)
        assert mux._phase == SessionPhase.CONFIGURED

    @pytest.mark.asyncio
    async def test_first_attach_forwarded(self, client: FakeClient, fake_adapter: FakeAdapter) -> None:
        """First client's attach is forwarded to the adapter normally."""
        await client.send("initialize", {"clientID": "c1", "adapterID": "debugpy"})
        await client.wait_for_response("initialize")
        await client.send("attach", {})
        resp = await client.wait_for_response("attach")
        assert resp["success"] is True
        assert any(m.get("command") == "attach" for m in fake_adapter.received)

    @pytest.mark.asyncio
    async def test_second_client_attach_intercepted(
        self, client: FakeClient, mux_port: int, fake_adapter: FakeAdapter
    ) -> None:
        """After configurationDone, a second client's attach gets synthetic success."""
        from conftest import FakeClient as FC

        await _configure_session(client)
        attach_count = sum(1 for m in fake_adapter.received if m.get("command") == "attach")

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await c2.send("initialize", {"clientID": "c2", "adapterID": "debugpy"})
        await c2.wait_for_response("initialize")
        await c2.send("attach", {})
        resp = await c2.wait_for_response("attach")

        assert resp["success"] is True
        # Adapter must NOT have received a second attach.
        assert sum(1 for m in fake_adapter.received if m.get("command") == "attach") == attach_count
        await c2.close()

    @pytest.mark.asyncio
    async def test_second_client_configuration_done_intercepted(
        self, client: FakeClient, mux_port: int, fake_adapter: FakeAdapter
    ) -> None:
        """configurationDone from a late joiner gets synthetic success."""
        from conftest import FakeClient as FC

        await _configure_session(client)
        cd_count = sum(1 for m in fake_adapter.received if m.get("command") == "configurationDone")

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await c2.send("initialize", {"clientID": "c2", "adapterID": "debugpy"})
        await c2.wait_for_response("initialize")
        await c2.send("configurationDone", {})
        resp = await c2.wait_for_response("configurationDone")

        assert resp["success"] is True
        assert sum(1 for m in fake_adapter.received if m.get("command") == "configurationDone") == cd_count
        await c2.close()

    @pytest.mark.asyncio
    async def test_late_joiner_can_still_debug(
        self, client: FakeClient, mux_port: int, fake_adapter: FakeAdapter
    ) -> None:
        """After synthetic attach/configurationDone, the late joiner can send normal requests."""
        from conftest import FakeClient as FC

        await _configure_session(client)
        await fake_adapter.send_event("stopped", {"reason": "breakpoint", "threadId": 1})

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await c2.send("initialize", {"clientID": "c2", "adapterID": "debugpy"})
        await c2.wait_for_response("initialize")
        await c2.send("attach", {})
        await c2.wait_for_response("attach")
        await c2.send("configurationDone", {})
        await c2.wait_for_response("configurationDone")

        await c2.send("threads")
        resp = await c2.wait_for_response("threads")
        assert resp["success"] is True
        await c2.close()


# ---------------------------------------------------------------------------
# Disruptive-command interception
# ---------------------------------------------------------------------------


class TestDisruptiveCommandInterception:
    """disconnect/terminate/restart are never forwarded to the adapter."""

    @pytest.mark.asyncio
    async def test_disconnect_not_forwarded(self, client: FakeClient, fake_adapter: FakeAdapter) -> None:
        """disconnect returns synthetic success and does not reach the adapter."""
        await client.send("disconnect", {})
        resp = await client.wait_for_response("disconnect")
        assert resp["success"] is True
        assert all(m.get("command") != "disconnect" for m in fake_adapter.received)

    @pytest.mark.asyncio
    async def test_session_survives_disconnect_request(self, client: FakeClient, mux_port: int) -> None:
        """After one client sends disconnect, other clients can still use the session."""
        from conftest import FakeClient as FC

        await client.send("disconnect", {})
        await client.wait_for_response("disconnect")
        await asyncio.sleep(0.05)

        c2 = FC()
        await c2.connect("127.0.0.1", mux_port)
        await c2.send("threads")
        resp = await c2.wait_for_response("threads")
        assert resp["success"] is True
        await c2.close()

    @pytest.mark.asyncio
    async def test_terminate_not_forwarded(self, client: FakeClient, fake_adapter: FakeAdapter) -> None:
        """terminate returns synthetic success and does not reach the adapter."""
        await client.send("terminate", {})
        resp = await client.wait_for_response("terminate")
        assert resp["success"] is True
        assert all(m.get("command") != "terminate" for m in fake_adapter.received)

    @pytest.mark.asyncio
    async def test_restart_not_forwarded(self, client: FakeClient, fake_adapter: FakeAdapter) -> None:
        """restart returns synthetic success and does not reach the adapter."""
        await client.send("restart", {})
        resp = await client.wait_for_response("restart")
        assert resp["success"] is True
        assert all(m.get("command") != "restart" for m in fake_adapter.received)
