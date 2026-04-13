"""
Sequence number mapping for DAP request/response routing.

The multiplexer rewrites ``seq`` on requests forwarded upstream so
that the debug adapter sees a single monotonic sequence. When a
response comes back, the ``SeqMap`` resolves the proxy seq to the
original ``(client_id, client_seq)`` pair so the response can be
routed to the correct client with its original sequence number
restored.

"""

from __future__ import annotations

import time
from typing import NamedTuple

from loguru import logger

logger = logger.bind(library="dap_mux")


class PendingRequest(NamedTuple):
    """A request awaiting its response."""

    client_id: str
    client_seq: int
    timestamp: float


class SeqMap:
    """
    Bidirectional mapping between proxy seq numbers and client seq numbers.

    Thread-safety is not required — this is used from a single asyncio
    task. The class is kept simple and synchronous.

    >>> m = SeqMap()
    >>> proxy_seq = m.allocate("helix", 1)
    >>> proxy_seq
    1
    >>> m.resolve(proxy_seq)
    PendingRequest(client_id='helix', client_seq=1, timestamp=...)
    >>> m.resolve(proxy_seq) is None
    True

    """

    def __init__(self) -> None:  # noqa: D107
        self._next_seq: int = 1
        self._pending: dict[int, PendingRequest] = {}

    @property
    def next_seq(self) -> int:
        """The next proxy seq number that will be allocated."""
        return self._next_seq

    def allocate(self, client_id: str, client_seq: int) -> int:
        """
        Allocate a proxy seq number for a client request.

        Returns the proxy-side seq to use when forwarding upstream.

        """
        proxy_seq = self._next_seq
        self._next_seq += 1
        self._pending[proxy_seq] = PendingRequest(client_id, client_seq, time.monotonic())
        logger.trace(
            "SeqMap: allocated proxy_seq={} for client={} client_seq={}",
            proxy_seq,
            client_id,
            client_seq,
        )
        return proxy_seq

    def resolve(self, proxy_seq: int) -> PendingRequest | None:
        """
        Look up and remove the pending request for *proxy_seq*.

        Returns ``None`` if no pending request exists (already resolved,
        expired, or never allocated).

        """
        return self._pending.pop(proxy_seq, None)

    def cleanup(self, client_id: str) -> int:
        """
        Remove all pending requests for *client_id*.

        Returns the number of entries removed. Call this when a client
        disconnects to avoid leaking stale mappings.

        """
        stale = [seq for seq, p in self._pending.items() if p.client_id == client_id]
        for seq in stale:
            del self._pending[seq]
        if stale:
            logger.debug("SeqMap: cleaned up {} pending requests for client={}", len(stale), client_id)
        return len(stale)

    def expire(self, timeout: float) -> int:
        """
        Remove all pending requests older than *timeout* seconds.

        Returns the number of entries removed.

        """
        cutoff = time.monotonic() - timeout
        stale = [seq for seq, p in self._pending.items() if p.timestamp < cutoff]
        for seq in stale:
            pending = self._pending.pop(seq)
            logger.warning(
                "SeqMap: expired proxy_seq={} for client={} client_seq={} (no response after {:.1f}s)",
                seq,
                pending.client_id,
                pending.client_seq,
                timeout,
            )
        return len(stale)

    @property
    def pending_count(self) -> int:
        """Number of requests currently awaiting responses."""
        return len(self._pending)

    def __repr__(self) -> str:  # noqa: D105
        return f"SeqMap(next_seq={self._next_seq}, pending={len(self._pending)})"


__all__ = (
    "PendingRequest",
    "SeqMap",
)
