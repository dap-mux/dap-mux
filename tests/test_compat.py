"""Tests for the compatibility layer."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from dap_mux.compat import (
    is_known_reverse_request,
    is_reverse_request,
    pick_reverse_request_target,
    rewrite_stale_variable_error,
    should_filter_event,
)

if TYPE_CHECKING:
    from conftest import FakeAdapter, FakeClient


class TestFilterEvents:
    """Filtering debugpy-specific custom events."""

    def test_filters_debugpy_sockets(self) -> None:
        assert should_filter_event({"type": "event", "event": "debugpySockets"})

    def test_filters_debugpy_attach(self) -> None:
        assert should_filter_event({"type": "event", "event": "debugpyAttach"})

    def test_filters_start_debugging(self) -> None:
        assert should_filter_event({"type": "event", "event": "startDebugging"})

    def test_passes_stopped(self) -> None:
        assert not should_filter_event({"type": "event", "event": "stopped"})

    def test_passes_output(self) -> None:
        assert not should_filter_event({"type": "event", "event": "output"})


class TestReverseRequests:
    """Identifying and routing reverse requests."""

    def test_run_in_terminal_is_reverse(self) -> None:
        msg = {"type": "request", "command": "runInTerminal"}
        assert is_reverse_request(msg)
        assert is_known_reverse_request(msg)

    def test_initialize_is_not_reverse(self) -> None:
        msg = {"type": "request", "command": "initialize"}
        assert is_reverse_request(msg)
        assert not is_known_reverse_request(msg)

    def test_response_is_not_reverse(self) -> None:
        msg = {"type": "response", "command": "runInTerminal"}
        assert not is_reverse_request(msg)

    def test_pick_target_prefers_opted_in(self) -> None:
        clients = {
            "helix": {"clientID": "helix"},
            "repl": {"clientID": "repl", "supportsRunInTerminalRequest": True},
        }
        msg = {"type": "request", "command": "runInTerminal"}
        assert pick_reverse_request_target(clients, msg) == "repl"

    def test_pick_target_falls_back_to_first(self) -> None:
        clients = {
            "helix": {"clientID": "helix"},
            "repl": {"clientID": "repl"},
        }
        msg = {"type": "request", "command": "runInTerminal"}
        result = pick_reverse_request_target(clients, msg)
        assert result == "helix"

    def test_pick_target_no_clients(self) -> None:
        msg = {"type": "request", "command": "runInTerminal"}
        assert pick_reverse_request_target({}, msg) is None


class TestStaleVariableRewrite:
    """Rewriting stale variable reference errors."""

    def test_rewrites_invalid_error(self) -> None:
        msg = {
            "type": "response",
            "success": False,
            "command": "variables",
            "message": "Invalid variablesReference",
        }
        result = rewrite_stale_variable_error(msg)
        assert "invalidated when execution resumes" in result["message"]

    def test_passes_through_success(self) -> None:
        msg = {
            "type": "response",
            "success": True,
            "command": "variables",
            "body": {"variables": []},
        }
        result = rewrite_stale_variable_error(msg)
        assert result is msg

    def test_passes_through_unrelated_error(self) -> None:
        msg = {
            "type": "response",
            "success": False,
            "command": "variables",
            "message": "Something else went wrong",
        }
        result = rewrite_stale_variable_error(msg)
        assert result["message"] == "Something else went wrong"


class TestMuxFiltering:
    """Integration: mux filters debugpy events before forwarding."""

    @pytest.mark.asyncio
    async def test_filtered_events_not_forwarded(
        self,
        client: FakeClient,
        fake_adapter: FakeAdapter,
    ) -> None:
        """debugpy custom events are not forwarded to clients."""
        # Send a normal event first.
        await fake_adapter.send_event("stopped", {"reason": "breakpoint", "threadId": 1})
        await client.wait_for_event("stopped")

        # Send a debugpy custom event.
        await fake_adapter.send_event("debugpySockets", {"sockets": []})
        await asyncio.sleep(0.1)

        # Client should only have the stopped event, not debugpySockets.
        events = [m for m in client.received if m.get("type") == "event"]
        event_names = [e.get("event") for e in events]
        assert "stopped" in event_names
        assert "debugpySockets" not in event_names
