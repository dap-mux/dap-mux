"""Tests for the IPython extension."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from dap_mux.ipython_ext import DapConnection, DapMuxMagics, load_ipython_extension

if TYPE_CHECKING:
    from conftest import FakeAdapter


def _blocking(conn: DapConnection, command: str, args: dict | None = None) -> dict | None:
    """Run a blocking send_request — for use with asyncio.to_thread."""
    return conn.send_request(command, args)


class TestDapConnection:
    """DapConnection talking to a FakeAdapter through the mux."""

    @pytest.mark.asyncio
    async def test_connect_and_send(self, mux_port: int) -> None:
        """Connect and send a request through the mux."""
        conn = DapConnection()
        await asyncio.to_thread(conn.connect, "127.0.0.1", mux_port)
        assert conn.connected

        resp = await asyncio.to_thread(_blocking, conn, "initialize", {"clientID": "test", "adapterID": "debugpy"})
        assert resp is not None
        assert resp["success"] is True
        assert resp["command"] == "initialize"

        conn.disconnect()
        assert not conn.connected

    @pytest.mark.asyncio
    async def test_send_threads(self, mux_port: int) -> None:
        """Query threads through the connection."""
        conn = DapConnection()
        await asyncio.to_thread(conn.connect, "127.0.0.1", mux_port)

        resp = await asyncio.to_thread(_blocking, conn, "threads")
        assert resp is not None
        assert resp["body"]["threads"][0]["name"] == "MainThread"

        conn.disconnect()

    @pytest.mark.asyncio
    async def test_evaluate(self, mux_port: int) -> None:
        """Evaluate an expression."""
        conn = DapConnection()
        await asyncio.to_thread(conn.connect, "127.0.0.1", mux_port)

        resp = await asyncio.to_thread(_blocking, conn, "evaluate", {"expression": "1 + 2", "context": "repl"})
        assert resp is not None
        assert resp["body"]["result"] == "<eval: 1 + 2>"

        conn.disconnect()

    @pytest.mark.asyncio
    async def test_event_updates_state(self, mux_port: int, fake_adapter: FakeAdapter) -> None:
        """Stopped event updates current_thread_id and fetches frame."""
        conn = DapConnection()
        await asyncio.to_thread(conn.connect, "127.0.0.1", mux_port)

        # Adapter sends a stopped event.
        await fake_adapter.send_event("stopped", {"reason": "breakpoint", "threadId": 1})

        # Give the event listener time to process (it auto-fetches stack frame).
        await asyncio.sleep(0.5)

        assert conn.current_thread_id == 1
        assert conn.current_frame_id is not None
        assert conn.stopped_file == "target.py"
        assert conn.stopped_line == 10

        conn.disconnect()

    @pytest.mark.asyncio
    async def test_stop_on_entry_sends_attach_and_configure(
        self,
        mux_port: int,
        fake_adapter: FakeAdapter,
    ) -> None:
        """connect(stop_on_entry=True) forwards attach and configurationDone to the adapter."""
        conn = DapConnection()
        await asyncio.to_thread(conn.connect, "127.0.0.1", mux_port, stop_on_entry=True)
        await asyncio.sleep(0.05)

        commands = [m.get("command") for m in fake_adapter.received]
        assert "attach" in commands
        assert "configurationDone" in commands

        conn.disconnect()

    @pytest.mark.asyncio
    async def test_connect_default_does_not_send_attach(
        self,
        mux_port: int,
        fake_adapter: FakeAdapter,
    ) -> None:
        """connect() without stop_on_entry only sends initialize — no attach or configurationDone."""
        conn = DapConnection()
        await asyncio.to_thread(conn.connect, "127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        commands = [m.get("command") for m in fake_adapter.received]
        assert "attach" not in commands
        assert "configurationDone" not in commands

        conn.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self) -> None:
        """Disconnecting when not connected is a no-op."""
        conn = DapConnection()
        conn.disconnect()
        assert not conn.connected


class TestMagicCommands:
    """Magic commands send the right DAP requests."""

    def _make_magics(self) -> tuple[DapMuxMagics, DapConnection]:
        """Create magics with no shell (unit testing only)."""
        magics = DapMuxMagics(None)  # type: ignore[arg-type]
        return magics, magics.conn

    def test_step_sends_step_in(self) -> None:
        magics, conn = self._make_magics()
        conn.send_request = MagicMock(return_value={"success": True})  # type: ignore[assignment]
        conn.current_thread_id = 1
        magics.step("")
        conn.send_request.assert_called_once_with("stepIn", {"threadId": 1})

    def test_next_sends_next(self) -> None:
        magics, conn = self._make_magics()
        conn.send_request = MagicMock(return_value={"success": True})  # type: ignore[assignment]
        conn.current_thread_id = 1
        magics.next("")
        conn.send_request.assert_called_once_with("next", {"threadId": 1})

    def test_continue_sends_continue(self) -> None:
        magics, conn = self._make_magics()
        conn.send_request = MagicMock(return_value={"success": True})  # type: ignore[assignment]
        conn.current_thread_id = 1
        magics.continue_("")
        conn.send_request.assert_called_once_with("continue", {"threadId": 1})

    def test_finish_sends_step_out(self) -> None:
        magics, conn = self._make_magics()
        conn.send_request = MagicMock(return_value={"success": True})  # type: ignore[assignment]
        conn.current_thread_id = 1
        magics.finish("")
        conn.send_request.assert_called_once_with("stepOut", {"threadId": 1})

    def test_eval_sends_evaluate(self) -> None:
        magics, conn = self._make_magics()
        conn.current_frame_id = 1
        conn.send_request = MagicMock(
            return_value={
                "success": True,
                "body": {"result": "42"},
            },
        )  # type: ignore[assignment]
        magics.eval_("x + 1")
        conn.send_request.assert_called_once_with(
            "evaluate",
            {
                "expression": "x + 1",
                "frameId": 1,
                "context": "repl",
            },
        )

    def test_break_sends_set_breakpoints(self) -> None:
        magics, conn = self._make_magics()
        conn.send_request = MagicMock(
            return_value={
                "success": True,
                "body": {"breakpoints": [{"verified": True, "line": 10}]},
            },
        )  # type: ignore[assignment]
        magics.break_("target.py:10")
        conn.send_request.assert_called_once_with(
            "setBreakpoints",
            {
                "source": {"path": "target.py"},
                "breakpoints": [{"line": 10}],
            },
        )

    def test_break_with_condition(self) -> None:
        magics, conn = self._make_magics()
        conn.send_request = MagicMock(
            return_value={
                "success": True,
                "body": {"breakpoints": [{"verified": True, "line": 10}]},
            },
        )  # type: ignore[assignment]
        magics.break_("target.py:10 x > 5")
        conn.send_request.assert_called_once_with(
            "setBreakpoints",
            {
                "source": {"path": "target.py"},
                "breakpoints": [{"line": 10, "condition": "x > 5"}],
            },
        )

    def test_clear_sends_empty_breakpoints(self) -> None:
        magics, conn = self._make_magics()
        conn.send_request = MagicMock(return_value={"success": True})  # type: ignore[assignment]
        magics.clear("target.py:10")
        conn.send_request.assert_called_once_with(
            "setBreakpoints",
            {
                "source": {"path": "target.py"},
                "breakpoints": [],
            },
        )


class TestLoadExtension:
    """Extension registration."""

    def test_load_registers_magics(self) -> None:
        shell = MagicMock()
        load_ipython_extension(shell)
        shell.register_magics.assert_called_once_with(DapMuxMagics)


class TestFullSessionFlow:
    """DapConnection (IPython) + FakeClient (Helix) together — the real-world session pattern."""

    @pytest.mark.asyncio
    async def test_ipython_then_helix_can_attach_and_configure(
        self,
        mux_port: int,
        fake_adapter: FakeAdapter,
    ) -> None:
        """IPython connects first, then Helix late-joins and sends attach + configurationDone."""
        from conftest import FakeClient

        # IPython-style client connects and auto-initializes.
        conn = DapConnection()
        await asyncio.to_thread(conn.connect, "127.0.0.1", mux_port)

        assert conn.connected

        # Helix connects as a late joiner.
        helix = FakeClient()
        await helix.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        # Helix sends initialize → served from cache, not forwarded to adapter.
        adapter_count_before = len(fake_adapter.received)
        await helix.send("initialize", {"clientID": "helix", "adapterID": "debugpy"})
        init_resp = await helix.wait_for_response("initialize")
        assert init_resp["success"] is True
        # Adapter should NOT have received a second initialize.
        assert len(fake_adapter.received) == adapter_count_before

        # Helix sends attach (the :debug-remote template).
        await helix.send("attach", {})
        attach_resp = await helix.wait_for_response("attach")
        assert attach_resp["success"] is True

        # Helix sends configurationDone.
        await helix.send("configurationDone", {})
        config_resp = await helix.wait_for_response("configurationDone")
        assert config_resp["success"] is True

        # Adapter received attach and configurationDone.
        adapter_commands = [m.get("command") for m in fake_adapter.received]
        assert "attach" in adapter_commands
        assert "configurationDone" in adapter_commands

        conn.disconnect()
        await helix.close()

    @pytest.mark.asyncio
    async def test_ipython_receives_stopped_replay_and_helix_still_works(
        self,
        mux_port: int,
        fake_adapter: FakeAdapter,
    ) -> None:
        """If the session is stopped when Helix connects, both clients still work."""
        from conftest import FakeClient

        conn = DapConnection()
        await asyncio.to_thread(conn.connect, "127.0.0.1", mux_port)

        # Adapter fires a stopped event.
        await fake_adapter.send_event("stopped", {"reason": "breakpoint", "threadId": 1})
        await asyncio.sleep(0.3)  # allow auto_fetch_frame to complete

        assert conn.current_thread_id == 1

        # Helix connects while session is stopped.
        helix = FakeClient()
        await helix.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        await helix.send("initialize", {"clientID": "helix", "adapterID": "debugpy"})
        await helix.wait_for_response("initialize")

        # Helix receives the stopped replay.
        stopped_evt = await helix.wait_for_event("stopped")
        assert stopped_evt["body"]["reason"] == "breakpoint"

        # Helix can still send requests.
        await helix.send("threads")
        threads_resp = await helix.wait_for_response("threads")
        assert threads_resp["success"] is True

        conn.disconnect()
        await helix.close()


class TestConcurrentSendRequest:
    """Thread-safety of DapConnection.send_request."""

    @pytest.mark.asyncio
    async def test_two_concurrent_stacktrace_requests(self, mux_port: int) -> None:
        """Two threads sending stackTrace simultaneously both get correct responses."""
        conn = DapConnection()
        await asyncio.to_thread(conn.connect, "127.0.0.1", mux_port)

        def send_stack() -> dict | None:
            return conn.send_request("stackTrace", {"threadId": 1, "startFrame": 0, "levels": 1})

        r1, r2 = await asyncio.gather(
            asyncio.to_thread(send_stack),
            asyncio.to_thread(send_stack),
        )

        assert r1 is not None, "first stackTrace timed out"
        assert r2 is not None, "second stackTrace timed out"
        assert r1["success"] is True
        assert r2["success"] is True
        # Both should see the same stack frame content.
        assert r1["body"]["stackFrames"][0]["name"] == "main"
        assert r2["body"]["stackFrames"][0]["name"] == "main"

        conn.disconnect()

    @pytest.mark.asyncio
    async def test_auto_fetch_frame_plus_explicit_stacktrace(
        self,
        mux_port: int,
        fake_adapter: FakeAdapter,
    ) -> None:
        """_auto_fetch_frame (background) and %bt (foreground) both complete without collision."""
        conn = DapConnection()
        await asyncio.to_thread(conn.connect, "127.0.0.1", mux_port)

        # Fire a stopped event to trigger _auto_fetch_frame in background.
        await fake_adapter.send_event("stopped", {"reason": "breakpoint", "threadId": 1})

        # Immediately send a stackTrace from the "foreground" (simulating %bt running at the
        # same moment _auto_fetch_frame is starting).
        resp = await asyncio.to_thread(_blocking, conn, "stackTrace", {"threadId": 1, "startFrame": 0, "levels": 10})

        # Wait for auto_fetch_frame to settle.
        await asyncio.sleep(0.3)

        assert resp is not None, "explicit stackTrace timed out"
        assert resp["success"] is True
        assert conn.current_thread_id == 1
        assert conn.current_frame_id is not None

        conn.disconnect()
