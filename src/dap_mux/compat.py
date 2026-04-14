"""
Debug adapter compatibility layer.

Filters, rewrites, and routes messages that need special handling
due to adapter quirks or DAP edge cases. The multiplexer calls into
this module before forwarding messages.

"""

from __future__ import annotations

from typing import Any

from loguru import logger

logger = logger.bind(library="dap_mux")

# debugpy custom events that strict DAP clients may choke on.
_DEBUGPY_FILTERED_EVENTS: frozenset[str] = frozenset(
    {
        "debugpySockets",
        "debugpyAttach",
    }
)

# Events that signal subprocess debugging (deferred — log only).
_SUBPROCESS_EVENTS: frozenset[str] = frozenset(
    {
        "startDebugging",
    }
)


def should_filter_event(msg: dict[str, Any]) -> bool:
    """
    Return whether an event should be dropped rather than forwarded.

    Filters debugpy-specific custom events that non-debugpy clients
    don't understand.

    >>> should_filter_event({"type": "event", "event": "debugpySockets"})
    True
    >>> should_filter_event({"type": "event", "event": "stopped"})
    False

    """
    event = msg.get("event", "")
    if event in _DEBUGPY_FILTERED_EVENTS:
        logger.debug("Filtering debugpy custom event: {}", event)
        return True
    if event in _SUBPROCESS_EVENTS:
        logger.info(
            "Subprocess debug event received (not yet supported): {} body={}",
            event,
            msg.get("body"),
        )
        return True
    return False


def is_reverse_request(msg: dict[str, Any]) -> bool:
    """
    Return whether a message is a reverse request from the adapter.

    DAP allows the adapter to send requests to the client (e.g.
    ``runInTerminal``). These need special routing — they cannot be
    broadcast like events.

    >>> is_reverse_request({"type": "request", "command": "runInTerminal"})
    True
    >>> is_reverse_request({"type": "response", "command": "initialize"})
    False

    """
    return msg.get("type") == "request"


# Reverse requests that the adapter may send.
_REVERSE_REQUESTS: frozenset[str] = frozenset(
    {
        "runInTerminal",
        "startDebugging",
    }
)


def is_known_reverse_request(msg: dict[str, Any]) -> bool:
    """
    Return whether this is a recognized reverse request.

    >>> is_known_reverse_request({"type": "request", "command": "runInTerminal"})
    True
    >>> is_known_reverse_request({"type": "request", "command": "initialize"})
    False

    """
    return msg.get("type") == "request" and msg.get("command", "") in _REVERSE_REQUESTS


def pick_reverse_request_target(
    clients: dict[str, dict[str, Any]],
    msg: dict[str, Any],
) -> str | None:
    """
    Choose which client should handle a reverse request.

    For ``runInTerminal``, prefer a client that declared
    ``supportsRunInTerminalRequest`` in its initialize arguments.
    Falls back to the first connected client.

    *clients* is a mapping of ``{client_id: initialize_arguments}``.

    """
    command = msg.get("command", "")

    if command == "runInTerminal":
        # Prefer a client that opted in.
        for client_id, init_args in clients.items():
            if init_args.get("supportsRunInTerminalRequest"):
                logger.debug("Routing runInTerminal to {} (opted in)", client_id)
                return client_id

    # Fall back to the first client.
    if clients:
        first = next(iter(clients))
        logger.debug("Routing {} to {} (fallback)", command, first)
        return first

    logger.warning("No clients available for reverse request: {}", command)
    return None


def rewrite_stale_variable_error(msg: dict[str, Any]) -> dict[str, Any]:
    """
    Improve error messages for stale variable reference requests.

    When execution resumes, variable references become invalid. Debug
    adapters may return cryptic errors. This rewrites them to be
    clearer to the user.

    """
    if (
        msg.get("type") == "response"
        and not msg.get("success")
        and msg.get("command") in ("variables", "scopes", "evaluate")
    ):
        original = msg.get("message", "")
        if "invalid" in original.lower() or "not found" in original.lower():
            msg = {
                **msg,
                "message": f"{original} (variable references are invalidated when execution resumes)",
            }
    return msg


__all__ = (
    "is_known_reverse_request",
    "is_reverse_request",
    "pick_reverse_request_target",
    "rewrite_stale_variable_error",
    "should_filter_event",
)
