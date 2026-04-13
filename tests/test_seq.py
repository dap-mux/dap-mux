"""Tests for sequence number mapping."""

from __future__ import annotations

import time
from unittest.mock import patch

from dap_mux.seq import PendingRequest, SeqMap


class TestAllocateResolve:
    """Basic allocate/resolve cycle."""

    def test_allocate_returns_incrementing_seq(self) -> None:
        m = SeqMap()
        assert m.allocate("a", 1) == 1
        assert m.allocate("a", 2) == 2
        assert m.allocate("b", 1) == 3

    def test_resolve_returns_client_info(self) -> None:
        m = SeqMap()
        proxy_seq = m.allocate("helix", 42)
        result = m.resolve(proxy_seq)
        assert result is not None
        assert result.client_id == "helix"
        assert result.client_seq == 42

    def test_resolve_consumes_entry(self) -> None:
        m = SeqMap()
        proxy_seq = m.allocate("helix", 1)
        assert m.resolve(proxy_seq) is not None
        assert m.resolve(proxy_seq) is None

    def test_resolve_unknown_seq(self) -> None:
        m = SeqMap()
        assert m.resolve(999) is None

    def test_multiple_clients_independent(self) -> None:
        m = SeqMap()
        s1 = m.allocate("helix", 1)
        s2 = m.allocate("repl", 1)
        r1 = m.resolve(s1)
        r2 = m.resolve(s2)
        assert r1 is not None and r1.client_id == "helix"
        assert r2 is not None and r2.client_id == "repl"


class TestCleanup:
    """Remove all pending requests for a disconnected client."""

    def test_cleanup_removes_client_entries(self) -> None:
        m = SeqMap()
        m.allocate("helix", 1)
        m.allocate("helix", 2)
        m.allocate("repl", 1)
        removed = m.cleanup("helix")
        assert removed == 2
        assert m.pending_count == 1

    def test_cleanup_no_entries(self) -> None:
        m = SeqMap()
        assert m.cleanup("nobody") == 0

    def test_cleanup_leaves_other_clients(self) -> None:
        m = SeqMap()
        s1 = m.allocate("repl", 5)
        m.allocate("helix", 1)
        m.cleanup("helix")
        result = m.resolve(s1)
        assert result is not None and result.client_id == "repl"


class TestExpire:
    """Remove stale pending requests by age."""

    def test_expire_old_entries(self) -> None:
        m = SeqMap()
        # Allocate with a fake old timestamp.
        old_time = time.monotonic() - 120
        with patch("time.monotonic", return_value=old_time):
            m.allocate("helix", 1)
            m.allocate("helix", 2)

        # These should be expired with a 60s timeout.
        removed = m.expire(60.0)
        assert removed == 2
        assert m.pending_count == 0

    def test_expire_keeps_recent(self) -> None:
        m = SeqMap()
        m.allocate("helix", 1)
        removed = m.expire(60.0)
        assert removed == 0
        assert m.pending_count == 1

    def test_expire_mixed_ages(self) -> None:
        m = SeqMap()
        old_time = time.monotonic() - 120
        with patch("time.monotonic", return_value=old_time):
            m.allocate("helix", 1)
        m.allocate("helix", 2)

        removed = m.expire(60.0)
        assert removed == 1
        assert m.pending_count == 1


class TestPendingRequest:
    """The PendingRequest named tuple."""

    def test_fields(self) -> None:
        p = PendingRequest("client_a", 42, 1000.0)
        assert p.client_id == "client_a"
        assert p.client_seq == 42
        assert p.timestamp == 1000.0


class TestRepr:
    """SeqMap repr for debugging."""

    def test_repr(self) -> None:
        m = SeqMap()
        m.allocate("x", 1)
        assert "next_seq=2" in repr(m)
        assert "pending=1" in repr(m)
