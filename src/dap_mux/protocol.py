"""
DAP message framing, types, and classification.

The Debug Adapter Protocol uses Content-Length framed JSON over a byte
stream (identical to LSP). This module provides the framing layer and
TypedDict definitions for the message types the multiplexer inspects.
Messages the mux doesn't need to inspect pass through as plain dicts.

"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal, NotRequired, TypedDict

from loguru import logger

logger = logger.bind(library="dap_mux")

_ENCODING = "utf-8"
_HEADER_SEPARATOR = b"\r\n\r\n"
_CONTENT_LENGTH = b"Content-Length: "


# ---------------------------------------------------------------------------
# TypedDicts — base message shapes
# ---------------------------------------------------------------------------


class DapRequest(TypedDict):
    """A DAP request message (client -> adapter)."""

    seq: int
    type: Literal["request"]
    command: str
    arguments: NotRequired[dict[str, Any]]


class DapResponse(TypedDict):
    """A DAP response message (adapter -> client)."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: str
    message: NotRequired[str]
    body: NotRequired[dict[str, Any]]


class DapEvent(TypedDict):
    """A DAP event message (adapter -> client, unsolicited)."""

    seq: int
    type: Literal["event"]
    event: str
    body: NotRequired[dict[str, Any]]


# A DAP message as it flows through the proxy — always a plain dict.
# The TypedDicts above document the shapes; the proxy treats everything
# as dicts and inspects only the fields it needs.
type DapMessage = dict[str, Any]


# ---------------------------------------------------------------------------
# Message classification
# ---------------------------------------------------------------------------


def is_request(msg: DapMessage) -> bool:
    """
    Return whether *msg* is a DAP request.

    >>> is_request({"seq": 1, "type": "request", "command": "initialize"})
    True
    >>> is_request({"seq": 1, "type": "event", "event": "stopped"})
    False

    """
    return msg.get("type") == "request"


def is_response(msg: DapMessage) -> bool:
    """
    Return whether *msg* is a DAP response.

    >>> is_response({"seq": 1, "type": "response", "request_seq": 0, "success": True, "command": "initialize"})
    True
    >>> is_response({"seq": 1, "type": "request", "command": "next"})
    False

    """
    return msg.get("type") == "response"


def is_event(msg: DapMessage) -> bool:
    """
    Return whether *msg* is a DAP event.

    >>> is_event({"seq": 1, "type": "event", "event": "stopped"})
    True
    >>> is_event({"seq": 1, "type": "response", "request_seq": 0, "success": True, "command": "next"})
    False

    """
    return msg.get("type") == "event"


# ---------------------------------------------------------------------------
# Framing — pure functions (no I/O)
# ---------------------------------------------------------------------------


def encode_message(msg: DapMessage) -> bytes:
    r"""
    Serialize a DAP message to Content-Length framed bytes.

    >>> encode_message({"seq": 1, "type": "request", "command": "next"})
    b'Content-Length: 48\r\n\r\n{"seq": 1, "type": "request", "command": "next"}'

    """
    body = json.dumps(msg, ensure_ascii=False).encode(_ENCODING)
    header = _CONTENT_LENGTH + str(len(body)).encode("ascii") + _HEADER_SEPARATOR
    return header + body


def decode_header(data: bytes) -> int:
    r"""
    Parse a Content-Length header and return the body length.

    Raises ``ValueError`` if the header is malformed.

    >>> decode_header(b"Content-Length: 42\r\n\r\n")
    42

    """
    text = data.decode("ascii")
    for line in text.split("\r\n"):
        if line.startswith("Content-Length:"):
            return int(line.split(":", 1)[1].strip())
    msg = f"Missing Content-Length in header: {text!r}"
    raise ValueError(msg)


def decode_body(data: bytes) -> DapMessage:
    """
    Deserialize a JSON body into a DAP message dict.

    >>> decode_body(b'{"seq": 1, "type": "event", "event": "stopped"}')
    {'seq': 1, 'type': 'event', 'event': 'stopped'}

    """
    return json.loads(data.decode(_ENCODING))


# ---------------------------------------------------------------------------
# Framing — async I/O
# ---------------------------------------------------------------------------


async def read_message(reader: asyncio.StreamReader) -> DapMessage:
    """
    Read one Content-Length framed DAP message from *reader*.

    Raises ``ConnectionError`` when the stream ends before a complete
    message is received.

    """
    header = await _read_header(reader)
    content_length = decode_header(header)
    body = await _read_exactly(reader, content_length)
    msg = decode_body(body)
    logger.trace("DAP recv: {}", msg)
    return msg


async def write_message(writer: asyncio.StreamWriter, msg: DapMessage) -> None:
    """Write one Content-Length framed DAP message to *writer*."""
    logger.trace("DAP send: {}", msg)
    writer.write(encode_message(msg))
    await writer.drain()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _read_header(reader: asyncio.StreamReader) -> bytes:
    """Read bytes until the header/body separator is found."""
    buf = b""
    while _HEADER_SEPARATOR not in buf:
        chunk = await reader.read(1)
        if not chunk:
            msg = "Connection closed while reading DAP header"
            raise ConnectionError(msg)
        buf += chunk
    return buf


async def _read_exactly(reader: asyncio.StreamReader, n: int) -> bytes:
    """Read exactly *n* bytes, raising on premature EOF."""
    data = await reader.readexactly(n)
    return data


__all__ = (
    "DapEvent",
    "DapMessage",
    "DapRequest",
    "DapResponse",
    "decode_body",
    "decode_header",
    "encode_message",
    "is_event",
    "is_request",
    "is_response",
    "read_message",
    "write_message",
)
