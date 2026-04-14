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
        conn.connect("127.0.0.1", mux_port)
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
        conn.connect("127.0.0.1", mux_port)

        resp = await asyncio.to_thread(_blocking, conn, "threads")
        assert resp is not None
        assert resp["body"]["threads"][0]["name"] == "MainThread"

        conn.disconnect()

    @pytest.mark.asyncio
    async def test_evaluate(self, mux_port: int) -> None:
        """Evaluate an expression."""
        conn = DapConnection()
        conn.connect("127.0.0.1", mux_port)

        resp = await asyncio.to_thread(_blocking, conn, "evaluate", {"expression": "1 + 2", "context": "repl"})
        assert resp is not None
        assert resp["body"]["result"] == "<eval: 1 + 2>"

        conn.disconnect()

    @pytest.mark.asyncio
    async def test_event_updates_state(self, mux_port: int, fake_adapter: FakeAdapter) -> None:
        """Stopped event updates current_thread_id and fetches frame."""
        conn = DapConnection()
        conn.connect("127.0.0.1", mux_port)
        await asyncio.sleep(0.05)

        # Initialize so the mux accepts our requests.
        await asyncio.to_thread(_blocking, conn, "initialize", {"clientID": "test", "adapterID": "debugpy"})

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
